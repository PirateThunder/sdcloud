import pytest

from pipeline.exceptions import ModelValidationError
from pipeline.expression_parser import normalize_expression, parse_expression
from pipeline.schemas import CallExpression, IfExpression, LiteralExpression


def test_dsl_functions_and_conditional_become_canonical_ast():
    seasonal = parse_expression("sin(2 * pi * time / immunity_period)")
    assert isinstance(seasonal, CallExpression)
    assert seasonal.name == "sin"

    conditional = parse_expression("if_then_else(time >= 10, high_demand, base_demand)")
    assert isinstance(conditional, IfExpression)
    assert conditional.condition.op == "ge"
    assert conditional.then.name == "high_demand"
    assert conditional.otherwise.name == "base_demand"


def test_normalizes_observed_llm_shorthands():
    expression = normalize_expression({"op": "sin", "args": [{"op": "time"}]})
    assert expression == {"op": "call", "name": "sin", "args": [{"op": "time"}]}
    assert normalize_expression(0.1) == {"op": "lit", "value": 0.1}
    assert normalize_expression("0.1") == {"op": "lit", "value": 0.1}
    assert normalize_expression({"op": "lit", "value": "0.1"}) == {
        "op": "lit",
        "value": 0.1,
    }


def test_ast_like_dsl_from_repair_is_normalized_without_eval():
    expression = parse_expression(
        "mul(div(mul(ref('base_contact_rate'), ref('susceptible')), "
        "ref('total_population')), add(lit(1.0), call('sin', time())))"
    )
    assert expression.op == "mul"
    assert expression.args[0].op == "div"
    assert expression.args[1].args[1].op == "call"
    assert expression.args[1].args[1].name == "sin"

    nary = parse_expression("mul(ref('prey'), ref('predators'), ref('predation_rate'))")
    assert nary.op == "mul"
    assert nary.args[0].op == "mul"
    assert nary.args[1].name == "predation_rate"


def test_dsl_precedence_and_math_constants():
    expression = parse_expression("-position^3 + 2^-2 + e")
    assert expression.op == "add"
    assert expression.args[0].op == "add"
    assert expression.args[0].args[0].op == "neg"
    assert expression.args[0].args[0].arg.op == "pow"
    assert expression.args[0].args[1].args[1].op == "neg"
    assert isinstance(expression.args[1], LiteralExpression)


def test_lookup_requires_a_table_identifier():
    expression = parse_expression("lookup(demand_table, time)")
    assert expression.op == "lookup"
    assert expression.table == "demand_table"
    assert expression.arg.op == "time"


@pytest.mark.parametrize(
    "source",
    [
        "__import__('os')",
        "os.system('true')",
        "population; dangerous()",
        "unknown_function(population)",
        "sin(1, 2)",
        "a < b < c",
        "population[0]",
    ],
)
def test_unsafe_or_invalid_dsl_is_rejected(source):
    with pytest.raises(ModelValidationError):
        parse_expression(source)


def test_malformed_function_ast_does_not_crash_normalizer():
    with pytest.raises(ModelValidationError, match="expects between 3 and 3"):
        normalize_expression({"op": "if_then_else", "args": [{"op": "time"}]})
