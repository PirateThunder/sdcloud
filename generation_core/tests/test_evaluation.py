import csv
import json
from pathlib import Path

import httpx
import pytest

from pipeline.ablation import run_ablation
from pipeline.direct import generate_direct_model
from pipeline.evaluation import (
    compare_model_reports,
    compare_report_sets,
    export_annotation_tasks,
    inter_annotator_agreement,
    paired_metric_comparison,
)
from pipeline.exceptions import LLMResponseError, ModelValidationError
from pipeline.llm import FixtureLLM, OpenAICompatibleLLM, use_inference_seed
from pipeline.pattern_library import get_pattern
from pipeline.schemas import GenerationRequest

FIXTURE = Path(__file__).parent / "fixtures" / "llm_responses.json"


def direct_response():
    document = get_pattern("predator_prey").document
    return {
        "name": document.name,
        "time": document.time.model_dump(mode="json"),
        "variables": [item.model_dump(mode="json") for item in document.variables],
        "tables": [],
        "assumptions": [],
    }


class AblationFixture(FixtureLLM):
    def __init__(self):
        super().__init__(FIXTURE)
        self.calls = []

    async def chat_json(self, prompt, *, stage, system=None, temperature=0.3, response_schema=None):
        self.calls.append(stage)
        if stage == "direct":
            return direct_response()
        return await super().chat_json(
            prompt,
            stage=stage,
            system=system,
            temperature=temperature,
            response_schema=response_schema,
        )


async def test_direct_generation_is_single_stage_without_archetype_or_repair():
    llm = AblationFixture()
    document = await generate_direct_model(
        GenerationRequest(description="Модель хищник-жертва: кролики и лисы"),
        llm,
    )
    assert llm.calls == ["direct"]
    assert document.validation.status == "passed"
    assert document.repair_attempts == 0
    assert document.brief is None
    assert document.pattern_id is None
    assert document.artifacts["python"] == "model.py"


async def test_direct_generation_does_not_repair_invalid_output():
    class InvalidDirect:
        def __init__(self):
            self.calls = []

        async def chat_json(self, prompt, *, stage, system=None, temperature=0.3, response_schema=None):
            self.calls.append(stage)
            response = direct_response()
            response["variables"][0]["initial"] = None
            return response

    llm = InvalidDirect()
    with pytest.raises(ModelValidationError, match="missing initial") as exc_info:
        await generate_direct_model(GenerationRequest(description="A model"), llm)
    assert llm.calls == ["direct"]
    assert exc_info.value.repair_attempts == 0


async def test_ablation_runs_paired_arms_and_preserves_protocol(tmp_path):
    llm = FixtureLLM(FIXTURE.with_name("llm_ablation_responses.json"))
    llm.seed = 41
    result = await run_ablation(
        llm,
        runs=2,
        prompt_ids=["predator_prey_ru"],
        artifacts_dir=tmp_path / "artifacts",
        max_repairs=2,
        corpus_role="blind",
        bootstrap_samples=100,
        seed=11,
    )
    assert result["kind"] == "llm_ablation"
    assert len(result["protocol_sha256"]) == 64
    assert result["protocol"]["corpus_role"] == "blind"
    assert set(result["arms"]) == {"direct", "typed_no_repair", "full"}
    assert [result["arms"][arm]["max_repairs"] for arm in result["arms"]] == [0, 0, 2]
    assert all(report["behavior_rate"] == 1 for report in result["arms"].values())
    assert result["arms"]["direct"]["results"][0]["pattern_match"] is False
    assert result["arms"]["direct"]["results"][0]["semantic_pass"] is True
    assert all(
        [case["inference_seed"] for case in report["results"]] == [41, 42]
        for report in result["arms"].values()
    )
    assert len(result["comparisons"]) == 9
    assert (tmp_path / "artifacts" / "direct" / "predator_prey_ru-run-1" / "model.json").exists()


def synthetic_report(mode, outcomes, *, corpus="corpus", model="same-model"):
    cases = []
    for prompt_id, runs in outcomes.items():
        for run, passed in enumerate(runs, start=1):
            cases.append(
                {
                    "prompt_id": prompt_id,
                    "run": run,
                    "behavior_pass": passed,
                    "semantic_pass": passed,
                    "executable": passed,
                    "outcome_pass": passed,
                    "finite": passed,
                    "full_horizon": passed,
                    "graph_pass": passed,
                }
            )
    return {
        "kind": "llm_benchmark",
        "generation_mode": mode,
        "corpus_role": "regression",
        "corpus_sha256": corpus,
        "pipeline_sha256": "pipeline",
        "model": model,
        "results": cases,
    }


def test_paired_comparison_uses_prompt_clusters_and_exact_discordance():
    baseline = synthetic_report("direct", {"a": [False, False], "b": [False, False], "c": [False, False]})
    treatment = synthetic_report("full", {"a": [True, True], "b": [False, False], "c": [False, False]})
    first = paired_metric_comparison(baseline, treatment, bootstrap_samples=500, seed=9)
    second = paired_metric_comparison(baseline, treatment, bootstrap_samples=500, seed=9)
    assert first["pairs"] == 6
    assert first["prompt_clusters"] == 3
    assert first["difference"] == pytest.approx(1 / 3)
    assert first["discordant"] == {"treatment_only": 2, "baseline_only": 0}
    assert first["mcnemar_exact_pvalue"] == 0.5
    assert first["cluster_bootstrap"]["difference_ci95"] == second["cluster_bootstrap"]["difference_ci95"]


def test_paired_comparison_rejects_unfair_report_combinations():
    baseline = synthetic_report("direct", {"a": [False]})
    with pytest.raises(ValueError, match="corpus_sha256"):
        paired_metric_comparison(baseline, synthetic_report("full", {"a": [True]}, corpus="other"))
    with pytest.raises(ValueError, match="model"):
        paired_metric_comparison(baseline, synthetic_report("full", {"a": [True]}, model="other"))
    with pytest.raises(ValueError, match="identical prompt_id/run"):
        paired_metric_comparison(baseline, synthetic_report("full", {"b": [True]}))
    baseline["results"][0]["inference_seed"] = 2026
    treatment = synthetic_report("full", {"a": [True]})
    treatment["results"][0]["inference_seed"] = 2027
    with pytest.raises(ValueError, match="inference_seed"):
        paired_metric_comparison(baseline, treatment)


def test_model_comparison_uses_matching_modes_and_allows_only_model_change():
    def ablation(model, passed):
        arms = {
            mode: synthetic_report(mode, {"a": [passed], "b": [False]}, model=model)
            for mode in ("direct", "typed_no_repair", "full")
        }
        return {
            "kind": "llm_ablation",
            "model": model,
            "corpus_sha256": "corpus",
            "pipeline_sha256": "pipeline",
            "protocol_sha256": "protocol",
            "protocol": {"corpus_role": "blind"},
            "arms": arms,
        }

    result = compare_model_reports(
        ablation("small", False),
        ablation("large", True),
        metrics=("behavior",),
        bootstrap_samples=50,
    )
    assert result["kind"] == "paired_model_comparison"
    assert len(result["comparisons"]) == 3
    full = next(
        item for item in result["comparisons"] if item["generation_mode"] == "full"
    )
    assert full["difference"] == 0.5
    assert "mcnemar_holm_pvalue" in full


def test_ablation_comparisons_include_multiplicity_correction():
    reports = {
        "direct": synthetic_report("direct", {"a": [False]}),
        "typed_no_repair": synthetic_report("typed_no_repair", {"a": [False]}),
        "full": synthetic_report("full", {"a": [True]}),
    }
    result = compare_report_sets(reports, metrics=("behavior",), bootstrap_samples=20)
    assert len(result) == 3
    assert all("mcnemar_holm_pvalue" in item for item in result)
    assert all(item["warning"].startswith("One prompt") for item in result)


def annotation_report(mode, *, executable=True):
    return {
        "kind": "llm_benchmark",
        "generation_mode": mode,
        "corpus_sha256": "corpus",
        "pipeline_sha256": "pipeline",
        "results": [
            {
                "prompt_id": "prompt",
                "run": 1,
                "description": "Describe a population",
                "executable": executable,
                "semantic_pass": executable,
                "behavior_pass": executable,
                "model": {
                    "name": "Population",
                    "description": "Describe a population",
                    "time": {"unit": "year", "initial_time": 0, "final_time": 1, "time_step": 1, "saveper": 1},
                    "variables": [],
                    "pattern_id": "private_pattern",
                    "brief": {"private": True},
                    "repair_attempts": 2,
                    "validation": {"status": "passed"},
                    "generation_log": ["private"],
                } if executable else None,
                "simulation": {
                    "time": [0, 1],
                    "variables": {"population": [1, 2]},
                    "engine": "scipy",
                    "integration_method": "euler",
                } if executable else None,
            }
        ],
    }


def test_annotation_export_is_blinded_and_separates_answer_key(tmp_path):
    reports = {
        "direct": annotation_report("direct", executable=False),
        "typed_no_repair": annotation_report("typed_no_repair"),
        "full": annotation_report("full"),
    }
    result = export_annotation_tasks(reports, tmp_path, seed=13)
    assert result["tasks"] == 3
    with (tmp_path / "expert" / "tasks.csv").open(encoding="utf-8", newline="") as stream:
        tasks = list(csv.DictReader(stream))
    assert len(tasks) == 3
    assert "generation_mode" not in tasks[0]
    assert {task["generation_status"] for task in tasks} == {"model", "no_model"}
    model_task = next(task for task in tasks if task["generation_status"] == "model")
    artifact = json.loads((tmp_path / "expert" / model_task["artifact"]).read_text())
    assert "pattern_id" not in artifact["model"]
    assert "brief" not in artifact["model"]
    assert "repair_attempts" not in artifact["model"]
    assert "validation" not in artifact["model"]
    assert "generation_log" not in artifact["model"]
    answer_key = json.loads((tmp_path / "private" / "answer_key.json").read_text())
    assert {item["generation_mode"] for item in answer_key} == set(reports)
    assert not (tmp_path / "expert" / "answer_key.json").exists()


def test_inter_annotator_agreement_handles_missing_and_constant_scores(tmp_path):
    rows = [
        {"annotation_id": "a", "semantic_score": "1", "behavior_score": "0"},
        {"annotation_id": "b", "semantic_score": "1", "behavior_score": "0"},
        {"annotation_id": "c", "semantic_score": "0", "behavior_score": "NA"},
        {"annotation_id": "d", "semantic_score": "0", "behavior_score": "0"},
    ]
    second_rows = [
        {"annotation_id": "a", "semantic_score": "1", "behavior_score": "0"},
        {"annotation_id": "b", "semantic_score": "0", "behavior_score": "0"},
        {"annotation_id": "c", "semantic_score": "1", "behavior_score": "0"},
        {"annotation_id": "d", "semantic_score": "0", "behavior_score": "0"},
    ]
    for name, values in (("first", rows), ("second", second_rows)):
        with (tmp_path / f"{name}.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(values[0]))
            writer.writeheader()
            writer.writerows(values)
    result = inter_annotator_agreement(tmp_path / "first.csv", tmp_path / "second.csv")
    assert result["metrics"]["semantic_score"]["cohens_kappa"] == 0
    assert result["metrics"]["behavior_score"]["observed_agreement"] == 1
    assert result["metrics"]["behavior_score"]["cohens_kappa"] is None
    assert result["metrics"]["behavior_score"]["excluded_or_missing"] == 1


async def test_openai_compatible_seed_is_recorded_in_request():
    captured = {}

    async def handler(request):
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]},
        )

    llm = OpenAICompatibleLLM(
        "test-model",
        base_url="http://test",
        seed=17,
        transport=httpx.MockTransport(handler),
    )
    try:
        assert await llm.chat_json("prompt", stage="test") == {}
        assert captured["seed"] == 17
        with use_inference_seed(23):
            assert await llm.chat_json("prompt", stage="test") == {}
            assert captured["seed"] == 23
        assert await llm.chat_json("prompt", stage="test") == {}
        assert captured["seed"] == 17
        assert llm.seed == 17
    finally:
        await llm.close()


async def test_provider_error_body_without_choices_is_reported():
    async def handler(request):
        return httpx.Response(
            200,
            json={"error": {"message": "Structured output backend is incompatible", "code": 400}},
        )

    llm = OpenAICompatibleLLM(
        "test-model",
        base_url="http://test",
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(LLMResponseError, match="no choices.*incompatible"):
            await llm.chat_json("prompt", stage="test")
    finally:
        await llm.close()
