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
    with pytest.raises(ModelValidationError, match="INVALID_DEATH_FLOW"):
        await generate_model(
            GenerationRequest(description="Модель хищник-жертва: кролики и лисы"),
            llm,
            max_repairs=1,
        )
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
