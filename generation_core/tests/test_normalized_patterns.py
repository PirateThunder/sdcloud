import pytest

from pipeline.generation import _requires_normalized_pattern, generate_model
from pipeline.ir import walk
from pipeline.pattern_library import get_pattern
from pipeline.schemas import GenerationRequest


class NormalizedPatternLLM:
    def __init__(self, pattern_id, *, time_unit=None, flow_suffix=False, initial_overrides=None):
        self.pattern = get_pattern(pattern_id)
        self.time_unit = time_unit
        self.flow_suffix = flow_suffix
        self.initial_overrides = initial_overrides or {}
        self.calls = []

    async def chat_json(self, prompt, *, stage, system=None, temperature=0.3, response_schema=None):
        self.calls.append(stage)
        pattern = self.pattern.document
        if stage == "brief":
            return {
                "goal": pattern.name,
                "time_horizon": str(pattern.time.final_time),
                "time_unit": pattern.time.unit,
                "stocks": [item.id for item in pattern.variables if item.kind == "stock"],
                "flows": [item.id for item in pattern.variables if item.kind == "flow"],
                "exogenous_inputs": [
                    item.id for item in pattern.variables if item.kind == "constant"
                ],
            }
        if stage == "variables":
            variables = []
            for variable in pattern.variables:
                if variable.kind == "auxiliary":
                    continue
                payload = variable.model_dump(mode="json")
                if variable.kind == "stock":
                    payload["derivative"] = None
                elif variable.kind in {"flow", "auxiliary", "constant"}:
                    payload["expression"] = None
                if variable.id in self.initial_overrides:
                    payload["initial"] = self.initial_overrides[variable.id]
                if self.flow_suffix and variable.kind == "flow":
                    payload["id"] = f"{variable.id}_flow"
                variables.append(payload)
            return {
                "name": pattern.name,
                "time": {
                    **pattern.time.model_dump(mode="json"),
                    "unit": self.time_unit or pattern.time.unit,
                },
                "variables": variables,
                "tables": [],
                "assumptions": [],
            }
        raise AssertionError(f"Unexpected LLM stage: {stage}")

    async def close(self):
        return None


@pytest.mark.parametrize(
    ("pattern_id", "description", "time_unit", "flow_suffix", "overrides"),
    [
        (
            "lorenz_system",
            "Lorenz system with three coupled stocks and a chaotic butterfly attractor, sigma=11.",
            "dimensionless",
            False,
            {"sigma": 11},
        ),
        (
            "sirs_epidemic",
            "SIRS epidemic with seasonal contact rates, waning immunity and initial_infectious=10 person.",
            "day",
            True,
            {"initial_infectious": 10},
        ),
        (
            "student_club",
            "Students create an English speaking club with club_capacity=90 person, burnout and a recruitment campaign after week 60.",
            "week",
            False,
            {"club_capacity": 90},
        ),
    ],
)
async def test_normalized_patterns_complete_canonical_topology(
    pattern_id, description, time_unit, flow_suffix, overrides
):
    llm = NormalizedPatternLLM(
        pattern_id,
        time_unit=time_unit,
        flow_suffix=flow_suffix,
        initial_overrides=overrides,
    )
    document = await generate_model(
        GenerationRequest(description=description),
        llm,
        max_repairs=0,
    )
    assert llm.calls == ["brief", "variables"]
    assert document.validation.status == "passed"
    assert document.pattern_id == pattern_id
    assert document.time.unit == get_pattern(pattern_id).document.time.unit
    for variable_id, value in overrides.items():
        variable = next(item for item in document.variables if item.id == variable_id)
        assert variable.expression.value == value
    expected_auxiliaries = {
        item.id for item in get_pattern(pattern_id).document.variables if item.kind == "auxiliary"
    }
    assert expected_auxiliaries <= {item.id for item in document.variables}
    if pattern_id == "sirs_epidemic":
        contact_rate = next(item for item in document.variables if item.id == "contact_rate")
        assert contact_rate.kind == "auxiliary"
        assert any(node.op == "time" for node in walk(contact_rate.expression))


def test_normalized_pattern_rejects_conflicting_explicit_time_unit():
    pattern = get_pattern("sirs_epidemic")
    assert _requires_normalized_pattern(pattern, "SIRS with seasonal waves and a 10 day horizon")
    assert not _requires_normalized_pattern(pattern, "SIRS with seasonal waves and a 10 year horizon")
