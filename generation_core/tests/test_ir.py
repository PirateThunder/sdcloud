import pytest
from pydantic import ValidationError

from pipeline.exceptions import ModelValidationError, SimulationError
from pipeline.formats import import_xmile
from pipeline.ir import binary, lit, ref
from pipeline.schemas import (
    AuxiliaryVariable,
    ModelDocument,
    SimulationParameters,
    StockVariable,
)
from pipeline.simulation import simulate_model
from tests.helpers import exponential_model, make_model


def legacy_document() -> dict:
    return {
        "schema_version": "1.0",
        "description": "legacy zero stock",
        "python_code": "raise RuntimeError('must not execute')",
        "variables": [
            {"name": "recovered", "type": "stock", "initial_value": 0, "units": "people"},
            {"name": "recovering", "type": "flow", "units": "people/day"},
        ],
        "equations": [
            {"lhs": "recovered", "rhs": "integ(recovering, 0)", "variable_type": "stock"},
            {"lhs": "recovering", "rhs": "0", "variable_type": "flow"},
        ],
    }


def test_v1_migration_preserves_zero_and_ignores_python():
    document = ModelDocument.model_validate(legacy_document())
    assert document.schema_version == "2.0"
    stock = next(item for item in document.variables if item.id == "recovered")
    assert stock.initial.value == 0
    result = simulate_model(document, SimulationParameters(final_time=1, time_step=0.25))
    assert result.variables["recovered"] == [0, 0, 0, 0, 0]
    assert result.variables["recovering"] == [0, 0, 0, 0, 0]


def test_unknown_reference_fails_closed():
    document = exponential_model()
    variables = [item.model_dump() for item in document.variables]
    variables[1]["expression"] = ref("missing").model_dump(mode="json")
    with pytest.raises(ModelValidationError, match="UNKNOWN_REFERENCE"):
        simulate_model(
            ModelDocument.model_validate(document.model_dump() | {"variables": variables}),
            SimulationParameters(),
        )


def test_incompatible_units_fail_generation():
    document = exponential_model()
    variables = [item.model_dump() for item in document.variables]
    variables[1]["units"] = {"fox": 1, "year": -1}
    with pytest.raises(ModelValidationError, match="INCOMPATIBLE_UNITS"):
        simulate_model(
            ModelDocument.model_validate(document.model_dump() | {"variables": variables}),
            SimulationParameters(),
        )


def test_auxiliary_cycle_is_rejected():
    document = make_model(
        [
            StockVariable(
                id="stock", kind="stock", initial=lit(1), units={"item": 1}, allow_isolated=True
            ),
            AuxiliaryVariable(id="a", kind="auxiliary", expression=ref("b"), units={"item": 1}),
            AuxiliaryVariable(id="b", kind="auxiliary", expression=ref("a"), units={"item": 1}),
        ]
    )
    assert document.validation.status == "failed"
    assert any(item.code == "AUXILIARY_CYCLE" for item in document.validation.issues)


def test_dynamic_constant_is_rejected():
    document = exponential_model()
    variables = [item.model_dump() for item in document.variables]
    variables[2]["expression"] = binary("add", lit(1), ref("population")).model_dump(mode="json")
    with pytest.raises(ModelValidationError, match="DYNAMIC_CONSTANT"):
        simulate_model(
            ModelDocument.model_validate(document.model_dump() | {"variables": variables}),
            SimulationParameters(),
        )


def test_xml_external_entities_are_rejected():
    with pytest.raises(ModelValidationError, match="DTD"):
        import_xmile('<!DOCTYPE model [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><xmile/>')


def test_duplicate_lookup_points_are_rejected():
    from pipeline.schemas import LookupTable

    with pytest.raises(ValidationError):
        LookupTable(id="table", points=[(0, 0), (0, 1)])


def test_stateful_capability_does_not_silently_change_engine():
    from pathlib import Path

    from pipeline.formats import import_vensim

    path = Path(__file__).parent / "fixtures" / "models" / "delay.mdl"
    document = import_vensim(path.read_text(encoding="utf-8"))
    assert document.validation.capabilities.supported["pysd_euler"]
    assert not document.validation.capabilities.supported["scipy_fixed"]
    with pytest.raises(SimulationError, match="UNSUPPORTED_ENGINE"):
        simulate_model(document, SimulationParameters(engine="scipy", integration_method="rk4"))


def test_flow_without_stock_is_rejected():
    document = exponential_model()
    variables = [item.model_dump() for item in document.variables]
    variables[1]["source"] = {"kind": "cloud", "id": "source"}
    variables[1]["target"] = {"kind": "cloud", "id": "sink"}
    document = ModelDocument.model_validate(document.model_dump() | {"variables": variables})
    with pytest.raises(ModelValidationError, match="FLOW_WITHOUT_STOCK"):
        simulate_model(document, SimulationParameters())


def test_cld_polarity_uses_known_constants():
    document = exponential_model()
    loops = document.cld_data.validation.feedback_loops
    assert len(loops) == 1
    assert loops[0].type == "reinforcing"

    from pathlib import Path

    from pipeline.formats import import_vensim

    path = Path(__file__).parent / "fixtures" / "models" / "teacup.mdl"
    document = import_vensim(path.read_text(encoding="utf-8"))
    assert any(loop.type == "balancing" for loop in document.cld_data.validation.feedback_loops)
