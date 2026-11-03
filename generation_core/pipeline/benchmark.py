from __future__ import annotations

import json
import time
from pathlib import Path

from .generation import generate_model
from .llm import LLMClient
from .schemas import GenerationRequest, SimulationParameters
from .semantics import semantic_issues
from .simulation import simulate_model

PROMPTS_PATH = Path(__file__).with_name("benchmark_prompts.json")


def load_prompts() -> list[dict]:
    return json.loads(PROMPTS_PATH.read_text(encoding="utf-8"))


async def run_benchmark(
    llm: LLMClient,
    *,
    runs: int = 1,
    prompt_ids: list[str] | None = None,
    max_repairs: int = 2,
) -> dict:
    prompts = load_prompts()
    if prompt_ids:
        allowed = set(prompt_ids)
        prompts = [item for item in prompts if item["id"] in allowed]
    if not prompts:
        raise ValueError("benchmark has no prompts to run")
    cases = []
    for prompt in prompts:
        for run in range(runs):
            started = time.monotonic()
            case = {
                "prompt_id": prompt["id"],
                "run": run + 1,
                "expected_pattern": prompt["expected_pattern"],
                "executable": False,
                "semantic_pass": False,
                "units_pass": False,
                "topology_pass": False,
                "graph_pass": False,
                "repair_attempts": 0,
            }
            try:
                document = await generate_model(
                    GenerationRequest(description=prompt["description"]),
                    llm,
                    max_repairs=max_repairs,
                )
                parameters = SimulationParameters(
                    initial_time=document.time.initial_time,
                    final_time=document.time.initial_time + document.time.time_step * 4,
                    time_step=document.time.time_step,
                    saveper=document.time.time_step,
                )
                simulate_model(document, parameters)
                case["executable"] = True
                case["repair_attempts"] = document.repair_attempts
                errors = [item for item in document.validation.issues if item.severity == "error"]
                case["units_pass"] = not any("UNITS" in item.code for item in errors)
                case["topology_pass"] = not any(
                    token in item.code
                    for item in errors
                    for token in ("TOPOLOGY", "FLOW", "DERIVATIVE")
                )
                case["graph_pass"] = (
                    document.cld_data.validation.valid and document.sfd_data.validation.valid
                )
                case["semantic_pass"] = (
                    document.pattern_id == prompt["expected_pattern"]
                    and not semantic_issues(document)
                    and case["units_pass"]
                    and case["topology_pass"]
                    and case["graph_pass"]
                )
                case["actual_pattern"] = document.pattern_id
            except Exception as exc:
                case["error"] = str(exc)[:2000]
            case["duration_seconds"] = round(time.monotonic() - started, 3)
            cases.append(case)
    total = len(cases)
    return {
        "schema_version": "2.0",
        "kind": "llm_benchmark",
        "prompts": len(prompts),
        "runs_per_prompt": runs,
        "cases": total,
        "executable_rate": sum(case["executable"] for case in cases) / total,
        "semantic_rate": sum(case["semantic_pass"] for case in cases) / total,
        "units_rate": sum(case["units_pass"] for case in cases) / total,
        "topology_rate": sum(case["topology_pass"] for case in cases) / total,
        "graph_rate": sum(case["graph_pass"] for case in cases) / total,
        "repair_rate": sum(case["repair_attempts"] > 0 for case in cases) / total,
        "average_duration_seconds": round(
            sum(case["duration_seconds"] for case in cases) / total, 3
        ),
        "targets": {"executable_rate": 0.9, "semantic_rate": 0.85, "graph_rate": 1.0},
        "results": cases,
    }
