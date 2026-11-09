from __future__ import annotations

import itertools
import math
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..codegen import load_pysd_model, runtime_name, runtime_variable_name, series_names
from ..exceptions import SimulationError
from ..schemas import ModelDocument, SimulationParameters, SimulationResult
from ..validation import ensure_valid_model
from .scipy_runner import EngineOutput, run_simulation


@dataclass
class TimeGrid:
    initial_time: float
    final_time: float
    time_step: float
    saveper: float
    output_times: list[float]


def _whole_steps(value: float, step: float, code: str) -> int:
    ratio = value / step
    rounded = round(ratio)
    if rounded < 1 or not math.isclose(ratio, rounded, rel_tol=1e-9, abs_tol=1e-9):
        raise SimulationError(f"{code}: {value} must be an integer multiple of {step}")
    return int(rounded)


def make_time_grid(document: ModelDocument, parameters: SimulationParameters) -> TimeGrid:
    initial = (
        parameters.initial_time
        if parameters.initial_time is not None
        else document.time.initial_time
    )
    final = parameters.final_time if parameters.final_time is not None else document.time.final_time
    step = parameters.time_step if parameters.time_step is not None else document.time.time_step
    saveper = parameters.saveper if parameters.saveper is not None else document.time.saveper
    if final <= initial:
        raise SimulationError("INVALID_TIME_GRID: final_time must be greater than initial_time")
    steps = _whole_steps(final - initial, step, "INVALID_TIME_GRID time_step")
    save_every = _whole_steps(saveper, step, "INVALID_TIME_GRID saveper")
    indices = list(range(0, steps + 1, save_every))
    if indices[-1] != steps:
        indices.append(steps)
    if len(indices) > 10000:
        raise SimulationError("INVALID_TIME_GRID: at most 10000 output points are allowed")
    times = [initial + index * step for index in indices]
    times[-1] = final
    return TimeGrid(initial, final, step, saveper, times)


def _pysd_element_value(value, indexers: dict[str, str]) -> float:
    if hasattr(value, "dims"):
        expanded = {
            **indexers,
            **{f"{name}!": element for name, element in indexers.items() if f"{name}!" in value.dims},
        }
        if expanded:
            value = value.sel(expanded)
    return float(value.item() if hasattr(value, "item") else value)


def _run_pysd(
    document: ModelDocument,
    parameters: SimulationParameters,
    grid: TimeGrid,
) -> EngineOutput:
    with tempfile.TemporaryDirectory(prefix="sdcloud_pysd_") as temporary:
        model = load_pysd_model(document, Path(temporary))
        names = {item.id: runtime_variable_name(item) for item in document.variables}
        stock_names = {item.id for item in document.variables if item.kind == "stock"}
        constant_names = {item.id for item in document.variables if item.kind == "constant"}
        component_params = {
            names[name]: value
            for name, value in parameters.parameters.items()
            if name in constant_names
        }
        initial_values = {
            names[name]: value
            for name, value in parameters.stock_initial.items()
            if name in stock_names
        }
        if parameters.input_series:
            import pandas as pd

            for name, series in parameters.input_series.items():
                component_params[names[name]] = pd.Series(
                    [point[1] for point in series.points],
                    index=[point[0] for point in series.points],
                )
        has_subscripts = any(item.subscripts for item in document.variables)
        frame = model.run(
            params=component_params or None,
            initial_condition=(grid.initial_time, initial_values),
            final_time=grid.final_time,
            time_step=grid.time_step,
            saveper=grid.time_step,
            return_timestamps=grid.output_times,
            return_columns=[runtime_name(item.label or item.id) for item in document.variables],
            flatten_output=not has_subscripts,
        )
        docs = model.doc.to_dict("records")
        real_by_python = {row["Py Name"]: row["Real Name"] for row in docs}
        columns = {real_by_python.get(str(column), str(column)): column for column in frame.columns}
        output = {"time": frame.index.astype(float).tolist()}
        if len(output["time"]) == len(grid.output_times) and all(
            math.isclose(actual, expected, rel_tol=0, abs_tol=5.1e-6)
            for actual, expected in zip(output["time"], grid.output_times, strict=True)
        ):
            output["time"] = grid.output_times.copy()
        dimensions = {item.id: item.elements for item in document.dimensions}
        for variable in document.variables:
            label = runtime_name(variable.label or variable.id)
            if label not in columns:
                raise SimulationError(f"PySD did not return variable {variable.id}")
            series = frame[columns[label]]
            if not variable.subscripts:
                output[variable.id] = series.astype(float).tolist()
                continue
            for elements in itertools.product(*(dimensions[name] for name in variable.subscripts)):
                suffix = ",".join(elements)
                indexers = dict(zip(variable.subscripts, elements, strict=True))
                output[f"{variable.id}[{suffix}]"] = [
                    _pysd_element_value(value, indexers) for value in series
                ]
        return EngineOutput(
            output["time"], {key: value for key, value in output.items() if key != "time"}, {}
        )


def _validate_overrides(document: ModelDocument, parameters: SimulationParameters) -> None:
    variables = {item.id: item for item in document.variables}
    unknown = set(parameters.parameters) - {
        name for name, item in variables.items() if item.kind == "constant"
    }
    if unknown:
        raise SimulationError(f"unknown or non-constant simulation parameters: {sorted(unknown)}")
    unknown_stocks = set(parameters.stock_initial) - {
        name for name, item in variables.items() if item.kind == "stock"
    }
    if unknown_stocks:
        raise SimulationError(f"unknown or non-stock initial values: {sorted(unknown_stocks)}")
    allowed_series = {
        name for name, item in variables.items() if item.kind == "constant" and item.exogenous
    }
    unknown_series = set(parameters.input_series) - allowed_series
    if unknown_series:
        raise SimulationError(f"input series require exogenous constants: {sorted(unknown_series)}")


def _validate_series_grid(parameters: SimulationParameters, grid: TimeGrid) -> None:
    for name, series in parameters.input_series.items():
        if series.extrapolation == "clamp":
            continue
        start = series.points[0][0]
        end = series.points[-1][0]
        if grid.initial_time < start or grid.final_time > end:
            raise SimulationError(
                f"external series {name} covers [{start}, {end}], not [{grid.initial_time}, {grid.final_time}]"
            )


def _validate_output(document: ModelDocument, output: EngineOutput, grid: TimeGrid) -> list[str]:
    if len(output.time) != len(grid.output_times):
        raise SimulationError("simulation returned a different output time grid")
    for actual, expected in zip(output.time, grid.output_times, strict=True):
        if not math.isclose(actual, expected, rel_tol=1e-8, abs_tol=1e-8):
            raise SimulationError("simulation returned a different output time grid")
    expected_names = set(series_names(document))
    if set(output.variables) != expected_names:
        raise SimulationError("simulation did not return every model variable")
    for name, values in output.variables.items():
        if len(values) != len(output.time):
            raise SimulationError(f"series {name} has a different length")
        if any(not math.isfinite(value) for value in values):
            raise SimulationError(f"series {name} contains non-finite values")
    warnings = []
    for stock in (item for item in document.variables if item.kind == "stock" and item.bounds):
        bounds = stock.bounds
        values = [
            value
            for name, series in output.variables.items()
            if name == stock.id or name.startswith(f"{stock.id}[")
            for value in series
        ]
        violations = []
        if bounds.min is not None:
            tolerance = max(1e-9, abs(bounds.min) * 1e-9)
            violations.extend(
                f"{value} < min {bounds.min}" for value in values if value < bounds.min - tolerance
            )
        if bounds.max is not None:
            tolerance = max(1e-9, abs(bounds.max) * 1e-9)
            violations.extend(
                f"{value} > max {bounds.max}" for value in values if value > bounds.max + tolerance
            )
        if not violations:
            continue
        message = (
            f"STOCK_BOUNDS_VIOLATION at variables.{stock.id}: {violations[0]}; "
            "use a smaller time_step or correct the flow policy"
        )
        if bounds.on_violation == "error":
            raise SimulationError(message)
        warnings.append(message)
    return warnings


def simulate_model(document: ModelDocument, parameters: SimulationParameters) -> SimulationResult:
    payload = document.model_dump() if isinstance(document, ModelDocument) else document
    document = ModelDocument.model_validate(payload)
    document = ensure_valid_model(document)
    _validate_overrides(document, parameters)
    grid = make_time_grid(document, parameters)
    _validate_series_grid(parameters, grid)
    method = parameters.integration_method
    supported = document.validation.capabilities.supported
    adaptive = method in {"rk45", "dop853", "lsoda", "bdf"}
    scipy_capability = "scipy_adaptive" if adaptive else "scipy_fixed"
    if parameters.engine == "pysd":
        if method != "euler" or not supported.get("pysd_euler", False):
            raise SimulationError("UNSUPPORTED_ENGINE: PySD supports only Euler for this model")
        engine = "pysd"
    elif parameters.engine == "scipy":
        if not supported.get(scipy_capability, False):
            reasons = document.validation.capabilities.reasons.get(scipy_capability, [])
            raise SimulationError(f"UNSUPPORTED_ENGINE: {'; '.join(reasons)}")
        engine = "scipy"
    elif method == "euler" and supported.get("pysd_euler", False):
        engine = "pysd"
    elif supported.get(scipy_capability, False):
        engine = "scipy"
    else:
        raise SimulationError(f"UNSUPPORTED_CAPABILITY: no engine supports {method} for this model")

    fallback_reason = None
    try:
        if engine == "pysd":
            output = _run_pysd(document, parameters, grid)
        else:
            output = run_simulation(
                document,
                parameters.parameters,
                parameters.stock_initial,
                initial_time=grid.initial_time,
                final_time=grid.final_time,
                time_step=grid.time_step,
                output_times=grid.output_times,
                integration_method=method,
                rtol=parameters.rtol,
                atol=parameters.atol,
                input_series=parameters.input_series,
            )
    except Exception as exc:
        if (
            engine != "pysd"
            or parameters.engine != "auto"
            or not supported.get("scipy_fixed", False)
        ):
            if isinstance(exc, SimulationError):
                raise
            raise SimulationError(f"PySD simulation failed: {type(exc).__name__}: {exc}") from exc
        try:
            output = run_simulation(
                document,
                parameters.parameters,
                parameters.stock_initial,
                initial_time=grid.initial_time,
                final_time=grid.final_time,
                time_step=grid.time_step,
                output_times=grid.output_times,
                integration_method="euler",
                rtol=parameters.rtol,
                atol=parameters.atol,
                input_series=parameters.input_series,
            )
            engine = "scipy"
            fallback_reason = f"{type(exc).__name__}: {exc}"[:1000]
        except Exception as scipy_error:
            raise SimulationError(
                f"PySD failed: {type(exc).__name__}: {exc}; SciPy failed: {type(scipy_error).__name__}: {scipy_error}"
            ) from scipy_error
    bound_warnings = _validate_output(document, output, grid)
    return SimulationResult(
        model_id=document.id,
        model_hash=document.model_hash(),
        time=output.time,
        variables=output.variables,
        requested_engine=parameters.engine,
        engine=engine,
        requested_method=method,
        integration_method=method,
        time_step=grid.time_step,
        saveper=grid.saveper,
        rtol=parameters.rtol if adaptive and engine == "scipy" else None,
        atol=parameters.atol if adaptive and engine == "scipy" else None,
        fallback_reason=fallback_reason,
        warnings=[
            item.message for item in document.validation.issues if item.severity == "warning"
        ]
        + bound_warnings,
        metadata={"points": len(output.time), **output.metadata},
    )
