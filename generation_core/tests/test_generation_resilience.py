import copy
import json
from pathlib import Path

import pytest

from pipeline.exceptions import LLMResponseError, ModelValidationError
from pipeline.generation import _variable_response, generate_model
from pipeline.llm import FixtureLLM
from pipeline.schemas import GenerationRequest

FIXTURE = Path(__file__).parent / "fixtures" / "llm_responses.json"


class EarlyRepairLLM(FixtureLLM):
    def __init__(self, failures=None, replacements=None):
        super().__init__(FIXTURE)
        self.failures = dict(failures or {})
        self.replacements = copy.deepcopy(replacements or {})
        self.calls = []
        self.schemas = {}

    async def chat_json(self, prompt, *, stage, system=None, temperature=0.3, response_schema=None):
        self.calls.append(stage)
        self.schemas[stage] = response_schema
        if stage in self.failures:
            failure = self.failures.pop(stage)
            if isinstance(failure, Exception):
                raise failure
            return failure
        if stage in self.replacements:
            return copy.deepcopy(self.replacements[stage])
        base_stage = stage.split("_repair_", 1)[0]
        return await super().chat_json(
            prompt,
            stage=base_stage,
            system=system,
            temperature=temperature,
            response_schema=response_schema,
        )


def request() -> GenerationRequest:
    return GenerationRequest(description="Модель хищник-жертва: кролики и лисы")


async def test_malformed_json_is_repaired_on_the_same_stage():
    llm = EarlyRepairLLM(
        failures={
            "brief": LLMResponseError("failed to parse LLM JSON", response_text="{broken")
        }
    )
    document = await generate_model(request(), llm, max_repairs=1)
    assert document.validation.status == "passed"
    assert document.repair_attempts == 1
    assert llm.calls == ["brief", "brief_repair_1", "variables", "equations"]


async def test_unknown_expression_id_is_repaired_before_full_model_repair():
    llm = EarlyRepairLLM(
        failures={"equations": {"expressions": {"not_a_variable": {"op": "lit", "value": 1}}}}
    )
    document = await generate_model(request(), llm, max_repairs=1)
    assert document.validation.status == "passed"
    assert llm.calls == ["brief", "variables", "equations", "equations_repair_1"]
    assert "repair_1" not in llm.calls


async def test_unknown_stock_initial_reference_is_repaired_on_variables_stage():
    responses = json.loads(FIXTURE.read_text(encoding="utf-8"))
    responses["variables"]["variables"][0]["initial"] = {"op": "ref", "name": "initial_prey"}
    llm = EarlyRepairLLM(replacements={"variables": responses["variables"]})
    document = await generate_model(request(), llm, max_repairs=1)
    assert document.validation.status == "passed"
    assert llm.calls == ["brief", "variables", "variables_repair_1", "equations"]


async def test_early_repair_respects_zero_budget():
    llm = EarlyRepairLLM(
        failures={"equations": {"expressions": {"not_a_variable": {"op": "lit", "value": 1}}}}
    )
    with pytest.raises(ModelValidationError, match="unknown variables"):
        await generate_model(request(), llm, max_repairs=0)
    assert llm.calls == ["brief", "variables", "equations"]


async def test_dsl_numeric_values_and_assumptions_are_normalized_without_repair():
    responses = json.loads(FIXTURE.read_text(encoding="utf-8"))
    variables = responses["variables"]
    variables["assumptions"] = [
        {
            "path": "variables.prey_growth",
            "value": 0.1,
            "source": "llm_inferred",
            "rationale": "Illustrative growth rate",
        }
    ]
    variables["variables"][0]["initial"] = 100
    for item in variables["variables"]:
        for field, value in {
            "label": None,
            "description": None,
            "units": None,
            "units_raw": None,
            "bounds": None,
            "subscripts": [],
            "initial": None,
            "derivative": None,
            "allow_isolated": False,
            "expression": None,
            "source": None,
            "target": None,
            "topology_status": "declared",
            "exogenous": False,
        }.items():
            item.setdefault(field, value)
    equations = {
        "expressions": {
            "prey_births": "prey * prey_growth",
            "predation": "prey * predators * predation_rate",
            "predator_births": "predation * conversion_efficiency",
            "predator_deaths": "predators * predator_mortality",
            "prey_growth": 0.1,
            "predation_rate": 0.02,
            "conversion_efficiency": 0.1,
            "predator_mortality": 0.1,
        }
    }
    llm = EarlyRepairLLM(replacements={"variables": variables, "equations": equations})
    document = await generate_model(request(), llm)
    assert document.validation.status == "passed"
    assert document.repair_attempts == 0
    assert document.assumptions[0].value == "0.1"
    stock = next(item for item in document.variables if item.id == "prey")
    flow = next(item for item in document.variables if item.id == "prey_births")
    assert stock.initial.value == 100
    assert flow.expression.op == "mul"
    assert llm.schemas["variables"]["required"] == [
        "name",
        "time",
        "variables",
        "tables",
        "assumptions",
    ]
    variants = llm.schemas["variables"]["properties"]["variables"]["items"]["anyOf"]
    stock_schema = next(item for item in variants if item["properties"]["kind"]["enum"] == ["stock"])
    constant_schema = next(
        item for item in variants if item["properties"]["kind"]["enum"] == ["constant"]
    )
    assert {"type": "null"} not in stock_schema["properties"]["initial"]["anyOf"]
    assert {"type": "null"} in constant_schema["properties"]["initial"]["anyOf"]
    assert llm.schemas["equations"]["required"] == ["expressions"]


def test_nonstock_initial_becomes_expression_before_kind_filtering():
    _, variables = _variable_response(
        {
            "variables": [
                {
                    "id": "rate",
                    "kind": "constant",
                    "units": {"year": -1},
                    "initial": 0.1,
                    "expression": None,
                }
            ]
        }
    )
    assert variables[0]["expression"] == {"op": "lit", "value": 0.1}
    assert "initial" not in variables[0]


def valid_repair_payload():
    from pipeline.generation import _repair_payload
    from pipeline.pattern_library import get_pattern

    return _repair_payload(get_pattern("predator_prey").document)


async def test_invalid_final_repair_uses_remaining_budget():
    llm = EarlyRepairLLM(
        replacements={
            "equations": {
                "expressions": {
                    "prey_births": "prey + prey_growth",
                    "predation": "prey * predators * predation_rate",
                    "predator_births": "predation * conversion_efficiency",
                    "predator_deaths": "predators * predator_mortality",
                    "prey_growth": 0.1,
                    "predation_rate": 0.02,
                    "conversion_efficiency": 0.1,
                    "predator_mortality": 0.1,
                }
            },
            "repair_1": {"variables": []},
            "repair_2": valid_repair_payload(),
        }
    )
    document = await generate_model(request(), llm, max_repairs=2)
    assert document.validation.status == "passed"
    assert document.repair_attempts == 2
    assert llm.calls[-2:] == ["repair_1", "repair_2"]


def test_final_repair_preserves_previous_expressions_for_null_values():
    from pipeline.generation import _repair

    payload = valid_repair_payload()
    for item in payload["variables"]:
        if item["kind"] != "stock":
            item["expression"] = None
            item["initial"] = None
    from pipeline.pattern_library import get_pattern

    original = get_pattern("predator_prey").document
    repaired = _repair(original, payload, 1)
    assert [item.expression for item in repaired.variables if item.kind != "stock"] == [
        item.expression for item in original.variables if item.kind != "stock"
    ]


async def test_smoke_failure_uses_repair_budget(monkeypatch):
    import pipeline.generation as generation

    original_simulate = generation.simulate_model
    calls = 0
    horizons = []

    def fail_first_smoke(document, parameters):
        nonlocal calls
        calls += 1
        horizons.append(parameters.final_time)
        if calls == 1:
            raise ValueError("non-finite values")
        return original_simulate(document, parameters)

    monkeypatch.setattr(generation, "simulate_model", fail_first_smoke)
    llm = EarlyRepairLLM(replacements={"repair_1": valid_repair_payload()})
    document = await generate_model(request(), llm, max_repairs=1)
    assert document.validation.status == "passed"
    assert document.repair_attempts == 1
    assert calls == 2
    assert horizons == [100, 100]
    assert llm.calls[-1] == "repair_1"


def test_merge_normalizes_stock_topology_and_dynamic_constant():
    from pipeline.generation import _merge

    variables = _merge(
        [
            {
                "id": "members",
                "kind": "stock",
                "units": {"person": 1},
                "initial": 10,
                "derivative": "members * 2",
            },
            {
                "id": "recruitment",
                "kind": "flow",
                "units": {"person": 1, "week": -1},
                "source": {"kind": "cloud", "id": "recruitment_source"},
                "target": {"kind": "stock", "id": "members"},
            },
            {"id": "demand", "kind": "constant", "units": {"item": 1, "week": -1}},
        ],
        {
            "recruitment": "if_then_else(time >= 60, 5, 0)",
            "demand": "time",
        },
    )
    stock = next(item for item in variables if item.id == "members")
    demand = next(item for item in variables if item.id == "demand")
    recruitment = next(item for item in variables if item.id == "recruitment")
    assert stock.derivative is None
    assert demand.kind == "auxiliary"
    assert recruitment.expression.otherwise.op == "mul"


def test_explicit_dimensionless_units_are_normalized():
    _, variables = _variable_response(
        {
            "variables": [
                {
                    "id": "weight",
                    "kind": "constant",
                    "units": {"dimensionless": 1},
                    "initial": 0.1,
                }
            ]
        }
    )
    assert variables[0]["units"] == {}
