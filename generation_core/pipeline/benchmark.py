from __future__ import annotations

import json
import math
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


def _sign_changes(series: list[float]) -> int:
    return sum(
        left * right < 0 for left, right in zip(series, series[1:], strict=False)
    )


def _expected_behavior(prompt: dict, result) -> tuple[bool, dict]:
    expected = prompt.get("expected_behavior")
    if expected is None:
        return True, {}
    if expected == "repeated_waves":
        series = result.variables.get("infectious", [])
        peaks = [
            value
            for index in range(1, len(series) - 1)
            if (value := series[index]) > series[index - 1]
            and value >= series[index + 1]
            and value > 1
        ]
        return len(peaks) >= 3, {"epidemic_waves": len(peaks)}
    if expected == "bullwhip":
        orders = result.variables.get("order_rate", [])
        demand = result.variables.get("demand", [])
        peak_demand = max(demand, default=0)
        peak_orders = max(orders, default=0)
        return bool(demand and orders and peak_orders > peak_demand * 1.05), {
            "peak_demand": peak_demand,
            "peak_orders": peak_orders,
        }
    if expected == "campaign_wave":
        members = result.variables.get("active_members", [])
        if not members:
            return False, {}
        index = min(range(len(result.time)), key=lambda item: abs(result.time[item] - 60))
        later_peak = max(members[index:])
        return later_peak > members[index] * 1.02, {
            "at_campaign": members[index],
            "later_peak": later_peak,
        }
    series = result.variables.get("x" if expected == "chaotic_sign_changes" else "position", [])
    if not series:
        return False, {}
    start = len(series) // 10
    changes = _sign_changes(series[start:])
    if expected == "chaotic_sign_changes":
        return changes >= 2, {"sign_changes": changes}
    if expected == "two_wells":
        return changes >= 2 and min(series) < 0 and max(series) > 0, {
            "well_switches": changes
        }
    if expected == "limit_cycle":
        tail = series[max(0, len(series) * 4 // 5) :]
        return min(tail) < -1 and max(tail) > 1, {
            "tail_min": min(tail),
            "tail_max": max(tail),
        }
    raise ValueError(f"unknown expected behavior: {expected}")


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
                "finite": False,
                "full_horizon": False,
                "dynamic": False,
                "behavior_pass": False,
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
                    final_time=document.time.final_time,
                    time_step=document.time.time_step,
                    saveper=document.time.saveper,
                )
                result = simulate_model(document, parameters)
                case["executable"] = True
                case["repair_attempts"] = document.repair_attempts
                case["finite"] = all(
                    math.isfinite(value) for series in result.variables.values() for value in series
                )
                case["full_horizon"] = bool(result.time) and math.isclose(
                    result.time[-1], document.time.final_time, rel_tol=0, abs_tol=1e-9
                )
                stock_ids = {item.id for item in document.variables if item.kind == "stock"}
                case["dynamic"] = any(
                    len(series) > 1 and max(series) - min(series) > 1e-9
                    for name, series in result.variables.items()
                    if name in stock_ids
                )
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
                expected_pass, behavior_metrics = _expected_behavior(prompt, result)
                case["behavior_pass"] = (
                    case["semantic_pass"]
                    and case["finite"]
                    and case["full_horizon"]
                    and case["dynamic"]
                    and expected_pass
                )
                case["behavior_metrics"] = behavior_metrics
                case["actual_pattern"] = document.pattern_id
            except Exception as exc:
                case["repair_attempts"] = getattr(exc, "repair_attempts", 0)
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
        "finite_rate": sum(case["finite"] for case in cases) / total,
        "full_horizon_rate": sum(case["full_horizon"] for case in cases) / total,
        "dynamic_rate": sum(case["dynamic"] for case in cases) / total,
        "behavior_rate": sum(case["behavior_pass"] for case in cases) / total,
        "semantic_rate": sum(case["semantic_pass"] for case in cases) / total,
        "units_rate": sum(case["units_pass"] for case in cases) / total,
        "topology_rate": sum(case["topology_pass"] for case in cases) / total,
        "graph_rate": sum(case["graph_pass"] for case in cases) / total,
        "repair_rate": sum(case["repair_attempts"] > 0 for case in cases) / total,
        "average_duration_seconds": round(
            sum(case["duration_seconds"] for case in cases) / total, 3
        ),
        "targets": {
            "executable_rate": 0.9,
            "semantic_rate": 0.85,
            "behavior_rate": 0.85,
            "graph_rate": 1.0,
        },
        "results": cases,
    }
