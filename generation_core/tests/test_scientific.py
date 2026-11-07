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


def test_vensim_inline_metadata_and_quoted_tildes():
    source = """{UTF-8}
"Input ~~| label"=2 ~~|
StockA=INTEG("Input ~~| label", 10) ~~|
"""
    document = import_vensim(source)
    flow = next(item for item in document.variables if item.kind == "flow")
    assert flow.label == "Input ~~| label"
    result = simulate_model(document, SimulationParameters(final_time=1, time_step=0.25, saveper=0.25))
    assert result.variables["stocka"][-1] == 12


def test_stock_free_constant_model_runs_without_a_dummy_stock():
    from pipeline.ir import lit
    from pipeline.schemas import ConstantVariable, ModelDocument, TimeSettings

    document = ModelDocument(
        description="Stock-free function model",
        time=TimeSettings(unit="year", final_time=1, time_step=0.25, saveper=0.25),
        variables=[ConstantVariable(id="answer", kind="constant", expression=lit(42), units={})],
    )
    result = simulate_model(document, SimulationParameters())
    assert result.variables["answer"] == [42, 42, 42, 42, 42]


def test_unary_power_operands_preserve_their_meaning():
    source = """{UTF-8}
expo[sub1]=(-Time)^2 ~~|
expo[sub2]=2^-2 ~~|
expo[sub3]=-Time^2 ~~|
subs:
(sub1-sub3)
    ~
    ~ |
INITIAL TIME=1 ~~|
FINAL TIME=2 ~~|
TIME STEP=1 ~~|
SAVEPER=TIME STEP ~~|
"""
    document = import_vensim(source)
    result = simulate_model(document, SimulationParameters())
    assert result.variables["expo[sub1]"][0] == 1
    assert result.variables["expo[sub2]"][0] == 0.25
    assert result.variables["expo[sub3]"][0] == -1


def test_vensim_except_stock_uses_scalar_flows_and_wildcard_exceptions():
    document = import_vensim("""{UTF-8}
initial inventory[store,product]=100 ~~|
inventory[store,product] :EXCEPT: [s2,p2]=
    INTEG(receipts[store,product]-sales[store,product],initial inventory[store,product]) ~~|
inventory[s2,p2]=INTEG(receipts[s2,p2]-sales[s2,p2]-special,initial inventory[s2,p2]) ~~|
receipts[store,product]=1 ~~|
sales[store,product]=0 ~~|
special=0.1 ~~|
store:(s1-s2) ~~|
product:(p1-p2) ~~|
INITIAL TIME=0 ~~|
FINAL TIME=1 ~~|
TIME STEP=1 ~~|
SAVEPER=TIME STEP ~~|
""")
    result = simulate_model(document, SimulationParameters())
    assert result.variables["inventory[s1,p1]"] == [100, 101]
    assert result.variables["inventory[s2,p2]"][-1] == pytest.approx(100.9)


def test_vensim_except_merges_subsets_and_resolves_dimension_indices():
    document = import_vensim("""{UTF-8}
value[dim1,dim2] :EXCEPT: [dim1up,d1]=Time ~~|
value[dim1up,dim2] :EXCEPT: [dim1up,d2]=-Time ~~|
value[dim1up,d2]=2*Time ~~|
factor[dim1]=dim1 ~~|
scaled[dim1,dim2] :EXCEPT: [dim1up,d1]=factor[dim1] ~~|
scaled[dim1up,dim2] :EXCEPT: [dim1up,d2]=factor[dim1up] ~~|
scaled[dim1up,d2]=10*factor[dim1up] ~~|
dim1:(sub1-sub4) ~~|
dim1up:(sub1-sub2) ~~|
dim2:(d1-d2) ~~|
INITIAL TIME=0 ~~|
FINAL TIME=1 ~~|
TIME STEP=1 ~~|
SAVEPER=TIME STEP ~~|
""")
    result = simulate_model(document, SimulationParameters())
    assert result.variables["value[sub1,d1]"][-1] == -1
    assert result.variables["value[sub1,d2]"][-1] == 2
    assert result.variables["value[sub4,d1]"][-1] == 1
    assert result.variables["factor[sub4]"] == [4, 4]
    assert result.variables["scaled[sub1,d2]"] == [10, 10]
    assert result.variables["scaled[sub4,d2]"] == [4, 4]


def test_vensim_subranges_aliases_and_explicit_element_projection():
    document = import_vensim("""{UTF-8}
REG:A,B ~~|
ALL:X,Y,Z ~~|
ALL MAP <-> ALL ~~|
A ONLY:X,Z ~~|
B ONLY:Y ~~|
origin[REG,A ONLY,ALL MAP]=1 ~~|
value[REG,A ONLY,ALL MAP] :EXCEPT: [B,A ONLY,ALL MAP]=origin[REG,A ONLY,ALL MAP] ~~|
value[REG,B ONLY,ALL MAP]=2 ~~|
value[B,A ONLY,ALL MAP]=3 ~~|
sparse[REG,ALL,X] :EXCEPT: [B,ALL,X]=10 ~~|
sparse[B,ALL,X]=20 ~~|
sparse[REG,ALL,Z]=30 ~~|
INITIAL TIME=0 ~~|
FINAL TIME=1 ~~|
TIME STEP=1 ~~|
SAVEPER=TIME STEP ~~|
""")
    result = simulate_model(document, SimulationParameters())
    value = next(item for item in document.variables if item.id == "value")
    sparse = next(item for item in document.variables if item.id == "sparse")
    assert value.subscripts == ["reg", "all", "all_map"]
    assert result.variables["value[A,X,Y]"] == [1, 1]
    assert result.variables["value[A,Y,X]"] == [2, 2]
    assert result.variables["value[B,X,Y]"] == [3, 3]
    assert result.variables["sparse[A,X,X]"] == [10, 10]
    assert result.variables["sparse[B,X,X]"] == [20, 20]
    assert result.variables["sparse[A,X,Z]"] == [30, 30]
    assert "sparse[A,X,Y]" not in result.variables
    assert next(
        item for item in document.dimensions if item.id == sparse.subscripts[-1]
    ).elements == ["X", "Z"]


def test_vensim_rejects_overlapping_equations_with_different_values():
    from pipeline.exceptions import ModelValidationError

    with pytest.raises(ModelValidationError, match="ambiguous subscripted assignments"):
        import_vensim("""{UTF-8}
value[full]=1 ~~|
value[subset]=2 ~~|
full:(a1-a3) ~~|
subset:(a1-a2) ~~|
""")


def test_vensim_numeric_arrays_and_element_specific_stock_derivatives():
    document = import_vensim("""{UTF-8}
rows:Entry 1,Entry 2,Entry 3 ~~|
columns:Column 1,Column 2 ~~|
initial values[rows,columns]=1,2;3,4;5,6; ~~|
stock[rows,columns]=INTEG(flow[rows,columns],initial values[rows,columns]) ~~|
flow[rows,columns]=rate[rows,columns] ~~|
rate[rows,Column 1]=1,2,3 ~~|
rate[rows,Column 2]=2 ~~|
INITIAL TIME=0 ~~|
FINAL TIME=1 ~~|
TIME STEP=1 ~~|
SAVEPER=TIME STEP ~~|
""")
    result = simulate_model(document, SimulationParameters())
    assert result.variables["stock[Entry 1,Column 1]"] == [1, 2]
    assert result.variables["stock[Entry 3,Column 1]"] == [5, 8]
    assert result.variables["stock[Entry 2,Column 2]"] == [4, 6]


def test_vensim_array_projection_preserves_fixed_and_varying_indices():
    document = import_vensim("""{UTF-8}
rows:Entry 1,Entry 2,Entry 3 ~~|
columns:Column 1,Column 2 ~~|
values[rows,columns]=1,2;3,4;5,6; ~~|
selected[rows]=values[rows,Column 2] ~~|
INITIAL TIME=0 ~~|
FINAL TIME=1 ~~|
TIME STEP=1 ~~|
SAVEPER=TIME STEP ~~|
""")
    result = simulate_model(document, SimulationParameters())
    assert result.variables["selected[Entry 1]"] == [2, 2]
    assert result.variables["selected[Entry 2]"] == [4, 4]
    assert result.variables["selected[Entry 3]"] == [6, 6]


def test_vensim_macros_support_locals_nested_calls_and_stocks():
    document = import_vensim("""{UTF-8}
:MACRO: MULTIPLY(input,factor)
MULTIPLY=input*intermediate ~~|
intermediate=factor*3 ~~|
:END OF MACRO:
:MACRO: SIX TIMES(input)
SIX TIMES=MULTIPLY(input,2) ~~|
:END OF MACRO:
:MACRO: ACCUMULATE(input,initial)
ACCUMULATE=INTEG(input,initial) ~~|
:END OF MACRO:
output=SIX TIMES(5) ~~|
level=ACCUMULATE(output,1.1) ~~|
INITIAL TIME=0 ~~|
FINAL TIME=1 ~~|
TIME STEP=1 ~~|
SAVEPER=TIME STEP ~~|
""")
    result = simulate_model(document, SimulationParameters())
    assert result.variables["output"] == [30, 30]
    assert result.variables["level"] == [1.1, 31.1]


def test_vensim_rejects_recursive_macros():
    from pipeline.exceptions import ModelValidationError

    with pytest.raises(ModelValidationError, match="recursive or excessive"):
        import_vensim("""{UTF-8}
:MACRO: LOOP(input)
LOOP=LOOP(input) ~~|
:END OF MACRO:
output=LOOP(1) ~~|
""")


def test_vensim_equivalent_dimensions_unify_only_independent_axes():
    document = import_vensim("""{UTF-8}
subset:Entry 1,Entry 2 ~~|
dim1:Entry 1,Entry 2 ~~|
stock[dim1]=INTEG(inflow[dim1],0) ~~|
inflow[dim1]=rate[dim1] ~~|
rate[dim1]=1,2 ~~|
selected[subset]=stock[subset] ~~|
INITIAL TIME=0 ~~|
FINAL TIME=1 ~~|
TIME STEP=1 ~~|
SAVEPER=TIME STEP ~~|
""")
    result = simulate_model(document, SimulationParameters())
    assert len(document.dimensions) == 1
    assert result.variables["selected[Entry 2]"] == [0, 2]
