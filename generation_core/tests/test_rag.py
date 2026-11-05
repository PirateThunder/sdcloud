import json

import pytest

from pipeline.generation import generate_model
from pipeline.io import write_json_atomic
from pipeline.rag import RagExample, component_rag_context, load_examples, retrieve
from pipeline.rag_corpus import build_corpus
from pipeline.schemas import GenerationRequest, ModelDocument
from tests.test_components import ComponentLLM, component_brief, component_plan, document


def example(identifier="verified_example", kind="first_order", description="A custom first-order dynamic mechanism"):
    component = {
        "kind": kind,
        "source": "source_stock",
        "target": "cloud:sink",
        "flow": "transfer",
        "coefficient": 0.2,
        "initial_source": 100,
        "initial_target": 0,
        "source_units": {"item": 1},
        "target_units": None,
        "time_unit": "day",
    }
    if kind == "delay":
        component = {
            "kind": "delay",
            "stock": "inventory",
            "inflow": "transport",
            "outflow": "consumption",
            "input_rate": 8,
            "delay_time": 3,
            "initial_stock": 0,
            "initial_delayed_rate": 0,
            "stock_units": {"item": 1},
            "time_unit": "day",
            "consumption_time": 2,
        }
    return RagExample(
        id=identifier,
        description=description,
        components=[component],
        time={"unit": "day", "initial_time": 0, "final_time": 20, "time_step": 0.1, "saveper": 0.1},
        assumptions=[],
        source={"report": "test", "run": 1},
    )


def write_corpus(path, examples):
    write_json_atomic(
        path,
        {
            "schema_version": "1.0",
            "kind": "lexical_component_rag",
            "source_reports": ["test"],
            "examples": [item.model_dump(mode="json") for item in examples],
        },
    )


def test_retrieval_prefers_the_mechanism_shared_with_the_query():
    hits = retrieve(
        "A workshop receives parts through a third-order transport lag with consumption.",
        [example(), example("verified_delay", "delay", "Third-order material transport with a delay.")],
    )
    assert len(hits) == 1
    assert hits[0].example.id == "verified_delay"
    assert 0 < hits[0].score <= 1


def test_rag_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("LLM_RAG_ENABLED", raising=False)
    assert component_rag_context("Any model") == ("", [])


def test_rag_context_respects_size_and_duplicate_ids(monkeypatch, tmp_path):
    path = tmp_path / "rag.json"
    write_corpus(path, [example()])
    monkeypatch.setenv("LLM_RAG_ENABLED", "1")
    monkeypatch.setenv("LLM_RAG_CORPUS_PATH", str(path))
    context, sources = component_rag_context("A custom first-order dynamic mechanism")
    assert "verified_example" in context
    assert sources == ["verified_example"]
    monkeypatch.setenv("LLM_RAG_MAX_CHARS", "500")
    assert component_rag_context("A custom first-order dynamic mechanism") == ("", [])
    duplicate = [example(), example()]
    write_corpus(path, duplicate)
    with pytest.raises(Exception, match="ids must be unique"):
        load_examples(path)


class PromptLLM(ComponentLLM):
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


async def test_generation_uses_rag_only_with_explicit_opt_in(monkeypatch, tmp_path):
    path = tmp_path / "rag.json"
    write_corpus(path, [example()])
    monkeypatch.setenv("LLM_RAG_CORPUS_PATH", str(path))
    monkeypatch.delenv("LLM_RAG_ENABLED", raising=False)
    llm = PromptLLM()
    result = await generate_model(
        GenerationRequest(description="A custom first-order dynamic mechanism"),
        llm,
        max_repairs=0,
    )
    assert "RAG" not in llm.prompts["components"]
    assert not any(item.startswith("rag:") for item in result.generation_log)

    monkeypatch.setenv("LLM_RAG_ENABLED", "1")
    llm = PromptLLM()
    result = await generate_model(
        GenerationRequest(description="A custom first-order dynamic mechanism"),
        llm,
        max_repairs=0,
    )
    assert "Проверенный RAG пример verified_example" in llm.prompts["components"]
    assert "rag: verified_example" in result.generation_log


def test_corpus_builder_excludes_failures_and_evaluation_ids(monkeypatch, tmp_path):
    root = tmp_path
    report_name = "test-report.json"
    monkeypatch.setattr("pipeline.rag_corpus.REPORT_SOURCES", (report_name,))
    model = document(component_plan()["components"])
    model = ModelDocument.model_validate(
        model.model_copy(update={"brief": component_brief()}).model_dump(mode="json")
    )
    cases = []
    for index, (prompt_id, behavior_pass) in enumerate(
        (("independent_valid", True), ("independent_failed", False), ("accept_leakage", True)),
        start=1,
    ):
        directory = root / "out" / f"case-{index}"
        write_json_atomic(directory / "prompt.json", {"id": prompt_id, "description": prompt_id})
        write_json_atomic(directory / "model.json", model.model_dump(mode="json"))
        cases.append(
            {
                "prompt_id": prompt_id,
                "run": 1,
                "behavior_pass": behavior_pass,
                "semantic_pass": True,
                "artifacts": f"/app/work_api/case-{index}",
            }
        )
    write_json_atomic(root / "out" / report_name, {"results": cases})
    corpus = build_corpus(root)
    assert [item["id"] for item in corpus["examples"]] == ["independent_valid"]


def test_committed_corpus_contains_only_unique_development_examples():
    from pathlib import Path

    examples = load_examples(Path(__file__).parents[1] / "pipeline" / "rag_examples.json")
    ids = [item.id for item in examples]
    assert len(examples) == 24
    assert len(ids) == len(set(ids))
    assert not any(identifier.startswith(("accept", "blind")) for identifier in ids)
    assert all(item.components for item in examples)
    assert all(json.dumps(item.components, ensure_ascii=False) for item in examples)
