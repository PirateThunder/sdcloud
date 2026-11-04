import math
from pathlib import Path

import pytest

from pipeline.codegen import export_vensim
from pipeline.formats import (
    export_csv,
    export_xmile,
    import_vensim,
    import_xmile,
)
from pipeline.schemas import SimulationParameters
from pipeline.simulation import simulate_model
from tests.helpers import exponential_model, sir_model

MODELS = Path(__file__).parent / "fixtures" / "models"


def test_exponential_analytic_methods():
    expected = 100 * math.exp(0.1)
    euler = simulate_model(
        exponential_model(),
        SimulationParameters(final_time=1, time_step=0.25, integration_method="euler"),
    )
    rk4 = simulate_model(
        exponential_model(),
        SimulationParameters(final_time=1, time_step=0.25, integration_method="rk4"),
    )
    rk45 = simulate_model(
        exponential_model(),
        SimulationParameters(final_time=1, time_step=0.25, integration_method="rk45"),
    )
    assert euler.engine == "pysd"
    assert euler.variables["population"][-1] == pytest.approx(110.3812890625)
    assert rk4.variables["population"][-1] == pytest.approx(expected, rel=1e-7)
    assert rk45.variables["population"][-1] == pytest.approx(expected, rel=1e-7)
    assert rk45.variables["growth"][-1] == pytest.approx(rk45.variables["population"][-1] * 0.1)
    assert rk45.variables["growth_rate"] == [0.1] * 5


def test_sir_zero_stock_and_conservation():
    result = simulate_model(sir_model(), SimulationParameters())
    total = sum(result.variables[name][0] for name in ("susceptible", "infectious", "recovered"))
    assert result.variables["recovered"][0] == 0
    for index in range(len(result.time)):
        assert sum(
            result.variables[name][index] for name in ("susceptible", "infectious", "recovered")
        ) == pytest.approx(total, abs=1e-6)


def test_parameter_and_stock_overrides():
    result = simulate_model(
        exponential_model(),
        SimulationParameters(
            final_time=1,
            time_step=0.25,
            parameters={"growth_rate": 0.2},
            stock_initial={"population": 200},
        ),
    )
    assert result.variables["population"][0] == 200
    assert result.variables["population"][-1] == pytest.approx(200 * 1.05**4)


@pytest.mark.parametrize(
    "filename,loader", [("teacup.mdl", import_vensim), ("teacup.xmile", import_xmile)]
)
def test_teacup_import(filename, loader):
    document = loader((MODELS / filename).read_text(encoding="utf-8"))
    result = simulate_model(document, SimulationParameters())
    expected = 70 + 110 * math.exp(-3)
    assert result.engine == "pysd"
    assert result.variables["teacup_temperature"][-1] == pytest.approx(expected, abs=0.11)


@pytest.mark.parametrize(
    "exporter,loader", [(export_vensim, import_vensim), (export_xmile, import_xmile)]
)
def test_round_trip_preserves_numerics(exporter, loader):
    original = simulate_model(
        exponential_model(), SimulationParameters(final_time=1, time_step=0.25)
    )
    document = loader(exporter(exponential_model()))
    result = simulate_model(document, SimulationParameters(final_time=1, time_step=0.25))
    for name, values in original.variables.items():
        assert result.variables[name] == pytest.approx(values)


def test_lookup_delay_and_event_models():
    lookup = import_vensim((MODELS / "lookup.mdl").read_text(encoding="utf-8"))
    lookup_result = simulate_model(lookup, SimulationParameters())
    assert lookup.tables[0].points[3] == (15, 1)
    assert lookup_result.variables["lookup_function_call"][40] == 1
    assert "lookup" in lookup.capabilities

    delay = import_vensim((MODELS / "delay.mdl").read_text(encoding="utf-8"))
    delay_result = simulate_model(delay, SimulationParameters())
    assert delay_result.engine == "pysd"
    assert delay_result.variables["input"][0] == -1
    assert delay_result.variables["input"][-1] == 4
    assert delay_result.variables["output_delay1"][-1] > 3
    assert "delay" in delay.capabilities

    events = import_vensim((MODELS / "events.mdl").read_text(encoding="utf-8"))
    event_result = simulate_model(events, SimulationParameters())
    assert event_result.variables["test_step"][:16] == [0] * 16
    assert event_result.variables["test_step"][-1] == 1
    assert event_result.variables["test_ramp"][-1] == 3


def test_csv_contains_every_series():
    result = simulate_model(exponential_model(), SimulationParameters(final_time=1, time_step=0.25))
    lines = export_csv(result).splitlines()
    assert lines[0] == "time,population,growth,growth_rate"
    assert len(lines) == 6
    assert lines[1] == "0.0,100.0,10.0,0.1"


def test_stateful_and_lookup_round_trips():
    for filename in ("delay.mdl", "lookup.mdl"):
        document = import_vensim((MODELS / filename).read_text(encoding="utf-8"))
        expected = simulate_model(document, SimulationParameters())
        for exporter, loader in ((export_vensim, import_vensim), (export_xmile, import_xmile)):
            loaded = loader(exporter(document))
            result = simulate_model(loaded, SimulationParameters())
            for name, values in expected.variables.items():
                assert result.variables[name] == pytest.approx(values, abs=1e-7)


def test_delay_and_smooth_initial_value_argument_executes():
    from pipeline.expression_parser import normalize_expression
    from pipeline.schemas import CallExpression, LiteralExpression

    document = import_vensim((MODELS / "delay.mdl").read_text(encoding="utf-8"))
    variables = []
    for item in document.variables:
        if item.id in {"output_delay1", "output_delay3", "smooth_output"}:
            expression = item.expression
            expression = expression.model_copy(
                update={"args": [*expression.args, LiteralExpression(op="lit", value=0)]}
            )
            expression = CallExpression.model_validate(
                normalize_expression(expression.model_dump(mode="json"))
            )
            item = item.model_copy(update={"expression": expression})
        variables.append(item)
    document = document.model_copy(update={"variables": variables})
    result = simulate_model(document, SimulationParameters())
    assert all(math.isfinite(value) for series in result.variables.values() for value in series)
    for exporter, loader in ((export_vensim, import_vensim), (export_xmile, import_xmile)):
        roundtripped = loader(exporter(document))
        roundtrip_result = simulate_model(roundtripped, SimulationParameters())
        for name, values in result.variables.items():
            assert roundtrip_result.variables[name] == pytest.approx(values, abs=1e-7)


def test_boolean_conditions_use_vensim_min_max():
    from pipeline.codegen import generate_python_code
    from pipeline.expression_parser import parse_expression
    from pipeline.schemas import AuxiliaryVariable, ModelDocument, StockVariable, TimeSettings

    document = ModelDocument(
        name="Boolean conditions",
        description="Boolean condition code generation",
        time=TimeSettings(unit="time", final_time=200, time_step=0.01, saveper=0.05),
        variables=[
            StockVariable(id="x", kind="stock", initial=parse_expression("0"), units={}),
            AuxiliaryVariable(
                id="switch_and",
                kind="auxiliary",
                units={},
                expression=parse_expression(
                    "if(and(gt(time,lit(50.0)),lt(time,lit(100.0))),lit(1.0),lit(0.0))"
                ),
            ),
            AuxiliaryVariable(
                id="switch_or",
                kind="auxiliary",
                units={},
                expression=parse_expression(
                    "if(or(gt(time,lit(50.0)),lt(time,lit(100.0))),lit(1.0),lit(0.0))"
                ),
            ),
        ],
    )
    code = generate_python_code(document)
    assert "np.minimum(" in code
    assert "np.maximum(" in code
    assert " AND " not in code
    assert " OR " not in code


def test_units_diagnostics_include_operation_and_operand_units():
    from pipeline.expression_parser import parse_expression
    from pipeline.schemas import AuxiliaryVariable
    from pipeline.validation import finalize_model

    document = exponential_model()
    auxiliary = AuxiliaryVariable(
        id="invalid_sum",
        kind="auxiliary",
        units={},
        expression=parse_expression("population + growth_rate"),
    )
    result = finalize_model(
        document.model_copy(update={"variables": [*document.variables, auxiliary]})
    )
    issue = next(
        item
        for item in result.validation.issues
        if item.code == "INCOMPATIBLE_UNITS" and item.path == "variables.invalid_sum.expression"
    )
    assert "add operands" in issue.message
    assert "left={'person': 1}" in issue.message
    assert "right={'year': -1}" in issue.message
