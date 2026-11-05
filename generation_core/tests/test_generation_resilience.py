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


async def test_ode_guidance_is_used_only_without_pattern():
    class PromptCaptureLLM(EarlyRepairLLM):
        def __init__(self):
            super().__init__()
            self.prompts = {}

        async def chat_json(self, prompt, *, stage, system=None, temperature=0.3, response_schema=None):
            self.prompts[stage] = prompt
            return await super().chat_json(
                prompt,
                stage=stage,
                system=system,
                temperature=temperature,
                response_schema=response_schema,
            )

    llm = PromptCaptureLLM()
    await generate_model(
        GenerationRequest(description="Custom second-order dynamic system"),
        llm,
        max_repairs=0,
    )
    assert "Для математических ODE" in llm.prompts["variables"]
    assert "nonnegative flow policy" in llm.prompts["variables"]
    llm = PromptCaptureLLM()
    await generate_model(request(), llm, max_repairs=0)
    assert "stock.derivative" not in llm.prompts["variables"]


async def test_brief_schema_excludes_unused_component_definitions():
    from pipeline.llm import strict_json_schema

    llm = EarlyRepairLLM()
    await generate_model(request(), llm, max_repairs=0)
    schema = strict_json_schema(llm.schemas["brief"])
    assert "$defs" not in schema
    assert set(schema["required"]) == set(schema["properties"])
    assert not {"components", "time", "assumptions"} & set(schema["properties"])


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


async def test_brief_repair_requires_a_complete_object_not_an_array():
    class PromptLLM(EarlyRepairLLM):
        def __init__(self):
            super().__init__(
                failures={"brief": LLMResponseError("array instead of object", response_text="[]")}
            )
            self.prompts = {}

        async def chat_json(self, prompt, *, stage, system=None, temperature=0.3, response_schema=None):
            self.prompts[stage] = prompt
            return await super().chat_json(
                prompt,
                stage=stage,
                system=system,
                temperature=temperature,
                response_schema=response_schema,
            )

    llm = PromptLLM()
    await generate_model(request(), llm, max_repairs=1)
    assert "НЕ массив" in llm.prompts["brief_repair_1"]
    assert '"stocks"' in llm.prompts["brief_repair_1"]


async def test_second_brief_repair_drops_the_malformed_response_anchor():
    class RepeatedBriefLLM(EarlyRepairLLM):
        def __init__(self):
            super().__init__()
            self.prompts = {}

        async def chat_json(self, prompt, *, stage, system=None, temperature=0.3, response_schema=None):
            self.prompts[stage] = prompt
            if stage in {"brief", "brief_repair_1"}:
                return ["ONLY_BAD_ARRAY"]
            return await super().chat_json(
                prompt,
                stage=stage,
                system=system,
                temperature=temperature,
                response_schema=response_schema,
            )

    llm = RepeatedBriefLLM()
    document = await generate_model(request(), llm, max_repairs=2)
    assert document.repair_attempts == 2
    assert list(llm.prompts) == ["brief", "brief_repair_1", "brief_repair_2", "variables", "equations"]
    previous_response = llm.prompts["brief_repair_2"].split("Прежний ответ:\n", 1)[1]
    assert "ONLY_BAD_ARRAY" not in previous_response


async def test_stage_artifacts_include_successful_response_before_parsing(tmp_path):
    llm = EarlyRepairLLM(
        failures={
            "brief": LLMResponseError("failed to parse LLM JSON", response_text="{broken")
        }
    )
    await generate_model(request(), llm, workdir=tmp_path, max_repairs=1)
    assert not (tmp_path / "brief_response.json").exists()
    repaired = json.loads((tmp_path / "brief_repair_1_response.json").read_text())
    assert repaired["stocks"]


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
    with pytest.raises(ModelValidationError, match="undeclared variable ids"):
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
    assert {"type": "null"} not in constant_schema["properties"]["initial"]["anyOf"]
    assert llm.schemas["equations"]["required"] == ["expressions"]


def test_extracted_constant_value_wins_over_equation_self_reference():
    from pipeline.generation import _merge

    _, raw = _variable_response(
        {"variables": [{"id": "rate", "kind": "constant", "initial": 0.1}]}
    )
    variables = _merge(raw, {"rate": "rate"})
    assert variables[0].expression.value == 0.1


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


def test_empty_assumption_value_uses_explicit_variable_initial():
    metadata, _ = _variable_response(
        {
            "time": {
                "unit": "week",
                "initial_time": 0,
                "final_time": 10,
                "time_step": 0.25,
                "saveper": 0.5,
            },
            "variables": [{"id": "rate", "kind": "constant", "initial": 0.05}],
            "assumptions": [
                {
                    "path": "variables.rate.initial",
                    "value": "",
                    "source": "llm_inferred",
                    "rationale": "Illustrative rate",
                    "requires_confirmation": True,
                },
                {
                    "path": "time.time_step",
                    "value": "",
                    "source": "llm_inferred",
                    "rationale": "Illustrative time step",
                    "requires_confirmation": False,
                },
            ],
        }
    )
    assert metadata["assumptions"][0]["value"] == "0.05"
    assert metadata["assumptions"][1]["value"] == "0.25"


def test_empty_assumption_value_accepts_unambiguous_variable_shorthand():
    metadata, _ = _variable_response(
        {
            "variables": [{"id": "rate", "kind": "constant", "initial": 0.05}],
            "assumptions": [
                {
                    "path": "rate",
                    "value": "",
                    "source": "llm_inferred",
                    "rationale": "Illustrative rate",
                    "requires_confirmation": True,
                },
                {
                    "path": "rate.initial",
                    "value": "",
                    "source": "llm_inferred",
                    "rationale": "Illustrative rate",
                    "requires_confirmation": True,
                },
            ],
        }
    )
    assert [item["value"] for item in metadata["assumptions"]] == ["0.05", "0.05"]
    assert [item["path"] for item in metadata["assumptions"]] == [
        "variables.rate",
        "variables.rate.initial",
    ]


def test_bass_rejects_unrequested_monetary_budget_but_allows_explicit_budget():
    from pipeline.generation import _validate_variable_scope
    from pipeline.pattern_library import get_pattern

    pattern = get_pattern("bass_diffusion")
    variables = [
        {
            "id": "advertising_budget",
            "kind": "constant",
            "units": {"dollar": 1},
            "initial": 100,
        }
    ]
    with pytest.raises(ModelValidationError, match="unrequested monetary advertising budget"):
        _validate_variable_scope(variables, pattern, "App adoption through paid advertising")
    _validate_variable_scope(variables, pattern, "Adoption with a budget of 100 dollars")


def test_normalized_oscillators_reject_unrequested_physical_units():
    from pipeline.generation import _validate_variable_scope
    from pipeline.pattern_library import get_pattern

    pattern = get_pattern("van_der_pol_oscillator")
    valid = [item.model_dump(mode="json") for item in pattern.document.variables]
    description = "Electronic Van der Pol oscillator with a relaxation limit cycle"
    _validate_variable_scope(valid, pattern, description, pattern.document.time.unit)
    invalid = [
        {"id": "capacitor_charge", "kind": "stock", "units": {"coulomb": 1}, "initial": 0}
    ]
    with pytest.raises(ModelValidationError, match="normalized pattern ids"):
        _validate_variable_scope(invalid, pattern, description, pattern.document.time.unit)
    with pytest.raises(ModelValidationError, match="time.unit='second'"):
        _validate_variable_scope(valid, pattern, description, "second")
    _validate_variable_scope(
        invalid,
        pattern,
        "Van der Pol circuit with capacitance 1 farad",
        "second",
    )


async def test_normalized_pattern_uses_validated_equations_without_llm_stage():
    from pipeline.generation import _validate_brief_scope
    from pipeline.pattern_library import get_pattern
    from pipeline.schemas import ModelBrief

    pattern = get_pattern("van_der_pol_oscillator")
    description = "Electronic Van der Pol oscillator with a relaxation limit cycle"
    brief = ModelBrief(
        goal="Model a relaxation oscillator",
        boundaries=["Normalized circuit dynamics"],
        time_horizon="60 time units",
        time_unit="time",
        aggregation="medium",
        stocks=["position", "velocity"],
        flows=["d_position", "d_velocity"],
        exogenous_inputs=["mu", "acceleration_scale"],
        expected_feedback_loops=["nonlinear damping"],
    )
    with pytest.raises(ModelValidationError, match="normalized ModelBrief"):
        _validate_brief_scope(
            brief.model_copy(update={"stocks": ["capacitor_charge"]}),
            pattern,
            description,
        )
    with pytest.raises(ModelValidationError, match="normalized ModelBrief"):
        _validate_brief_scope(
            brief.model_copy(update={"exogenous_inputs": ["capacitance"]}),
            pattern,
            description,
        )
    _validate_brief_scope(
        brief.model_copy(update={"exogenous_inputs": ["mu"]}), pattern, description
    )
    variables = []
    for item in pattern.document.variables:
        payload = item.model_dump(mode="json")
        if item.kind == "constant":
            payload["initial"] = payload["expression"]
        if item.kind != "stock":
            payload["expression"] = None
        variables.append(payload)
    llm = EarlyRepairLLM(
        replacements={
            "brief": brief.model_dump(mode="json"),
            "variables": {
                "name": "Normalized Van der Pol",
                "time": pattern.document.time.model_dump(mode="json"),
                "variables": variables,
                "tables": [],
                "assumptions": [],
            },
        }
    )
    document = await generate_model(
        GenerationRequest(description=description), llm, max_repairs=0
    )
    assert llm.calls == ["brief", "variables"]
    assert document.repair_attempts == 0
    assert document.pattern_id == pattern.id
    assert [item.expression for item in document.variables if item.kind != "stock"] == [
        item.expression for item in pattern.document.variables if item.kind != "stock"
    ]
    assert document.assumptions[-1].source == "archetype"
    assert document.assumptions[-1].path == "equations"


async def test_canonical_pattern_edit_uses_llm_and_preserves_other_variables():
    from pipeline.pattern_library import get_pattern
    from pipeline.schemas import ModelBrief

    pattern = get_pattern("van_der_pol_oscillator")
    brief = ModelBrief(
        goal="Tune normalized damping",
        boundaries=["Normalized circuit dynamics"],
        time_horizon="60 time units",
        time_unit="time",
        aggregation="medium",
        stocks=["position", "velocity"],
        flows=["d_position", "d_velocity"],
        exogenous_inputs=["mu"],
        expected_feedback_loops=["nonlinear damping"],
    )
    variables = []
    expressions = []
    for item in pattern.document.variables:
        payload = item.model_dump(mode="json")
        if item.id == "mu":
            payload["initial"] = 5
            payload["expression"] = 5
        if item.kind != "stock":
            expressions.append({"id": item.id, "expression": payload["expression"]})
        variables.append(payload)
    llm = EarlyRepairLLM(
        replacements={
            "brief": brief.model_dump(mode="json"),
            "variables": {
                "name": pattern.document.name,
                "time": pattern.document.time.model_dump(mode="json"),
                "variables": variables,
                "tables": [],
                "assumptions": [],
            },
            "equations": {"expressions": expressions},
        }
    )
    document = await generate_model(
        GenerationRequest(description="Set mu to 5", base_model=pattern.document),
        llm,
        max_repairs=0,
    )
    assert llm.calls == ["brief", "variables", "equations"]
    assert document.pattern_id == pattern.id
    mu = next(item for item in document.variables if item.id == "mu")
    assert mu.expression.value == 5
    for item in document.variables:
        if item.id != "mu":
            original = next(value for value in pattern.document.variables if value.id == item.id)
            assert item.model_dump() == original.model_dump()


def test_bass_brief_rejects_unrequested_monetary_inputs():
    from pipeline.generation import _validate_brief_scope
    from pipeline.pattern_library import get_pattern
    from pipeline.schemas import ModelBrief

    brief = ModelBrief(
        goal="Model app adoption",
        boundaries=["App market"],
        time_horizon="100 years",
        time_unit="year",
        aggregation="medium",
        stocks=["potential_adopters", "adopters"],
        flows=["adoption"],
        exogenous_inputs=["advertising_budget"],
        expected_feedback_loops=["word of mouth"],
    )
    pattern = get_pattern("bass_diffusion")
    with pytest.raises(ModelValidationError, match="Bass ModelBrief.*advertising_budget"):
        _validate_brief_scope(brief, pattern, "App adoption through advertising")
    _validate_brief_scope(brief, pattern, "Adoption with a budget in dollars")


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


def test_repair_preserves_structure_when_all_kinds_are_corrupted():
    from pipeline.generation import _repair
    from pipeline.pattern_library import get_pattern

    original = _repair(get_pattern("predator_prey").document, valid_repair_payload(), 0)
    payload = valid_repair_payload()
    for item in payload["variables"]:
        item["kind"] = "flow"
        item["initial"] = None
        item["expression"] = None
    repaired = _repair(original, payload, 1, preserve_topology=True)
    assert repaired.model_hash() == original.model_hash()


def test_topology_repair_can_restore_constant_misclassified_as_stock():
    from pipeline.generation import _repair, _validated
    from pipeline.pattern_library import get_pattern
    from pipeline.schemas import FlowEndpoint, StockVariable

    document = get_pattern("exponential_growth").document
    variables = []
    for item in document.variables:
        if item.id == "birth_rate":
            item = StockVariable(
                id=item.id,
                kind="stock",
                initial=item.expression,
                units=item.units,
            )
        elif item.id == "births":
            item = item.model_copy(
                update={"source": FlowEndpoint(kind="stock", id="birth_rate")}
            )
        variables.append(item)
    original = document.model_copy(update={"variables": variables})
    payload = valid_repair_payload()
    payload["variables"] = [
        item.model_dump(mode="json") for item in document.variables
    ]
    repaired = _repair(
        original,
        payload,
        1,
        preserve_topology=False,
        preserve_kinds=False,
    )
    rate = next(item for item in repaired.variables if item.id == "birth_rate")
    assert rate.kind == "constant"
    assert not _validated(repaired)[1]


def test_repair_does_not_drop_missing_existing_variables():
    from pipeline.generation import _repair
    from pipeline.pattern_library import get_pattern

    original = get_pattern("predator_prey").document
    payload = valid_repair_payload()
    payload["variables"] = payload["variables"][1:]
    repaired = _repair(original, payload, 1)
    prey = next(item for item in repaired.variables if item.id == "prey")
    assert prey.kind == "stock"
    assert prey.initial.value == 100


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


def test_merge_preserves_derivative_for_consistency_validation():
    from pipeline.generation import _merge, _validated
    from pipeline.schemas import ModelDocument, TimeSettings

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
        time_unit="week",
    )
    stock = next(item for item in variables if item.id == "members")
    demand = next(item for item in variables if item.id == "demand")
    recruitment = next(item for item in variables if item.id == "recruitment")
    assert stock.derivative is not None
    assert demand.kind == "auxiliary"
    assert recruitment.expression.otherwise.op == "mul"
    _, errors = _validated(
        ModelDocument(
            name="Mismatched derivative",
            description="Derivative must agree with topology",
            time=TimeSettings(unit="week"),
            variables=variables,
        )
    )
    assert "DERIVATIVE_TOPOLOGY_MISMATCH" in {item.code for item in errors}


def test_isolated_stock_derivative_becomes_equivalent_net_flow():
    from pipeline.generation import _merge, _validated
    from pipeline.schemas import ModelDocument, TimeSettings

    variables = _merge(
        [
            {
                "id": "charge",
                "kind": "stock",
                "units": {"coulomb": 1},
                "initial": 5,
                "derivative": "-charge / rc_time",
            },
            {"id": "rc_time", "kind": "constant", "units": {"second": 1}},
        ],
        {"rc_time": 5},
        time_unit="second",
    )
    document, errors = _validated(
        ModelDocument(
            name="Derivative net flow",
            description="Equivalent derivative representation",
            time=TimeSettings(unit="second", final_time=1, time_step=0.1, saveper=0.1),
            variables=variables,
        )
    )
    assert not errors
    stock = next(item for item in document.variables if item.id == "charge")
    flow = next(item for item in document.variables if item.id == "charge_net_rate")
    assert stock.derivative.name == flow.id
    assert flow.units == {"coulomb": 1, "second": -1}
    assert flow.topology_status == "inferred"
    assert flow.source.kind == "cloud"
    assert flow.target.id == "charge"


def test_cloud_endpoint_with_declared_stock_is_reused():
    _, variables = _variable_response(
        {
            "variables": [
                {"id": "lower", "kind": "stock", "units": {"litre": 1}, "initial": 0},
                {"id": "environment", "kind": "stock", "units": {"litre": 1}, "initial": 0},
                {
                    "id": "outflow",
                    "kind": "flow",
                    "units": {"litre": 1, "minute": -1},
                    "source": {"kind": "stock", "id": "lower"},
                    "target": {"kind": "cloud", "id": "environment"},
                },
            ]
        }
    )
    flow = next(item for item in variables if item["id"] == "outflow")
    assert flow["target"] == {"kind": "stock", "id": "environment"}


def test_cloud_id_collision_with_nonstock_is_namespaced():
    _, variables = _variable_response(
        {
            "variables": [
                {"id": "lower", "kind": "stock", "units": {"litre": 1}, "initial": 0},
                {"id": "environment", "kind": "constant", "units": {"litre": 1}, "initial": 0},
                {
                    "id": "outflow",
                    "kind": "flow",
                    "units": {"litre": 1, "minute": -1},
                    "source": {"kind": "stock", "id": "lower"},
                    "target": {"kind": "cloud", "id": "environment"},
                },
            ]
        }
    )
    flow = next(item for item in variables if item["id"] == "outflow")
    assert flow["target"] == {"kind": "cloud", "id": "outflow_environment"}


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


def test_reserved_time_is_ignored_and_null_equation_uses_existing_expression():
    from pipeline.generation import _merge

    variables = _merge(
        [
            {
                "id": "rate",
                "kind": "constant",
                "units": {"year": -1},
                "expression": {"op": "lit", "value": 0.1},
            }
        ],
        {"time": "time", "rate": None},
    )
    assert variables[0].expression.value == 0.1


def test_repair_context_is_smaller_than_full_document_payload():
    from pipeline.generation import _repair_context, _repair_payload
    from pipeline.pattern_library import get_pattern

    document = get_pattern("student_club").document
    full = json.dumps(_repair_payload(document))
    compact = _repair_context(document)
    assert len(json.dumps(compact)) < len(full)
    assert "label" not in compact["variables"][0]
    assert "description" not in compact["variables"][0]
    assert "units" in compact["variables"][0]


def test_reserved_builtin_variables_are_not_declared():
    _, variables = _variable_response(
        {
            "variables": [
                {"id": "time", "kind": "stock", "initial": 0},
                {"id": "rate", "kind": "constant", "initial": 0.1},
            ]
        }
    )
    assert [item["id"] for item in variables] == ["rate"]


def test_equations_reject_unknown_ids_but_ignore_stock_expressions():
    from pipeline.generation import _merge

    with pytest.raises(ModelValidationError, match="undeclared variable ids"):
        _merge(
            [{"id": "rate", "kind": "constant", "units": {"year": -1}}],
            {"rate": 0.1, "replenishment_rate": 0.2},
        )
    variables = _merge(
        [{"id": "members", "kind": "stock", "initial": 10}],
        {"members": "members * 2"},
    )
    assert variables[0].initial.value == 10


def test_static_supply_delay_is_rejected_by_smoke():
    from pipeline.expression_parser import parse_expression
    from pipeline.generation import _smoke
    from pipeline.pattern_library import get_pattern

    document = get_pattern("supply_delay").document
    variables = []
    for item in document.variables:
        if item.id == "order_rate":
            item = item.model_copy(update={"expression": parse_expression("100")})
        variables.append(item)
    document = document.model_copy(update={"variables": variables, "pattern_id": "supply_delay"})
    with pytest.raises(ModelValidationError, match="supply-delay model is static"):
        _smoke(document)


def test_invalid_time_settings_use_archetype_defaults():
    from pipeline.schemas import TimeSettings

    metadata, _ = _variable_response(
        {
            "time": {
                "unit": "week",
                "initial_time": 0,
                "final_time": 100,
                "time_step": 0,
                "saveper": 0,
            },
            "variables": [{"id": "rate", "kind": "constant", "initial": 0.1}],
        },
        default_time=TimeSettings(
            unit="week",
            final_time=104,
            time_step=0.01,
            saveper=0.05,
        ),
    )
    assert metadata["time"]["time_step"] == 0.01
    assert metadata["time"]["saveper"] == 0.05
    assert metadata["time"]["final_time"] == 100


def test_stock_kind_is_inferred_from_flow_endpoints():
    _, variables = _variable_response(
        {
            "variables": [
                {"id": "savings", "kind": "constant", "initial": 1000},
                {
                    "id": "interest_income",
                    "kind": "flow",
                    "source": {"kind": "cloud", "id": "interest_source"},
                    "target": {"kind": "stock", "id": "savings"},
                },
            ]
        }
    )
    savings = next(item for item in variables if item["id"] == "savings")
    assert savings["kind"] == "stock"
    assert savings["initial"]["value"] == 1000


def test_unknown_stock_endpoint_is_repaired_on_variables_stage():
    with pytest.raises(ModelValidationError, match="interest_income_source.*kind='cloud'"):
        _variable_response(
            {
                "variables": [
                    {"id": "savings", "kind": "stock", "initial": 1000},
                    {
                        "id": "interest_income",
                        "kind": "flow",
                        "source": {"kind": "stock", "id": "interest_income_source"},
                        "target": {"kind": "stock", "id": "savings"},
                    },
                ]
            }
        )


def test_final_repair_uses_normalized_time_settings():
    from pipeline.generation import _repair
    from pipeline.pattern_library import get_pattern

    document = get_pattern("predator_prey").document
    payload = valid_repair_payload()
    payload["time"]["time_step"] = 0
    payload["time"]["saveper"] = 0
    repaired = _repair(document, payload, 1)
    assert repaired.time.time_step == document.time.time_step
    assert repaired.time.saveper == document.time.saveper
