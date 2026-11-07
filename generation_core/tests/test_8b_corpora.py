import hashlib
import json
import re
from pathlib import Path

import pytest

from pipeline.pattern_library import get_pattern

ROOT = Path(__file__).parents[1] / "pipeline"
CORPORA = (
    ("benchmark_8b_stress_prompts.json", 28),
    ("benchmark_confirmatory_8b_v2_prompts.json", 24),
)
SUPPORTED_BEHAVIORS = {
    "analytic_exponential",
    "cascade",
    "conservation",
    "delayed_response",
    "event_change",
    "monotonic",
    "range",
    "sign_changes",
    "steady_state",
}


@pytest.mark.parametrize(("filename", "count"), CORPORA)
def test_8b_corpus_ids_patterns_and_variable_references_are_valid(filename, count):
    prompts = json.loads((ROOT / filename).read_text(encoding="utf-8"))
    assert len(prompts) == count
    assert len({prompt["id"] for prompt in prompts}) == count
    for prompt in prompts:
        if prompt["expected_pattern"] is not None:
            assert get_pattern(prompt["expected_pattern"]).document.validation.status == "passed"
        expected = prompt.get("expected_behavior")
        if not isinstance(expected, dict):
            continue
        assert expected["kind"] in SUPPORTED_BEHAVIORS
        names = expected.get("variables", [])
        if expected.get("variable"):
            names = [*names, expected["variable"]]
        for name in names:
            assert re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", prompt["description"]), (
                prompt["id"],
                name,
            )


def test_confirmatory_8b_corpus_is_frozen_before_live_evaluation():
    payload = (ROOT / "benchmark_confirmatory_8b_v2_prompts.json").read_bytes()
    assert hashlib.sha256(payload).hexdigest() == (
        "36f21c904440acd7dc0e25911d41e5a78c9a81a3734a9d0b517b7b2e4391be18"
    )
