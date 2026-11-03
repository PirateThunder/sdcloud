import copy
import json
from pathlib import Path

from pipeline.conversation import respond_to_message
from pipeline.pattern_library import get_pattern
from pipeline.schemas import ConversationRequest

FIXTURE = Path(__file__).parent / "fixtures" / "llm_responses.json"


class ConversationLLM:
    def __init__(self, action: str, text: str) -> None:
        self.responses = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.decision = {"action": action, "assistant_text": text}
        self.calls = []
        self.prompts = {}

    async def chat_json(self, prompt, *, stage, system=None, temperature=0.3, response_schema=None):
        self.calls.append(stage)
        self.prompts[stage] = prompt
        if stage == "message":
            return copy.deepcopy(self.decision)
        return copy.deepcopy(self.responses[stage])

    async def close(self):
        return None


def test_equation_stage_accepts_a_complete_model_document():
    from pipeline.generation import _expressions

    expression = {"op": "lit", "value": 0.2}
    assert _expressions(
        {
            "name": "Updated model",
            "variables": [
                {"id": "prey", "kind": "stock", "initial": {"op": "lit", "value": 100}},
                {"id": "prey_growth", "kind": "constant", "expression": expression},
            ],
        }
    ) == {"prey_growth": expression}


async def test_question_uses_model_and_history_without_generation():
    base = get_pattern("predator_prey").document
    llm = ConversationLLM("answer", "Prey growth is **0.1 per year**.")
    response = await respond_to_message(
        ConversationRequest(
            description="What is the prey growth rate?",
            history=[{"role": "user", "content": "Explain the rabbit population."}],
            base_model=base,
        ),
        llm,
    )
    assert response.kind == "answer"
    assert response.model is None
    assert response.assistant_text == "Prey growth is **0.1 per year**."
    assert llm.calls == ["message"]
    assert "Explain the rabbit population" in llm.prompts["message"]
    assert '"prey_growth"' in llm.prompts["message"]


async def test_ambiguous_request_returns_clarification_without_generation():
    llm = ConversationLLM("clarify", "Do you want to change the rate or the initial population?")
    response = await respond_to_message(
        ConversationRequest(
            description="Change it to 20", base_model=get_pattern("predator_prey").document
        ),
        llm,
    )
    assert response.kind == "clarification"
    assert response.model is None
    assert llm.calls == ["message"]


async def test_update_receives_base_model_and_returns_complete_model():
    base = get_pattern("predator_prey").document
    llm = ConversationLLM("update", "Updated the prey growth rate.")
    response = await respond_to_message(
        ConversationRequest(
            description="Set prey growth to 0.2",
            history=[{"role": "assistant", "content": "The model is ready."}],
            base_model=base,
        ),
        llm,
        max_repairs=0,
    )
    assert response.kind == "model"
    assert response.model is not None
    assert response.model.validation.status == "passed"
    assert response.model.description == base.description
    assert response.assistant_text == "Updated the prey growth rate."
    assert llm.calls == ["message", "brief", "variables", "equations"]
    assert "Current canonical model (the source of truth)" in llm.prompts["variables"]
    assert "Set prey growth to 0.2" in llm.prompts["variables"]
    assert '"prey_growth"' in llm.prompts["variables"]
