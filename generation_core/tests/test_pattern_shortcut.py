import pytest

from pipeline.generation import _pattern_document_for_description, generate_model
from pipeline.pattern_library import get_pattern
from pipeline.schemas import GenerationRequest, SimulationParameters
from pipeline.simulation import simulate_model


class NoLLM:
    async def chat_json(self, *args, **kwargs):
        raise AssertionError("A qualitative validated pattern must not call the LLM")


@pytest.mark.parametrize(
    ("description", "pattern_id"),
    [
        (
            "A supply chain experiences a demand increase, shipping delays and bullwhip amplification of retailer purchasing orders.",
            "supply_chain_bullwhip",
        ),
        (
            "Students create an English speaking club with capacity limits, burnout and a recruitment campaign after week 60.",
            "student_club",
        ),
        (
            "Модель хищник-жертва: кролики размножаются, лисы едят кроликов и погибают естественным образом.",
            "predator_prey",
        ),
        (
            "Склад получает заказы с задержкой поставки, а продажи непрерывно уменьшают запас.",
            "supply_delay",
        ),
        (
            "Численность бактерий увеличивается экспоненциально с постоянной скоростью роста.",
            "exponential_growth",
        ),
        (
            "Новый продукт распространяется через инновации и подражание потенциальных пользователей.",
            "bass_diffusion",
        ),
    ],
)
async def test_qualitative_pattern_uses_validated_document_without_llm(
    monkeypatch, description, pattern_id
):
    monkeypatch.setenv("LLM_PATTERN_SHORTCUT", "1")
    document = await generate_model(GenerationRequest(description=description), NoLLM())
    assert document.pattern_id == pattern_id
    assert document.validation.status == "passed"
    assert document.repair_attempts == 0
    assert document.brief is not None
    assert document.assumptions[-1].source == "archetype"
    if pattern_id == "supply_chain_bullwhip":
        result = simulate_model(
            document,
            SimulationParameters(
                final_time=document.time.final_time,
                time_step=document.time.time_step,
                saveper=document.time.saveper,
            ),
        )
        assert max(result.variables["order_rate"]) > max(result.variables["demand"]) * 1.05


def test_pattern_shortcut_rejects_custom_numbers_and_time_conflicts():
    pattern = get_pattern("sirs_epidemic")
    assert _pattern_document_for_description(pattern, "SIRS with seasonal waves") is not None
    assert _pattern_document_for_description(pattern, "SIRS with initial_infectious=10") is None
    assert _pattern_document_for_description(pattern, "SIRS with time_step=0.1") is None
    assert _pattern_document_for_description(pattern, "SIRS with a 10 year horizon") is None
    student = get_pattern("student_club")
    assert _pattern_document_for_description(student, "Student club with a campaign after week 60") is not None
    assert _pattern_document_for_description(student, "Student club with club_capacity=90") is None


def test_every_validated_pattern_has_a_safe_default():
    from pipeline.pattern_library import _METADATA

    for pattern_id in sorted(_METADATA):
        pattern = get_pattern(pattern_id)
        document = _pattern_document_for_description(pattern, pattern.description)
        assert document is not None, pattern_id
        assert document.pattern_id == pattern_id
        assert document.validation.status == "passed", pattern_id


def test_russian_partitive_word_is_not_an_hour_unit():
    from pipeline.generation import _pattern_time_conflict

    pattern = get_pattern("workforce")
    description = "Компания нанимает новичков, а часть экспертов увольняется."
    assert not _pattern_time_conflict(pattern, description)
    assert _pattern_document_for_description(pattern, description) is not None
    for phrase in ("Модель на 1 час", "Модель на 1 часа", "Модель на 2 часов"):
        assert _pattern_time_conflict(pattern, phrase)
