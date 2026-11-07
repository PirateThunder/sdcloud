from __future__ import annotations

import csv
import itertools
import math
import subprocess
from pathlib import Path

from .formats import import_model
from .schemas import SimulationParameters
from .simulation import simulate_model


def _label(value: str) -> str:
    return " ".join(value.strip().strip('"').split())


def _reference(path: Path) -> dict[str, list[tuple[float, float]]]:
    delimiter = "\t" if path.suffix == ".tab" else ","
    with path.open(encoding="utf-8-sig", newline="") as source:
        rows = [row for row in csv.reader(source, delimiter=delimiter) if row]
    if len(rows) < 2:
        raise ValueError("reference output has no data rows")
    headers = [_label(item) for item in rows[0]]
    time_index = next((index for index, name in enumerate(headers) if name.lower() == "time"), None)
    if time_index is None:
        raise ValueError("reference output has no Time column")
    result = {name: [] for index, name in enumerate(headers) if index != time_index and name}
    for row in rows[1:]:
        if len(row) > len(headers):
            raise ValueError("reference output has more values than headers")
        row = [*row, *([""] * (len(headers) - len(row)))]
        timestamp = float(row[time_index])
        for index, name in enumerate(headers):
            if index != time_index and name and row[index].strip():
                result[name].append((timestamp, float(row[index])))
    return result


def _at(series: list[float], times: list[float], timestamp: float) -> float | None:
    if timestamp < times[0] - 1e-9 or timestamp > times[-1] + 1e-9:
        return None
    for index, actual_time in enumerate(times):
        if math.isclose(actual_time, timestamp, rel_tol=0, abs_tol=5.1e-5):
            return series[index]
        if actual_time > timestamp:
            if index == 0:
                return None
            fraction = (timestamp - times[index - 1]) / (actual_time - times[index - 1])
            return series[index - 1] + fraction * (series[index] - series[index - 1])
    return series[-1]


def _compare(document, result, reference: dict, rtol: float, atol: float) -> dict:
    missing = []
    maximum_absolute = 0.0
    maximum_relative = 0.0
    compared_variables = 0
    compared_points = 0
    failed_points = 0
    comparable = [item for item in document.variables if item.kind == "stock"]
    stocks_only = bool(comparable)
    if not comparable:
        comparable = [item for item in document.variables if item.kind in {"auxiliary", "constant"}]
    dimensions = {item.id: item.elements for item in document.dimensions}
    series = []
    for variable in comparable:
        label = _label(variable.label or variable.id)
        if not stocks_only and not any(
            name == label or name.startswith(f"{label}[") for name in reference
        ):
            continue
        if not variable.subscripts:
            series.append((label, result.variables[variable.id]))
            continue
        for elements in itertools.product(*(dimensions[name] for name in variable.subscripts)):
            suffix = ",".join(elements)
            series.append((f"{label}[{suffix}]", result.variables[f"{variable.id}[{suffix}]"]))
    for label, values in series:
        expected = reference.get(label)
        if not expected:
            missing.append(label)
            continue
        compared_variables += 1
        for timestamp, expected_value in expected:
            actual = _at(values, result.time, timestamp)
            if actual is None:
                failed_points += 1
                continue
            absolute = abs(actual - expected_value)
            relative = absolute / max(abs(expected_value), 1e-12)
            maximum_absolute = max(maximum_absolute, absolute)
            maximum_relative = max(maximum_relative, relative)
            compared_points += 1
            if absolute > atol + rtol * abs(expected_value):
                failed_points += 1
    passed = (
        not missing
        and compared_variables > 0
        and compared_points > 0
        and failed_points == 0
    )
    return {
        "comparison_pass": passed,
        "compared_variables": compared_variables,
        "compared_points": compared_points,
        "failed_points": failed_points,
        "missing_variables": missing,
        "max_absolute_error": maximum_absolute,
        "max_relative_error": maximum_relative,
    }


def _source_commit(root: Path) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def run_external_benchmark(
    root: Path,
    *,
    extension: str = ".mdl",
    cases: list[str] | None = None,
    limit: int | None = None,
    rtol: float = 1e-3,
    atol: float = 1e-5,
) -> dict:
    if extension not in {".mdl", ".xmile"}:
        raise ValueError("external corpus extension must be .mdl or .xmile")
    if limit is not None and limit < 1:
        raise ValueError("external corpus limit must be positive")
    if rtol < 0 or atol < 0:
        raise ValueError("external corpus tolerances must be nonnegative")
    paths = sorted(path for path in root.rglob(f"*{extension}") if path.is_file())
    if cases:
        allowed = set(cases)
        paths = [
            path
            for path in paths
            if path.parent.name in allowed
            or path.stem in allowed
            or path.relative_to(root).as_posix() in allowed
        ]
    if limit is not None:
        paths = paths[:limit]
    results = []
    for path in paths:
        relative = path.relative_to(root).as_posix()
        case = {
            "id": relative.removesuffix(extension),
            "model": relative,
            "imported": False,
            "simulated": False,
            "comparison_pass": False,
        }
        results.append(case)
        reference_names = ("output.tab", "output.csv") if extension == ".mdl" else ("output.csv", "output.tab")
        reference_path = next(
            (path.parent / name for name in reference_names if (path.parent / name).is_file()),
            None,
        )
        if reference_path is None:
            case["stage"] = "no_reference"
            case["error"] = "No output.tab or output.csv reference"
            continue
        case["reference"] = reference_path.name
        try:
            document = import_model(
                path.read_text(encoding="utf-8-sig"),
                "vensim" if extension == ".mdl" else "xmile",
                source_name=path.name,
            )
            case["imported"] = True
        except Exception as exc:
            case["stage"] = "import"
            case["error"] = f"{type(exc).__name__}: {exc}"[:2000]
            continue
        try:
            result = simulate_model(
                document,
                SimulationParameters(
                    initial_time=document.time.initial_time,
                    final_time=document.time.final_time,
                    time_step=document.time.time_step,
                    saveper=document.time.saveper,
                    integration_method="euler",
                ),
            )
            case["simulated"] = True
        except Exception as exc:
            case["stage"] = "simulation"
            case["error"] = f"{type(exc).__name__}: {exc}"[:2000]
            continue
        try:
            reference = _reference(reference_path)
            case.update(_compare(document, result, reference, rtol, atol))
            case["stage"] = "comparison" if not case["comparison_pass"] else "done"
        except Exception as exc:
            case["stage"] = "reference"
            case["error"] = f"{type(exc).__name__}: {exc}"[:2000]
    with_reference = [item for item in results if "reference" in item]
    imported = [item for item in with_reference if item["imported"]]
    simulated = [item for item in imported if item["simulated"]]
    matched = [item for item in simulated if item["comparison_pass"]]

    def rate(numerator: int, denominator: int) -> float:
        return numerator / denominator if denominator else 0.0

    return {
        "schema_version": "2.0",
        "kind": "external_model_benchmark",
        "source_root": str(root),
        "source_commit": _source_commit(root),
        "extension": extension,
        "rtol": rtol,
        "atol": atol,
        "total_models": len(results),
        "reference_models": len(with_reference),
        "imported": len(imported),
        "simulated": len(simulated),
        "matched": len(matched),
        "import_rate": rate(len(imported), len(with_reference)),
        "simulation_rate": rate(len(simulated), len(with_reference)),
        "match_rate": rate(len(matched), len(with_reference)),
        "results": results,
    }
