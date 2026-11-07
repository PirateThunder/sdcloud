from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from .benchmark import run_benchmark
from .evaluation import compare_report_sets
from .llm import LLMClient

ABLATION_ARMS = ("direct", "typed_no_repair", "full")
PROTOCOL_PATH = Path(__file__).with_name("evaluation_protocol.json")


async def run_ablation(
    llm: LLMClient,
    *,
    runs: int = 1,
    prompt_ids: list[str] | None = None,
    prompts_path: Path | None = None,
    artifacts_dir: Path | None = None,
    max_repairs: int = 2,
    concurrency: int = 1,
    corpus_role: str = "regression",
    bootstrap_samples: int = 10_000,
    seed: int = 2026,
) -> dict:
    protocol_bytes = PROTOCOL_PATH.read_bytes()
    protocol = json.loads(protocol_bytes)
    protocol_sha256 = hashlib.sha256(protocol_bytes).hexdigest()
    reports = {}
    for arm in ABLATION_ARMS:
        report = await run_benchmark(
            llm,
            runs=runs,
            prompt_ids=prompt_ids,
            prompts_path=prompts_path,
            artifacts_dir=artifacts_dir / arm if artifacts_dir is not None else None,
            max_repairs=max_repairs,
            concurrency=concurrency,
            generation_mode=arm,
            corpus_role=corpus_role,
        )
        report["provider"] = getattr(llm, "provider_name", type(llm).__name__)
        report["model"] = getattr(llm, "model", None)
        report["protocol_sha256"] = protocol_sha256
        report["llm_settings"] = {
            field: getattr(llm, field, None)
            for field in (
                "structured_output",
                "component_structured_output",
                "pattern_shortcut",
                "allow_unstructured_fallback",
                "max_tokens",
                "request_retries",
                "seed",
                "provider_options",
            )
        }
        reports[arm] = report
    first = reports["direct"]
    actual = {
        "max_repairs": max_repairs,
        "bootstrap_samples": bootstrap_samples,
        "seed": seed,
        "inference_seed_base": getattr(llm, "seed", None),
    }
    expected = {
        "max_repairs": protocol["max_repairs"],
        "bootstrap_samples": protocol["interval"]["samples"],
        "seed": protocol["interval"]["seed"],
        "inference_seed_base": protocol["inference_seed"]["base"],
    }
    return {
        "schema_version": "1.0",
        "kind": "llm_ablation",
        "created_at": datetime.now(UTC).isoformat(),
        "protocol": {
            **protocol,
            "corpus_role": corpus_role,
            "arm_definitions": {
                "direct": "One JSON response; no ModelBrief, typed plan, pattern library, RAG or repair.",
                "typed_no_repair": "Current typed/pattern pipeline with repair budget zero.",
                "full": "The same pipeline with a bounded repair budget.",
                "shared": "Bounded AST, canonical normalization, validation, smoke simulation and metrics.",
            },
        },
        "protocol_sha256": protocol_sha256,
        "protocol_deviations": [
            {"field": field, "expected": expected[field], "actual": actual[field]}
            for field in actual
            if actual[field] != expected[field]
        ],
        "provider": first["provider"],
        "model": first["model"],
        "llm_settings": first["llm_settings"],
        "corpus_sha256": first["corpus_sha256"],
        "pipeline_sha256": first["pipeline_sha256"],
        "runs_per_prompt": runs,
        "max_repairs": max_repairs,
        "concurrency": concurrency,
        "arms": reports,
        "comparisons": compare_report_sets(
            reports,
            bootstrap_samples=bootstrap_samples,
            seed=seed,
        ),
    }
