from __future__ import annotations

import csv
import hashlib
import io
import json

import numpy as np

from .analysis_schemas import (
    Scenario,
    ScenarioRun,
    ScenarioRunRequest,
    ScenarioRunResult,
    SensitivityRequest,
    SensitivityResult,
)
from .exceptions import SimulationError
from .simulation import simulate_model


def run_scenarios(request: ScenarioRunRequest) -> ScenarioRunResult:
    runs = []
    for scenario in request.scenarios:
        parameters = request.parameters.model_copy(
            update={
                "parameters": scenario.parameters,
                "stock_initial": scenario.stock_initial,
                "input_series": scenario.input_series,
            }
        )
        try:
            result = simulate_model(request.model, parameters)
            runs.append(ScenarioRun(name=scenario.name, status="done", result=result))
        except Exception as exc:
            if request.failure_policy == "fail_fast":
                raise SimulationError(f"scenario {scenario.name} failed: {exc}") from exc
            runs.append(ScenarioRun(name=scenario.name, status="error", error=str(exc)[:2000]))
    successful = sum(run.status == "done" for run in runs)
    status = "done" if successful == len(runs) else "partial" if successful else "error"
    return ScenarioRunResult(model_hash=request.model.model_hash(), status=status, runs=runs)


def comparison_csv(result: ScenarioRunResult) -> str:
    successful = [run for run in result.runs if run.result is not None]
    if not successful:
        raise SimulationError("no successful scenario runs to compare")
    expected_time = successful[0].result.time
    variables = list(successful[0].result.variables)
    for run in successful[1:]:
        if run.result.time != expected_time or list(run.result.variables) != variables:
            raise SimulationError("scenario results have incompatible time grids or variables")
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["scenario", "time", *variables])
    for run in successful:
        for index, value in enumerate(run.result.time):
            writer.writerow(
                [run.name, value, *[run.result.variables[name][index] for name in variables]]
            )
    return output.getvalue()


def _sample(target, rng: np.random.Generator):
    if target.distribution == "uniform":
        return float(rng.uniform(target.low, target.high))
    if target.distribution == "normal":
        return float(rng.normal(target.mean, target.std))
    if target.distribution == "lognormal":
        return float(rng.lognormal(target.mean, target.std))
    probabilities = None
    if target.probabilities is not None:
        total = sum(target.probabilities)
        probabilities = np.asarray(target.probabilities) / total
    return float(rng.choice(target.values, p=probabilities))


def run_sensitivity(request: SensitivityRequest) -> SensitivityResult:
    rng = np.random.default_rng(request.seed)
    scenarios = []
    for index in range(request.runs):
        parameters = {target.name: _sample(target, rng) for target in request.targets}
        scenarios.append(Scenario(name=f"sample_{index + 1:04d}", parameters=parameters))
    batch = run_scenarios(
        ScenarioRunRequest(
            model=request.model,
            parameters=request.parameters,
            scenarios=scenarios,
            failure_policy=request.failure_policy,
        )
    )
    successful = [run.result for run in batch.runs if run.result is not None]
    if not successful:
        raise SimulationError("all sensitivity runs failed")
    time = successful[0].time
    variables = successful[0].variables
    summary = {}
    for name in variables:
        data = np.asarray([result.variables[name] for result in successful], dtype=float)
        summary[name] = {
            "time": time,
            "mean": np.mean(data, axis=0).tolist(),
            "std": np.std(data, axis=0).tolist(),
            "quantiles": {
                str(quantile): np.quantile(data, quantile, axis=0).tolist()
                for quantile in request.quantiles
            },
        }
    config = {
        "model_hash": request.model.model_hash(),
        "seed": request.seed,
        "runs": request.runs,
        "targets": [target.model_dump(mode="json") for target in request.targets],
        "quantiles": request.quantiles,
    }
    config_hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    return SensitivityResult(
        model_hash=request.model.model_hash(),
        config_hash=config_hash,
        seed=request.seed,
        status=batch.status,
        successful_runs=len(successful),
        failed_runs=len(batch.runs) - len(successful),
        summary=summary,
        failures=[run for run in batch.runs if run.status == "error"],
    )


def sensitivity_csv(result: SensitivityResult) -> str:
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    quantiles = sorted(
        {key for item in result.summary.values() for key in item["quantiles"]}, key=float
    )
    writer.writerow(["variable", "time", "mean", "std", *[f"q_{value}" for value in quantiles]])
    for name, item in result.summary.items():
        for index, value in enumerate(item["time"]):
            writer.writerow(
                [
                    name,
                    value,
                    item["mean"][index],
                    item["std"][index],
                    *[item["quantiles"][quantile][index] for quantile in quantiles],
                ]
            )
    return output.getvalue()
