from __future__ import annotations

import csv
import io

import numpy as np
from scipy.optimize import least_squares

from .analysis_schemas import CalibrationRequest, CalibrationResult
from .exceptions import SimulationError
from .ir import lit
from .schemas import Provenance
from .simulation import simulate_model
from .validation import finalize_model


def run_calibration(request: CalibrationRequest) -> CalibrationResult:
    variables = {item.id: item for item in request.model.variables}
    constants = {name for name, item in variables.items() if item.kind == "constant"}
    unknown = {target.name for target in request.targets} - constants
    if unknown:
        raise SimulationError(f"calibration targets must be constants: {sorted(unknown)}")
    unknown_series = set(request.observations) - set(variables)
    if unknown_series:
        raise SimulationError(f"unknown observation variables: {sorted(unknown_series)}")
    for name in request.weights:
        if name not in request.observations or request.weights[name] <= 0:
            raise SimulationError("calibration weights must be positive and match observations")
    targets = request.targets
    names = [target.name for target in targets]
    observed_names = list(request.observations)

    def residual(values: np.ndarray) -> np.ndarray:
        overrides = dict(zip(names, values, strict=True))
        parameters = request.parameters.model_copy(update={"parameters": overrides})
        try:
            result = simulate_model(request.model, parameters)
            residuals = []
            for name in observed_names:
                prediction = np.interp(request.time, result.time, result.variables[name])
                weight = request.weights.get(name, 1.0)
                residuals.extend((prediction - np.asarray(request.observations[name])) * weight)
            return np.asarray(residuals, dtype=float)
        except Exception:
            return np.full(len(request.time) * len(observed_names), 1e9)

    solution = least_squares(
        residual,
        np.asarray([target.initial for target in targets]),
        bounds=(
            np.asarray([target.low for target in targets]),
            np.asarray([target.high for target in targets]),
        ),
        max_nfev=200,
    )
    fitted = dict(zip(names, solution.x.tolist(), strict=True))
    parameters = request.parameters.model_copy(update={"parameters": fitted})
    result = simulate_model(request.model, parameters)
    predictions = {}
    residuals = {}
    metrics = {"variables": {}}
    all_residuals = []
    for name in observed_names:
        prediction = np.interp(request.time, result.time, result.variables[name]).tolist()
        residual_values = (np.asarray(prediction) - np.asarray(request.observations[name])).tolist()
        predictions[name] = prediction
        residuals[name] = residual_values
        rmse = float(np.sqrt(np.mean(np.square(residual_values))))
        mae = float(np.mean(np.abs(residual_values)))
        metrics["variables"][name] = {"rmse": rmse, "mae": mae}
        all_residuals.extend(residual_values)
    metrics["rmse"] = float(np.sqrt(np.mean(np.square(all_residuals))))
    metrics["mae"] = float(np.mean(np.abs(all_residuals)))
    metrics["observations"] = len(all_residuals)

    variables_fitted = []
    for variable in request.model.variables:
        if variable.id in fitted and variable.kind == "constant":
            variables_fitted.append(
                variable.model_copy(update={"expression": lit(fitted[variable.id])})
            )
        else:
            variables_fitted.append(variable)
    fitted_model = finalize_model(
        request.model.model_copy(
            update={
                "variables": variables_fitted,
                "provenance": Provenance(
                    kind="calibration",
                    source_name=request.model.name,
                    source_sha256=request.model.model_hash(),
                ),
            }
        )
    )
    return CalibrationResult(
        status="done" if solution.success else "error",
        fitted_parameters=fitted,
        time=request.time,
        observations=request.observations,
        predictions=predictions,
        residuals=residuals,
        metrics=metrics,
        success=bool(solution.success),
        message=str(solution.message),
        evaluations=int(solution.nfev),
        fitted_model=fitted_model,
    )


def calibration_csv(result: CalibrationResult) -> str:
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["variable", "time", "observed", "predicted", "residual"])
    for name, predicted in result.predictions.items():
        residual = result.residuals[name]
        observed = result.observations[name]
        for index, value in enumerate(predicted):
            writer.writerow([name, result.time[index], observed[index], value, residual[index]])
    return output.getvalue()
