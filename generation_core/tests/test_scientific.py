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


def test_derived_si_units_support_analytic_rc_discharge():
    from pipeline.expression_parser import parse_expression
    from pipeline.schemas import (
        ConstantVariable,
        FlowEndpoint,
        FlowVariable,
        ModelDocument,
        StockVariable,
        TimeSettings,
    )
    from pipeline.units import canonical_units
    from pipeline.validation import finalize_model

    document = ModelDocument(
        name="RC discharge",
        description="Capacitor discharge through resistance and capacitance",
        time=TimeSettings(unit="second", final_time=50, time_step=0.01, saveper=0.05),
        variables=[
            StockVariable(
                id="charge",
                kind="stock",
                units={"coulomb": 1},
                initial=parse_expression("5"),
                derivative=parse_expression("-discharge_current"),
            ),
            FlowVariable(
                id="discharge_current",
                kind="flow",
                units={"ampere": 1},
                expression=parse_expression("charge / (resistance * capacitance)"),
                source=FlowEndpoint(kind="stock", id="charge"),
                target=FlowEndpoint(kind="cloud", id="ground"),
            ),
            ConstantVariable(
                id="resistance",
                kind="constant",
                units={"ohm": 1},
                expression=parse_expression("10"),
            ),
            ConstantVariable(
                id="capacitance",
                kind="constant",
                units={"farad": 1},
                expression=parse_expression("0.5"),
            ),
        ],
    )
    document = finalize_model(document)
    assert not [issue for issue in document.validation.issues if issue.severity == "error"]
    current = next(item for item in document.variables if item.id == "discharge_current")
    assert current.units == {"coulomb": 1, "second": -1}
    assert current.units_raw == "ampere"
    assert canonical_units({"ohm": 1, "farad": 1}) == {"second": 1}
    result = simulate_model(
        document,
        SimulationParameters(
            engine="scipy",
            integration_method="dop853",
            final_time=50,
            time_step=0.01,
            saveper=0.05,
            rtol=1e-10,
            atol=1e-12,
        ),
    )
    assert result.variables["charge"][-1] == pytest.approx(5 * math.exp(-10), abs=1e-6)


def test_compound_unit_names_are_normalized_to_base_dimensions():
    from pipeline.units import canonical_units

    assert canonical_units({"meter_per_second": 1}) == {"meter": 1, "second": -1}
    assert canonical_units({"per_second_squared": 1}) == {"second": -2}
    assert canonical_units({"meter_per_second_squared_per_meter": 1}) == {"second": -2}
    assert canonical_units({"meter_squared_per_second": 1}) == {"meter": 2, "second": -1}
    assert canonical_units({"seconds": 1, "dimensionless": 3}) == {"second": 1}


def test_vensim_blank_units_and_comments_do_not_create_control_variables():
    source = """{UTF-8}
InflowA=
    1
    ~\t
    ~\t\t|

StockA= INTEG (
    InflowA,
    10)
    ~\t
    ~\t\t|

********************************************************
    .Control
********************************************************~
    Simulation Control Parameters
    |

FINAL TIME = 10
    ~\tMonth
    ~\tFinal horizon|

INITIAL TIME = 0
    ~\tMonth
    ~\tInitial time|

SAVEPER = TIME STEP
    ~\tMonth
    ~\tOutput interval|

TIME STEP = 1
    ~\tMonth
    ~\tIntegration step|
"""
    document = import_vensim(source)
    assert [item.id for item in document.variables] == ["inflowa", "stocka"]
    assert document.time.unit == "month"
    assert document.time.final_time == 10
    result = simulate_model(document, SimulationParameters())
    assert result.variables["stocka"][-1] == 20
