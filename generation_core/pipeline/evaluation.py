from __future__ import annotations

import csv
import hashlib
import json
import random
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import binomtest

from .io import write_json_atomic

CASE_METRICS = {
    "executable": "executable",
    "semantic": "semantic_pass",
    "behavior": "behavior_pass",
    "outcome": "outcome_pass",
    "finite": "finite",
    "full_horizon": "full_horizon",
    "graph": "graph_pass",
}
DEFAULT_COMPARISONS = (
    ("direct", "typed_no_repair"),
    ("typed_no_repair", "full"),
    ("direct", "full"),
)


def _case_index(report: Mapping[str, Any]) -> dict[tuple[str, int], Mapping[str, Any]]:
    if report.get("kind") != "llm_benchmark":
        raise ValueError("paired comparison requires llm_benchmark reports")
    indexed = {}
    for case in report.get("results", []):
        key = (str(case["prompt_id"]), int(case["run"]))
        if key in indexed:
            raise ValueError(f"duplicate benchmark case: {key}")
        indexed[key] = case
    if not indexed:
        raise ValueError("benchmark report has no cases")
    return indexed


def _check_compatibility(
    baseline: Mapping[str, Any],
    treatment: Mapping[str, Any],
    *,
    allow_model_difference: bool = False,
) -> None:
    for field in ("corpus_sha256", "pipeline_sha256"):
        if baseline.get(field) != treatment.get(field):
            raise ValueError(f"reports have different {field}")
    fields = ("provider", "corpus_role", "protocol_sha256")
    if not allow_model_difference:
        fields = (*fields, "model")
    for field in fields:
        left = baseline.get(field)
        right = treatment.get(field)
        if left is not None and right is not None and left != right:
            raise ValueError(f"reports have different {field}")
    if (
        "llm_settings" in baseline
        and "llm_settings" in treatment
        and baseline["llm_settings"] != treatment["llm_settings"]
    ):
        raise ValueError("reports have different llm_settings")


def paired_metric_comparison(
    baseline: Mapping[str, Any],
    treatment: Mapping[str, Any],
    *,
    metric: str = "behavior",
    bootstrap_samples: int = 10_000,
    seed: int = 2026,
    allow_model_difference: bool = False,
) -> dict[str, Any]:
    if metric not in CASE_METRICS:
        raise ValueError(f"unknown paired metric: {metric}")
    if bootstrap_samples < 1:
        raise ValueError("bootstrap_samples must be positive")
    _check_compatibility(
        baseline, treatment, allow_model_difference=allow_model_difference
    )
    baseline_cases = _case_index(baseline)
    treatment_cases = _case_index(treatment)
    if baseline_cases.keys() != treatment_cases.keys():
        raise ValueError("reports do not contain identical prompt_id/run pairs")
    for key in baseline_cases:
        baseline_seed = baseline_cases[key].get("inference_seed")
        treatment_seed = treatment_cases[key].get("inference_seed")
        if (
            baseline_seed is not None
            and treatment_seed is not None
            and baseline_seed != treatment_seed
        ):
            raise ValueError(f"reports have different inference_seed for {key}")
    field = CASE_METRICS[metric]
    pairs = [
        (
            baseline_cases[key]["prompt_id"],
            int(bool(baseline_cases[key][field])),
            int(bool(treatment_cases[key][field])),
        )
        for key in sorted(baseline_cases)
    ]
    prompt_ids = sorted({item[0] for item in pairs})
    by_prompt = {
        prompt_id: [(base, treatment_value) for name, base, treatment_value in pairs if name == prompt_id]
        for prompt_id in prompt_ids
    }
    rng = np.random.default_rng(seed)
    deltas = np.empty(bootstrap_samples, dtype=float)
    for index in range(bootstrap_samples):
        sampled = rng.choice(prompt_ids, size=len(prompt_ids), replace=True)
        sampled_pairs = [pair for prompt_id in sampled for pair in by_prompt[str(prompt_id)]]
        deltas[index] = np.mean(
            [treatment_value - base for base, treatment_value in sampled_pairs]
        )
    improved = sum(not base and treatment_value for _, base, treatment_value in pairs)
    declined = sum(base and not treatment_value for _, base, treatment_value in pairs)
    discordant = improved + declined
    baseline_successes = sum(base for _, base, _ in pairs)
    treatment_successes = sum(treatment_value for _, _, treatment_value in pairs)
    total = len(pairs)
    lower, upper = np.quantile(deltas, [0.025, 0.975])
    result = {
        "metric": metric,
        "baseline": baseline.get("generation_mode"),
        "treatment": treatment.get("generation_mode"),
        "pairs": total,
        "prompt_clusters": len(prompt_ids),
        "baseline_successes": baseline_successes,
        "treatment_successes": treatment_successes,
        "baseline_rate": baseline_successes / total,
        "treatment_rate": treatment_successes / total,
        "difference": treatment_successes / total - baseline_successes / total,
        "discordant": {
            "treatment_only": improved,
            "baseline_only": declined,
        },
        "mcnemar_exact_pvalue": (
            float(binomtest(improved, discordant, 0.5).pvalue) if discordant else 1.0
        ),
        "cluster_bootstrap": {
            "method": "percentile",
            "cluster_unit": "prompt_id",
            "confidence_level": 0.95,
            "samples": bootstrap_samples,
            "seed": seed,
            "difference_ci95": [float(lower), float(upper)],
        },
    }
    if len(prompt_ids) < 2:
        result["warning"] = "One prompt cluster: the interval cannot estimate between-prompt variability."
    return result


def compare_report_sets(
    reports: Mapping[str, Mapping[str, Any]],
    *,
    metrics: Sequence[str] = ("executable", "semantic", "behavior"),
    bootstrap_samples: int = 10_000,
    seed: int = 2026,
) -> list[dict[str, Any]]:
    comparisons = []
    for comparison_index, (baseline_name, treatment_name) in enumerate(DEFAULT_COMPARISONS):
        if baseline_name not in reports or treatment_name not in reports:
            raise ValueError(f"missing ablation arms: {baseline_name}, {treatment_name}")
        for metric_index, metric in enumerate(metrics):
            item = paired_metric_comparison(
                reports[baseline_name],
                reports[treatment_name],
                metric=metric,
                bootstrap_samples=bootstrap_samples,
                seed=seed + comparison_index * len(metrics) + metric_index,
            )
            item["baseline"] = baseline_name
            item["treatment"] = treatment_name
            comparisons.append(item)
    for metric in metrics:
        family = sorted(
            (item for item in comparisons if item["metric"] == metric),
            key=lambda item: item["mcnemar_exact_pvalue"],
        )
        previous = 0.0
        for rank, item in enumerate(family):
            adjusted = min(
                1.0,
                (len(family) - rank) * item["mcnemar_exact_pvalue"],
            )
            previous = max(previous, adjusted)
            item["mcnemar_holm_pvalue"] = previous
    return comparisons


def compare_model_reports(
    baseline: Mapping[str, Any],
    treatment: Mapping[str, Any],
    *,
    metrics: Sequence[str] = ("executable", "semantic", "behavior"),
    bootstrap_samples: int = 10_000,
    seed: int = 2026,
) -> dict[str, Any]:
    if baseline.get("kind") != "llm_ablation" or treatment.get("kind") != "llm_ablation":
        raise ValueError("model comparison requires llm_ablation reports")
    for field in ("corpus_sha256", "pipeline_sha256", "protocol_sha256"):
        if baseline.get(field) != treatment.get(field):
            raise ValueError(f"reports have different {field}")
    comparisons = []
    arms = ("direct", "typed_no_repair", "full")
    for arm_index, arm in enumerate(arms):
        if arm not in baseline["arms"] or arm not in treatment["arms"]:
            raise ValueError(f"missing model comparison arm: {arm}")
        for metric_index, metric in enumerate(metrics):
            item = paired_metric_comparison(
                baseline["arms"][arm],
                treatment["arms"][arm],
                metric=metric,
                bootstrap_samples=bootstrap_samples,
                seed=seed + arm_index * len(metrics) + metric_index,
                allow_model_difference=True,
            )
            item["generation_mode"] = arm
            item["baseline"] = baseline.get("model")
            item["treatment"] = treatment.get("model")
            comparisons.append(item)
    for metric in metrics:
        family = sorted(
            (item for item in comparisons if item["metric"] == metric),
            key=lambda item: item["mcnemar_exact_pvalue"],
        )
        previous = 0.0
        for rank, item in enumerate(family):
            adjusted = min(1.0, (len(family) - rank) * item["mcnemar_exact_pvalue"])
            previous = max(previous, adjusted)
            item["mcnemar_holm_pvalue"] = previous
    return {
        "schema_version": "1.0",
        "kind": "paired_model_comparison",
        "baseline_model": baseline.get("model"),
        "treatment_model": treatment.get("model"),
        "corpus_sha256": baseline.get("corpus_sha256"),
        "pipeline_sha256": baseline.get("pipeline_sha256"),
        "protocol_sha256": baseline.get("protocol_sha256"),
        "corpus_role": baseline.get("protocol", {}).get("corpus_role"),
        "comparisons": comparisons,
    }


def _public_model(model: Mapping[str, Any]) -> dict[str, Any]:
    fields = (
        "name",
        "description",
        "time",
        "variables",
        "tables",
        "dimensions",
        "assumptions",
    )
    return {field: model[field] for field in fields if field in model}


def _load_case_artifacts(case: Mapping[str, Any]) -> tuple[dict | None, dict | None, str]:
    artifacts = case.get("artifacts")
    workdir = Path(artifacts) if artifacts else None
    prompt_path = workdir / "prompt.json" if workdir else None
    if prompt_path is not None and prompt_path.exists():
        prompt = json.loads(prompt_path.read_text(encoding="utf-8"))
        description = prompt["description"]
    else:
        description = str(case.get("description", ""))
    model = case.get("model")
    simulation = case.get("simulation")
    if workdir is not None and case.get("executable"):
        model_path = workdir / "model.json"
        simulation_path = workdir / "simulation.json"
        if model is None and model_path.exists():
            model = json.loads(model_path.read_text(encoding="utf-8"))
        if simulation is None and simulation_path.exists():
            simulation = json.loads(simulation_path.read_text(encoding="utf-8"))
    if case.get("executable") and (model is None or simulation is None):
        raise ValueError(
            f"expert export requires model.json and simulation.json for {case.get('prompt_id')}"
        )
    if model is not None:
        model = _public_model(model)
    if simulation is not None:
        simulation = {
            field: simulation[field]
            for field in ("time", "variables", "engine", "integration_method")
            if field in simulation
        }
    return model, simulation, description


def export_annotation_tasks(
    reports: Mapping[str, Mapping[str, Any]],
    output_dir: Path,
    *,
    seed: int = 2026,
) -> dict[str, Any]:
    if not reports:
        raise ValueError("expert export requires at least one report")
    first_report = next(iter(reports.values()))
    reference_keys = set(_case_index(first_report))
    for report in reports.values():
        _check_compatibility(first_report, report)
        if set(_case_index(report)) != reference_keys:
            raise ValueError("expert export requires identical prompt_id/run pairs")
    expert_dir = output_dir / "expert"
    models_dir = expert_dir / "models"
    private_dir = output_dir / "private"
    models_dir.mkdir(parents=True, exist_ok=True)
    private_dir.mkdir(parents=True, exist_ok=True)
    for path in models_dir.glob("task_*.json"):
        path.unlink()
    tasks = []
    answer_key = []
    for arm, report in reports.items():
        for case in _case_index(report).values():
            identity = f"{seed}\0{arm}\0{case['prompt_id']}\0{case['run']}"
            task_id = "task_" + hashlib.sha256(identity.encode()).hexdigest()[:20]
            model, simulation, description = _load_case_artifacts(case)
            if not description:
                raise ValueError(f"missing prompt description for {case['prompt_id']}")
            relative_artifact = None
            if model is not None:
                relative_artifact = f"models/{task_id}.json"
                write_json_atomic(
                    expert_dir / relative_artifact,
                    {
                        "description": description,
                        "model": model,
                        "simulation": simulation,
                    },
                )
            tasks.append(
                {
                    "annotation_id": task_id,
                    "description": description,
                    "generation_status": "model" if model is not None else "no_model",
                    "artifact": relative_artifact,
                    "semantic_score": "",
                    "behavior_score": "",
                    "failure_categories": "",
                    "comments": "",
                    "confidence": "",
                }
            )
            answer_key.append(
                {
                    "annotation_id": task_id,
                    "generation_mode": arm,
                    "prompt_id": case["prompt_id"],
                    "run": case["run"],
                    "executable": case["executable"],
                    "semantic_pass": case["semantic_pass"],
                    "behavior_pass": case["behavior_pass"],
                    "artifacts": case.get("artifacts"),
                }
            )
    random.Random(seed).shuffle(tasks)
    fields = [
        "annotation_id",
        "description",
        "generation_status",
        "artifact",
        "semantic_score",
        "behavior_score",
        "failure_categories",
        "comments",
        "confidence",
    ]
    with (expert_dir / "tasks.jsonl").open("w", encoding="utf-8") as stream:
        for task in tasks:
            stream.write(json.dumps(task, ensure_ascii=False) + "\n")
    with (expert_dir / "tasks.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(tasks)
    guide = """# Независимая оценка системно-динамических моделей

Оценивайте задания независимо, не пытаясь определить способ генерации и не используя
private answer key. Для каждой строки tasks.csv откройте указанный artifact, если он есть.
Файл содержит исходное описание, модель и траектории симуляции. Названия переменных и
внешнее оформление сами по себе не являются ошибкой.

- semantic_score=1: модель содержательно соответствует описанию. Проверьте границы,
  stocks/flows, начальные значения, уравнения, units, направления и полноту механизмов.
  Существенные пропуски, неподтверждённые механизмы и неверные уравнения означают 0.
- behavior_score=1: при semantic_score=1 траектории соответствуют явно заданному и
  обоснованно ожидаемому поведению на всём горизонте. Нефизичные значения, неожиданная
  статичность, нарушение сохранения или противоречие описанию означают 0.
- generation_status=no_model: обе оценки равны 0. Ошибка генерации не даёт оснований
  считать модель семантически или поведенчески корректной.
- failure_categories: краткие коды через точку с запятой, например missing_mechanism,
  wrong_equation, wrong_units, wrong_topology, invalid_initial, implausible_behavior.
- comments: конкретное обоснование оценки, особенно для нуля и спорных случаев.
- confidence: high, medium или low. Если описание не позволяет оценить аспект, поставьте
  NA в соответствующей колонке и обязательно объясните почему в comments.

Не изменяйте annotation_id, порядок заданий и содержимое artifacts. Не обсуждайте задания
со вторым экспертом до завершения независимой разметки. Расхождения разбираются отдельно
на этапе adjudication; согласованность рассчитывается до adjudication.
"""
    (expert_dir / "annotation_guide.md").write_text(guide, encoding="utf-8")
    write_json_atomic(private_dir / "answer_key.json", answer_key)
    manifest = {
        "schema_version": "1.0",
        "kind": "blind_annotation_export",
        "seed": seed,
        "tasks": len(tasks),
        "prompts": len({item["prompt_id"] for item in answer_key}),
        "generation_modes": list(reports),
        "provider": first_report.get("provider"),
        "model": first_report.get("model"),
        "corpus_role": first_report.get("corpus_role"),
        "corpus_sha256": first_report.get("corpus_sha256"),
        "pipeline_sha256": first_report.get("pipeline_sha256"),
        "protocol_sha256": first_report.get("protocol_sha256"),
        "expert_files": ["expert/tasks.csv", "expert/tasks.jsonl", "expert/annotation_guide.md"],
        "private_files": ["private/answer_key.json"],
    }
    write_json_atomic(output_dir / "manifest.json", manifest)
    return manifest


def _read_scores(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    result = {}
    for row in rows:
        task_id = row.get("annotation_id", "")
        if not task_id or task_id in result:
            raise ValueError(f"missing or duplicate annotation_id in {path}")
        for field in ("semantic_score", "behavior_score"):
            if row.get(field, "").strip().upper() not in {"", "0", "1", "NA"}:
                raise ValueError(f"invalid {field} for {task_id}: {row.get(field)!r}")
        if (
            row.get("behavior_score", "").strip() == "1"
            and row.get("semantic_score", "").strip() == "0"
        ):
            raise ValueError(f"behavior_score=1 requires semantic_score!=0 for {task_id}")
        result[task_id] = row
    return result


def inter_annotator_agreement(
    first_path: Path,
    second_path: Path,
    *,
    fields: Sequence[str] = ("semantic_score", "behavior_score"),
    include_no_model: bool = False,
) -> dict[str, Any]:
    first = _read_scores(first_path)
    second = _read_scores(second_path)
    shared = sorted(first.keys() & second.keys())
    eligible = [
        task_id
        for task_id in shared
        if include_no_model
        or (
            first[task_id].get("generation_status") != "no_model"
            and second[task_id].get("generation_status") != "no_model"
        )
    ]
    results = {}
    for field in fields:
        values = []
        for task_id in eligible:
            left = first[task_id].get(field, "").strip().upper()
            right = second[task_id].get(field, "").strip().upper()
            if left not in {"0", "1"} or right not in {"0", "1"}:
                continue
            values.append((int(left), int(right)))
        if not values:
            results[field] = {"pairs": 0, "cohens_kappa": None}
            continue
        observed = sum(left == right for left, right in values) / len(values)
        first_positive = sum(left for left, _ in values) / len(values)
        second_positive = sum(right for _, right in values) / len(values)
        expected = (
            first_positive * second_positive
            + (1 - first_positive) * (1 - second_positive)
        )
        kappa = (observed - expected) / (1 - expected) if expected < 1 else None
        results[field] = {
            "pairs": len(values),
            "observed_agreement": observed,
            "expected_agreement": expected,
            "cohens_kappa": kappa,
            "excluded_or_missing": len(eligible) - len(values),
        }
    return {
        "schema_version": "1.0",
        "kind": "inter_annotator_agreement",
        "shared_tasks": len(shared),
        "eligible_shared_tasks": len(eligible),
        "excluded_no_model": len(shared) - len(eligible),
        "include_no_model": include_no_model,
        "first_only_tasks": len(first.keys() - second.keys()),
        "second_only_tasks": len(second.keys() - first.keys()),
        "metrics": results,
        "note": "Kappa is undefined when expected agreement is 1; report prevalence and raw agreement.",
    }
