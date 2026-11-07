import asyncio
import copy
import json
from pathlib import Path

import pytest

from pipeline.exceptions import ModelValidationError
from pipeline.generation import _repair, generate_model
from pipeline.pattern_library import get_pattern, select_pattern
from pipeline.schemas import GenerationRequest
from pipeline.semantics import semantic_issues, with_semantic_validation

FIXTURE = Path(__file__).parent / "fixtures" / "llm_responses.json"


class RepairLLM:
    def __init__(self, *, successful: bool) -> None:
        self.responses = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.successful = successful
        self.calls = []

    async def chat_json(self, prompt, *, stage, system=None, temperature=0.3, response_schema=None):
        self.calls.append(stage)
        if stage == "repair_1":
            document = get_pattern("predator_prey").document
            variables = [item.model_dump(mode="json") for item in document.variables]
            if not self.successful:
                for item in variables:
                    if item["id"] == "predator_deaths":
                        item["source"] = {"kind": "cloud", "id": "deaths_source"}
            return {
                "name": "Repaired predator prey",
                "time": document.time.model_dump(mode="json"),
                "variables": variables,
                "tables": [],
                "assumptions": [],
            }
        if stage in {"variables", "equations"}:
            response = copy.deepcopy(self.responses[stage])
            if stage == "variables":
                for item in response["variables"]:
                    if item["id"] == "predator_deaths":
                        item["source"] = {"kind": "cloud", "id": "deaths_source"}
            return response
        return copy.deepcopy(self.responses[stage])

    async def close(self):
        return None


def test_pattern_selection_and_semantics():
    pattern = select_pattern("Модель хищник-жертва: кролики и лисы")
    assert pattern is not None and pattern.id == "predator_prey"
    document = with_semantic_validation(pattern.document)
    assert document.validation.status == "passed"
    assert not semantic_issues(document)


def test_invalid_death_flow_is_a_semantic_error():
    document = get_pattern("predator_prey").document
    variables = [item.model_dump() for item in document.variables]
    for item in variables:
        if item["id"] == "predator_deaths":
            item["source"] = {"kind": "cloud", "id": "deaths_source"}
    document = document.model_copy(update={"variables": variables})
    codes = {item.code for item in semantic_issues(document)}
    assert "INVALID_DEATH_FLOW" in codes


def test_negative_one_directional_outflow_is_rejected():
    from pipeline.expression_parser import parse_expression

    document = get_pattern("exponential_growth").document
    variables = [item.model_dump() for item in document.variables]
    for item in variables:
        if item["id"] == "births":
            item["id"] = "discharge_current"
            item["source"] = {"kind": "stock", "id": "population"}
            item["expression"] = parse_expression("-1 * population")
    candidate = document.model_copy(update={"variables": variables})
    assert "INVALID_NEGATIVE_OUTFLOW" in {item.code for item in semantic_issues(candidate)}
    for item in variables:
        if item["id"] == "discharge_current":
            item["expression"] = parse_expression("population * birth_rate")
    assert not semantic_issues(document.model_copy(update={"variables": variables}))


def test_steady_state_oracle_rejects_negative_stock():
    from types import SimpleNamespace

    from pipeline.benchmark import _expected_behavior

    result = SimpleNamespace(time=[0, 1], variables={"waiting_people": [-0.5, 1]})
    passed, metrics = _expected_behavior(
        {
            "expected_behavior": {
                "kind": "steady_state",
                "variable": "waiting_people",
                "value": 1,
                "tolerance": 0.1,
                "nonnegative": True,
            }
        },
        result,
    )
    assert not passed
    assert metrics["nonnegative"] is False


def test_bass_semantics_require_potential_adopters_and_word_of_mouth():
    from pipeline.expression_parser import parse_expression

    document = get_pattern("bass_diffusion").document.model_copy(
        update={"pattern_id": "bass_diffusion"}
    )
    assert not semantic_issues(document)
    for expression, expected in (
        ("adopters * imitation", "SEMANTIC_BASS_POTENTIAL_MISSING"),
        ("potential_adopters * innovation", "SEMANTIC_BASS_WORD_OF_MOUTH_MISSING"),
    ):
        variables = [item.model_dump() for item in document.variables]
        for item in variables:
            if item["id"] == "adoption":
                item["expression"] = parse_expression(expression)
        candidate = document.model_copy(update={"variables": variables})
        assert expected in {item.code for item in semantic_issues(candidate)}


async def test_bounded_repairs_invalid_generation():
    llm = RepairLLM(successful=True)
    document = await generate_model(
        GenerationRequest(description="Модель хищник-жертва: кролики и лисы"),
        llm,
        max_repairs=1,
    )
    assert document.validation.status == "passed"
    assert document.repair_attempts == 1
    assert document.pattern_id == "predator_prey"
    assert llm.calls == ["brief", "variables", "equations", "repair_1"]


async def test_repair_stops_after_limit():
    llm = RepairLLM(successful=False)
    with pytest.raises(ModelValidationError, match="INVALID_DEATH_FLOW") as exc_info:
        await generate_model(
            GenerationRequest(description="Модель хищник-жертва: кролики и лисы"),
            llm,
            max_repairs=1,
        )
    assert exc_info.value.repair_attempts == 1
    assert llm.calls.count("repair_1") == 1
    assert "repair_2" not in llm.calls


def test_nonstock_initial_is_normalized_to_expression():
    from pipeline.generation import _merge

    variables = _merge(
        [{"id": "rate", "kind": "constant", "initial": {"op": "lit", "value": 0.1}}],
        {},
    )
    assert variables[0].expression.op == "lit"
    assert variables[0].expression.value == 0.1


def test_repair_uses_normalized_constant_initial_values():
    document = get_pattern("predator_prey").document
    variables = [item.model_dump(mode="json") for item in document.variables]
    for item in variables:
        if item["kind"] == "constant":
            item["initial"] = item["expression"]["value"]
            item["expression"] = None
    repaired = _repair(
        document,
        {
            "name": document.name,
            "time": document.time.model_dump(mode="json"),
            "variables": variables,
            "tables": [],
            "assumptions": [],
        },
        1,
    )
    constant = next(item for item in repaired.variables if item.id == "prey_growth")
    assert constant.expression.value == 0.1


async def test_benchmark_offline():
    from pipeline.benchmark import run_benchmark
    from pipeline.llm import FixtureLLM

    result = await run_benchmark(
        FixtureLLM(FIXTURE),
        prompt_ids=["predator_prey_ru"],
        max_repairs=0,
    )
    assert result["cases"] == 1
    assert result["executable_rate"] == 1
    assert result["semantic_rate"] == 1
    assert result["behavior_rate"] == 1
    assert result["finite_rate"] == 1
    assert result["full_horizon_rate"] == 1
    assert result["results"][0]["repair_attempts"] == 0


async def test_benchmark_accepts_custom_prompt_file(tmp_path):
    from pipeline.benchmark import run_benchmark
    from pipeline.llm import FixtureLLM

    path = tmp_path / "prompts.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "custom_predator",
                    "description": "Модель хищник-жертва: кролики и лисы",
                    "expected_pattern": "predator_prey",
                }
            ]
        )
    )
    result = await run_benchmark(
        FixtureLLM(FIXTURE),
        prompts_path=path,
        artifacts_dir=tmp_path / "artifacts",
        max_repairs=0,
    )
    assert result["cases"] == 1
    assert result["results"][0]["prompt_id"] == "custom_predator"
    assert result["behavior_rate"] == 1
    assert result["max_repairs"] == 0
    assert len(result["corpus_sha256"]) == 64
    assert len(result["pipeline_sha256"]) == 64
    workdir = tmp_path / "artifacts" / "custom_predator-run-1"
    assert (workdir / "model.json").exists()
    assert (workdir / "simulation.json").exists()
    prompt = json.loads((workdir / "prompt.json").read_text())
    assert prompt["description"] == "Модель хищник-жертва: кролики и лисы"
    persisted_case = json.loads((workdir / "case.json").read_text())
    assert persisted_case["executable"] is True
    assert persisted_case["behavior_pass"] is True
    assert persisted_case["duration_seconds"] >= 0
    stale = workdir / "variables_repair_3.json"
    stale.write_text("{}")
    unrelated = workdir / "keep.txt"
    unrelated.write_text("keep")
    await run_benchmark(
        FixtureLLM(FIXTURE),
        prompts_path=path,
        artifacts_dir=tmp_path / "artifacts",
        max_repairs=0,
    )
    assert not stale.exists()
    assert unrelated.read_text() == "keep"


async def test_benchmark_persists_failed_case_result(tmp_path):
    from pipeline.benchmark import run_benchmark
    from pipeline.llm import FixtureLLM

    prompts = tmp_path / "prompts.json"
    prompts.write_text(
        json.dumps(
            [
                {
                    "id": "failed_case",
                    "description": "A model that cannot be generated",
                    "expected_pattern": "exponential_growth",
                }
            ]
        )
    )
    fixture = tmp_path / "empty_fixture.json"
    fixture.write_text("{}")
    artifacts = tmp_path / "artifacts"
    result = await run_benchmark(
        FixtureLLM(fixture),
        prompts_path=prompts,
        artifacts_dir=artifacts,
        max_repairs=0,
    )
    case = json.loads((artifacts / "failed_case-run-1" / "case.json").read_text())
    assert result["executable_rate"] == 0
    assert case["executable"] is False
    assert "has no response for stage brief" in case["error"]
    assert case["duration_seconds"] >= 0


async def test_benchmark_concurrency_preserves_result_order(tmp_path):
    from pipeline.benchmark import run_benchmark
    from pipeline.llm import FixtureLLM

    class DelayedFixture(FixtureLLM):
        active = 0
        maximum_active = 0

        async def chat_json(self, *args, **kwargs):
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
            try:
                await asyncio.sleep(0.01)
                return await super().chat_json(*args, **kwargs)
            finally:
                self.active -= 1

    prompts = [
        {
            "id": name,
            "description": "Модель хищник-жертва: кролики и лисы",
            "expected_pattern": "predator_prey",
        }
        for name in ("first", "second")
    ]
    path = tmp_path / "prompts.json"
    path.write_text(json.dumps(prompts))
    llm = DelayedFixture(FIXTURE)
    result = await run_benchmark(llm, prompts_path=path, concurrency=2, max_repairs=0)
    assert llm.maximum_active == 2
    assert result["concurrency"] == 2
    assert [case["prompt_id"] for case in result["results"]] == ["first", "second"]


def test_custom_behavior_oracles_check_numeric_properties():
    from types import SimpleNamespace

    from pipeline.benchmark import _expected_behavior, _requires_dynamic

    result = SimpleNamespace(
        time=[0, 1, 2, 3, 4],
        variables={
            "decay": [5, 4, 3, 2, 1.8393972058572117],
            "growth": [0, 1, 2, 3, 4],
            "cascade": [0, 0, 5, 3, 1],
            "delayed": [0, 0, 0, 8, 10],
            "event": [0, 4, 8, 4, 2],
            "sign": [1, -1, 1, -1, 1],
            "stable": [3, 3, 3, 3, 3],
            "left": [1, 1, 1, 1, 1],
            "right": [2, 2, 2, 2, 2],
        },
    )
    expectations = [
        {"kind": "analytic_exponential", "variable": "decay", "initial": 5, "rate": -0.2, "time": 5, "tolerance": 0.001},
        {"kind": "monotonic", "variable": "growth", "direction": "increasing"},
        {"kind": "sign_changes", "variable": "sign", "minimum": 2},
        {"kind": "cascade", "variable": "cascade", "after": 1},
        {"kind": "delayed_response", "variable": "delayed", "at": 2, "before_max": 0, "after_min": 5},
        {"kind": "event_change", "variable": "event", "at": 2, "after": 4, "relation": "decrease"},
        {"kind": "steady_state", "variable": "stable", "value": 3, "tolerance": 1e-9},
        {"kind": "range", "variable": "growth", "min": 0, "max": 5},
        {"kind": "conservation", "variables": ["left", "right"], "tolerance": 1e-9},
    ]
    for expected in expectations:
        passed, metrics = _expected_behavior({"expected_behavior": expected}, result)
        assert passed, (expected, metrics)
    assert not _requires_dynamic({"expected_behavior": expectations[6]})
    assert _requires_dynamic({"expected_behavior": expectations[1]})


def test_behavior_oracle_uses_explicit_variable_alias():
    from types import SimpleNamespace

    from pipeline.benchmark import _expected_behavior

    result = SimpleNamespace(time=[0, 1], variables={"capacitor_charge": [5, 4]})
    passed, metrics = _expected_behavior(
        {
            "expected_behavior": {
                "kind": "monotonic",
                "variable": "charge",
                "aliases": ["capacitor_charge"],
                "direction": "decreasing",
            }
        },
        result,
    )
    assert passed
    assert metrics["resolved_variable"] == "capacitor_charge"


def test_behavior_oracle_can_resolve_the_only_stock():
    from types import SimpleNamespace

    from pipeline.benchmark import _expected_behavior

    result = SimpleNamespace(time=[0, 1], variables={"packet_backlog": [10, 0]})
    passed, metrics = _expected_behavior(
        {
            "expected_behavior": {
                "kind": "steady_state",
                "variable": "packets",
                "value": 0,
                "tolerance": 0.01,
            }
        },
        result,
        {"packet_backlog"},
    )
    assert passed
    assert metrics["resolved_variable"] == "packet_backlog"


def test_behavior_oracle_uses_only_unique_stock_name_matches():
    from types import SimpleNamespace

    from pipeline.benchmark import _expected_behavior

    result = SimpleNamespace(
        time=[0, 1],
        variables={"hot_reservoir": [80, 70], "warm_reservoir": [20, 30]},
    )
    stocks = {"hot_reservoir", "warm_reservoir"}
    passed, metrics = _expected_behavior(
        {"expected_behavior": {"kind": "monotonic", "variable": "warm"}},
        result,
        stocks,
    )
    assert passed
    assert metrics["resolved_variable"] == "warm_reservoir"
    passed, _ = _expected_behavior(
        {"expected_behavior": {"kind": "monotonic", "variable": "reservoir"}},
        result,
        stocks,
    )
    assert not passed


def test_behavior_oracle_resolves_unique_embedded_stock_token():
    from types import SimpleNamespace

    from pipeline.benchmark import _expected_behavior

    result = SimpleNamespace(
        time=[0, 1, 2],
        variables={
            "energy_in_hot_reservoir": [80, 70, 60],
            "energy_in_warm_reservoir": [20, 30, 25],
        },
    )
    stocks = {"energy_in_hot_reservoir", "energy_in_warm_reservoir"}
    passed, metrics = _expected_behavior(
        {"expected_behavior": {"kind": "cascade", "variable": "warm", "after": 1}},
        result,
        stocks,
    )
    assert passed
    assert metrics["resolved_variable"] == "energy_in_warm_reservoir"
    passed, _ = _expected_behavior(
        {"expected_behavior": {"kind": "cascade", "variable": "reservoir"}},
        result,
        stocks,
    )
    assert not passed


def test_behavior_oracle_resolves_unique_case_insensitive_plural():
    from types import SimpleNamespace

    from pipeline.benchmark import _expected_behavior

    result = SimpleNamespace(
        time=[0, 1, 2], variables={"Novices": [70, 60, 50], "Mentors": [0, 20, 25]}
    )
    passed, metrics = _expected_behavior(
        {"expected_behavior": {"kind": "cascade", "variable": "mentor", "after": 1}},
        result,
        {"Novices", "Mentors"},
    )
    assert passed
    assert metrics["resolved_variable"] == "Mentors"


def test_behavior_oracle_supports_simple_plural_stock_name():
    from types import SimpleNamespace

    from pipeline.benchmark import _expected_behavior

    result = SimpleNamespace(
        time=[0, 1, 2], variables={"apprentices": [100, 80, 60], "masters": [0, 20, 30]}
    )
    passed, metrics = _expected_behavior(
        {"expected_behavior": {"kind": "cascade", "variable": "master", "after": 1}},
        result,
        {"apprentices", "masters"},
    )
    assert passed
    assert metrics["resolved_variable"] == "masters"


async def test_steady_state_benchmark_does_not_require_dynamic(tmp_path):
    from pipeline.benchmark import run_benchmark

    class ZeroLLM:
        async def chat_json(self, prompt, *, stage, system=None, temperature=0.3, response_schema=None):
            if stage == "brief":
                return {
                    "goal": "Remain at zero equilibrium",
                    "boundaries": ["Zero state"],
                    "time_horizon": "1 year",
                    "time_unit": "year",
                    "aggregation": "medium",
                    "stocks": ["level"],
                    "flows": ["change"],
                    "exogenous_inputs": ["rate"],
                    "expected_feedback_loops": [],
                }
            if stage == "components":
                return {"components": [], "time": None, "assumptions": []}
            if stage == "variables":
                return {
                    "name": "Zero equilibrium",
                    "time": {"unit": "year", "initial_time": 0, "final_time": 1, "time_step": 0.25, "saveper": 0.25},
                    "variables": [
                        {"id": "level", "kind": "stock", "units": {"unit": 1}, "initial": 0},
                        {"id": "change", "kind": "flow", "units": {"unit": 1, "year": -1}, "source": {"kind": "cloud", "id": "source"}, "target": {"kind": "stock", "id": "level"}},
                        {"id": "rate", "kind": "constant", "units": {"year": -1}, "initial": 0},
                    ],
                    "tables": [],
                    "assumptions": [],
                }
            if stage == "equations":
                return {"expressions": [{"id": "change", "expression": "level * rate"}, {"id": "rate", "expression": 0}]}
            raise AssertionError(stage)

    prompts = tmp_path / "prompts.json"
    prompts.write_text(json.dumps([{
        "id": "zero_equilibrium",
        "description": "A system at exact zero equilibrium",
        "expected_pattern": None,
        "expected_behavior": {"kind": "steady_state", "variable": "level", "value": 0, "tolerance": 1e-9},
    }]))
    result = await run_benchmark(ZeroLLM(), prompts_path=prompts, max_repairs=0)
    assert result["dynamic_rate"] == 0
    assert result["semantic_rate"] == 1
    assert result["behavior_rate"] == 1


async def test_benchmark_expected_errors_have_a_separate_outcome_metric(tmp_path):
    from pipeline.benchmark import run_benchmark
    from pipeline.llm import FixtureLLM

    prompts = tmp_path / "prompts.json"
    prompts.write_text(json.dumps([
        {
            "id": "expected_rejection",
            "description": "Reject this invalid request",
            "expected_pattern": None,
            "assumption_policy": "require_explicit",
            "expected_error": "no response",
        },
        {
            "id": "unexpected_model",
            "description": "A rejection with another error is not enough",
            "expected_pattern": None,
            "expected_error": "MISSING_PARAMETER",
        },
    ]))
    fixture = tmp_path / "empty.json"
    fixture.write_text("{}")
    result = await run_benchmark(FixtureLLM(fixture), prompts_path=prompts, max_repairs=0)
    assert result["expected_error_cases"] == 2
    assert result["outcome_rate"] == 0.5
    assert [case["outcome_pass"] for case in result["results"]] == [True, False]
    assert result["executable_rate"] == 0
