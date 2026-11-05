from __future__ import annotations

import asyncio
import hashlib
import json
import math
import time
from pathlib import Path

from .generation import generate_model
from .io import write_json_atomic
from .llm import LLMClient
from .naming import identifier
from .schemas import GenerationRequest, SimulationParameters
from .semantics import semantic_issues
from .simulation import simulate_model

PROMPTS_PATH = Path(__file__).with_name("benchmark_prompts.json")


def load_prompts(path: Path | None = None) -> list[dict]:
    return json.loads((path or PROMPTS_PATH).read_text(encoding="utf-8"))


def _sign_changes(series: list[float]) -> int:
    return sum(
        left * right < 0 for left, right in zip(series, series[1:], strict=False)
    )


def _requires_dynamic(prompt: dict) -> bool:
    expected = prompt.get("expected_behavior")
    return not isinstance(expected, dict) or expected.get("kind") != "steady_state"


def _custom_behavior(expected: dict, result) -> tuple[bool, dict]:
    kind = expected.get("kind")
    if kind == "conservation":
        names = expected.get("variables", [])
        if not names or any(name not in result.variables for name in names):
            return False, {"missing_variables": names}
        totals = [
            sum(result.variables[name][index] for name in names)
            for index in range(len(result.time))
        ]
        drift = max(totals) - min(totals)
        tolerance = expected.get("tolerance", 1e-6)
        return drift <= tolerance, {"drift": drift, "tolerance": tolerance}

    variable = expected.get("variable")
    series = result.variables.get(variable, [])
    if not series:
        return False, {"missing_variable": variable}
    if kind == "steady_state":
        target = expected["value"]
        tolerance = expected.get("tolerance", 1e-6)
        deviation = max(abs(value - target) for value in series[max(0, len(series) * 9 // 10) :])
        nonnegative = not expected.get("nonnegative", False) or min(series) >= 0
        return deviation <= tolerance and nonnegative, {
            "final": series[-1],
            "target": target,
            "max_deviation": deviation,
            "min": min(series),
            "nonnegative": nonnegative,
        }
    if kind == "analytic_exponential":
        initial = expected["initial"]
        final_time = expected.get("time", result.time[-1])
        target = initial * math.exp(expected["rate"] * final_time)
        tolerance = expected.get("tolerance", 0.05)
        error = abs(series[-1] - target)
        return error <= tolerance * max(1, abs(target)), {
            "expected": target,
            "actual": series[-1],
            "absolute_error": error,
            "tolerance": tolerance,
        }
    if kind == "monotonic":
        direction = expected.get("direction", "increasing")
        if direction == "increasing":
            passed = all(right >= left - 1e-9 for left, right in zip(series, series[1:], strict=False))
        elif direction == "decreasing":
            passed = all(right <= left + 1e-9 for left, right in zip(series, series[1:], strict=False))
        else:
            raise ValueError(f"unknown monotonic direction: {direction}")
        return passed, {"initial": series[0], "final": series[-1], "direction": direction}
    if kind == "sign_changes":
        changes = _sign_changes(series[len(series) // 10 :])
        minimum = expected.get("minimum", 2)
        return changes >= minimum, {"sign_changes": changes, "minimum": minimum}
    if kind == "cascade":
        peak_index = max(range(len(series)), key=series.__getitem__)
        after = expected.get("after", 0)
        peak = series[peak_index]
        return peak > series[0] and result.time[peak_index] >= after, {
            "initial": series[0],
            "peak": peak,
            "peak_time": result.time[peak_index],
            "after": after,
        }
    if kind == "delayed_response":
        at = expected["at"]
        index = min(range(len(result.time)), key=lambda item: abs(result.time[item] - at))
        early_peak = max(series[:index], default=series[0])
        later_peak = max(series[index:], default=series[index])
        before_max = expected.get("before_max", math.inf)
        after_min = expected.get("after_min", -math.inf)
        return early_peak <= before_max and later_peak >= after_min, {
            "early_peak": early_peak,
            "later_peak": later_peak,
            "before_max": before_max,
            "after_min": after_min,
        }
    if kind == "event_change":
        at = expected["at"]
        before_index = min(range(len(result.time)), key=lambda item: abs(result.time[item] - at))
        after_index = min(
            range(len(result.time)),
            key=lambda item: abs(result.time[item] - expected.get("after", result.time[-1])),
        )
        before = series[before_index]
        after = series[after_index]
        tolerance = expected.get("tolerance", 1e-9)
        relation = expected.get("relation", "decrease")
        if relation == "decrease":
            passed = after < before - tolerance
        elif relation == "increase":
            passed = after > before + tolerance
        elif relation == "above":
            passed = after > expected["value"]
        elif relation == "below":
            passed = after < expected["value"]
        else:
            raise ValueError(f"unknown event relation: {relation}")
        return passed, {"before": before, "after": after, "relation": relation}
    if kind == "range":
        lower = expected.get("min", -math.inf)
        upper = expected.get("max", math.inf)
        return min(series) >= lower and max(series) <= upper, {
            "min": min(series),
            "max": max(series),
            "expected_min": lower,
            "expected_max": upper,
        }
    raise ValueError(f"unknown expected behavior kind: {kind}")


def _expected_behavior(
    prompt: dict, result, stock_ids: set[str] | None = None
) -> tuple[bool, dict]:
    expected = prompt.get("expected_behavior")
    if expected is None:
        return True, {}
    if isinstance(expected, dict):
        aliases = expected.get("aliases", [])
        if stock_ids is not None and len(stock_ids) == 1:
            aliases = [*aliases, *stock_ids]
        expected_name = expected.get("variable")
        if expected_name and expected_name not in result.variables:
            candidates = {
                name
                for name in (stock_ids if stock_ids is not None else result.variables)
                if name == f"{expected_name}s"
                or name.startswith(f"{expected_name}_")
                or name.endswith(f"_{expected_name}")
            }
            if len(candidates) == 1:
                aliases = [*aliases, *candidates]
        if not isinstance(aliases, list):
            raise ValueError("behavior aliases must be a list")
        resolved = next(
            (
                name
                for name in (expected.get("variable"), *aliases)
                if name in result.variables
            ),
            expected.get("variable"),
        )
        if resolved != expected.get("variable"):
            passed, metrics = _custom_behavior({**expected, "variable": resolved}, result)
            return passed, {**metrics, "resolved_variable": resolved}
        return _custom_behavior(expected, result)
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
    prompts_path: Path | None = None,
    artifacts_dir: Path | None = None,
    max_repairs: int = 2,
    concurrency: int = 1,
) -> dict:
    if not 1 <= concurrency <= 8:
        raise ValueError("concurrency must be between 1 and 8")
    corpus_path = prompts_path or PROMPTS_PATH
    prompts = load_prompts(corpus_path)
    source_hash = hashlib.sha256()
    source_root = Path(__file__).parent
    for path in sorted(source_root.rglob("*.py")):
        source_hash.update(path.relative_to(source_root).as_posix().encode())
        source_hash.update(b"\0")
        source_hash.update(path.read_bytes())
    if prompt_ids:
        allowed = set(prompt_ids)
        prompts = [item for item in prompts if item["id"] in allowed]
    if not prompts:
        raise ValueError("benchmark has no prompts to run")
    semaphore = asyncio.Semaphore(concurrency)

    async def run_case(prompt: dict, run: int) -> dict:
        async with semaphore:
            started = time.monotonic()
            workdir = (
                artifacts_dir / f"{identifier(prompt['id'])}-run-{run + 1}"
                if artifacts_dir is not None
                else None
            )
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
            if workdir is not None:
                workdir.mkdir(parents=True, exist_ok=True)
                for path in workdir.glob("*.json"):
                    path.unlink()
                write_json_atomic(workdir / "prompt.json", prompt)
                case["artifacts"] = str(workdir)
            try:
                document = await generate_model(
                    GenerationRequest(description=prompt["description"]),
                    llm,
                    workdir=workdir,
                    max_repairs=max_repairs,
                )
                parameters = SimulationParameters(
                    initial_time=document.time.initial_time,
                    final_time=document.time.final_time,
                    time_step=document.time.time_step,
                    saveper=document.time.saveper,
                )
                result = simulate_model(document, parameters)
                if workdir is not None:
                    write_json_atomic(workdir / "model.json", document.model_dump(mode="json"))
                    write_json_atomic(workdir / "simulation.json", result.model_dump(mode="json"))
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
                expected_pass, behavior_metrics = _expected_behavior(prompt, result, stock_ids)
                case["behavior_pass"] = (
                    case["semantic_pass"]
                    and case["finite"]
                    and case["full_horizon"]
                    and (case["dynamic"] or not _requires_dynamic(prompt))
                    and expected_pass
                )
                case["behavior_metrics"] = behavior_metrics
                case["actual_pattern"] = document.pattern_id
            except Exception as exc:
                case["repair_attempts"] = getattr(exc, "repair_attempts", 0)
                case["error"] = str(exc)[:2000]
                if workdir is not None:
                    write_json_atomic(
                        workdir / "error.json",
                        {"type": type(exc).__name__, "error": case["error"]},
                    )
            finally:
                case["duration_seconds"] = round(time.monotonic() - started, 3)
                if workdir is not None:
                    write_json_atomic(workdir / "case.json", case)
            return case

    jobs = [(prompt, run) for prompt in prompts for run in range(runs)]
    cases = await asyncio.gather(*(run_case(prompt, run) for prompt, run in jobs))
    total = len(cases)
    return {
        "schema_version": "2.0",
        "kind": "llm_benchmark",
        "max_repairs": max_repairs,
        "concurrency": concurrency,
        "corpus_sha256": hashlib.sha256(corpus_path.read_bytes()).hexdigest(),
        "pipeline_sha256": source_hash.hexdigest(),
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
