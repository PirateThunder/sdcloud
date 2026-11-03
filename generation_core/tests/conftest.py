from pathlib import Path

import pytest

from pipeline.llm import FixtureLLM
from pipeline.schemas import GenerationRequest

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "llm_responses.json"


@pytest.fixture
def generation_request() -> GenerationRequest:
    return GenerationRequest(
        description="Модель хищник-жертва: кролики размножаются, лисы едят кроликов."
    )


@pytest.fixture
def fixture_llm() -> FixtureLLM:
    return FixtureLLM(FIXTURE_PATH)
