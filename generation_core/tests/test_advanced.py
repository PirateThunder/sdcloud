import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from pipeline.analysis_schemas import (
    CalibrationRequest,
    CalibrationTarget,
    SamplingTarget,
    Scenario,
    ScenarioRunRequest,
    SensitivityRequest,
)
from pipeline.calibration import calibration_csv, run_calibration
from pipeline.exceptions import ModelValidationError, SimulationError
from pipeline.formats import export_xmile
from pipeline.ir import binary, call, lit, ref
from pipeline.scenarios import comparison_csv, run_scenarios, run_sensitivity
from pipeline.schemas import (
    ArrayExpression,
    AuxiliaryVariable,
    ConstantVariable,
    Dimension,
    Expression,
    FlowEndpoint,
    FlowVariable,
    ModelDocument,
    SimulationParameters,
    StockVariable,
    TimeSeries,
    TimeSettings,
)
from pipeline.simulation import simulate_model
from pipeline.validation import finalize_model, validate_model
from tests.advanced_helpers import array_model
from tests.helpers import exponential_model

ROOT = Path(__file__).resolve().parent.parent


def test_subscripts_numeric_and_capabilities():
    result = simulate_model(array_model(), SimulationParameters())
    assert result.engine == "pysd"
    assert result.variables["population[North]"][0] == 100
    assert result.variables["population[South]"][0] == 200
    assert result.variables["total_population"][0] == 300
    assert result.variables["north_population"] == result.variables["population[North]"]
    with pytest.raises(SimulationError, match="UNSUPPORTED_ENGINE"):
        simulate_model(array_model(), SimulationParameters(engine="scipy"))
    with pytest.raises(ModelValidationError, match="UNSUPPORTED_CAPABILITY"):
        export_xmile(array_model())


def test_array_shape_validation():
    document = array_model()
    variables = [item.model_dump() for item in document.variables]
    variables[2]["expression"]["shape"] = [3]
    document = ModelDocument.model_validate(document.model_dump() | {"variables": variables})
    report = validate_model(document)
    assert any(item.code == "ARRAY_SHAPE_MISMATCH" for item in report.issues)


def test_multidimensional_array():
    document = finalize_model(
        ModelDocument(
            description="Two dimensional population",
            time=TimeSettings(unit="year", final_time=1, time_step=0.25, saveper=0.25),
            dimensions=[
                Dimension(id="region", elements=["North", "South"]),
                Dimension(id="age", elements=["Young", "Old"]),
            ],
            variables=[
                StockVariable(
                    id="population",
                    kind="stock",
                    subscripts=["region", "age"],
                    initial=ArrayExpression(
                        op="array",
                        values=[lit(100), lit(200), lit(300), lit(400)],
                        shape=[2, 2],
                    ),
                    units={"person": 1},
                ),
                FlowVariable(
                    id="births",
                    kind="flow",
                    subscripts=["region", "age"],
                    expression=binary("mul", ref("population"), ref("rate")),
                    source=FlowEndpoint(kind="cloud", id="births_source"),
                    target=FlowEndpoint(kind="stock", id="population"),
                    units={"person": 1, "year": -1},
                ),
                ConstantVariable(
                    id="rate", kind="constant", expression=lit(0.1), units={"year": -1}
                ),
                AuxiliaryVariable(
                    id="total_population",
                    kind="auxiliary",
                    expression=call("sum", ref("population")),
                    units={"person": 1},
                ),
            ],
        )
    )
    result = simulate_model(document, SimulationParameters())
    assert result.variables["population[North,Young]"][0] == 100
    assert result.variables["population[North,Old]"][0] == 200
    assert result.variables["population[South,Young]"][0] == 300
    assert result.variables["population[South,Old]"][0] == 400
    assert result.variables["total_population"][0] == 1000


def test_external_series_matches_engines_and_validates_bounds():
    document = exponential_model()
    variables = [
        item.model_copy(update={"exogenous": True}) if item.id == "growth_rate" else item
        for item in document.variables
    ]
    document = document.model_copy(update={"variables": variables})
    series = TimeSeries(points=[(0, 0.1), (1, 0.2)])
    results = []
    for engine in ("pysd", "scipy"):
        result = simulate_model(
            document,
            SimulationParameters(
                engine=engine, final_time=1, time_step=0.25, input_series={"growth_rate": series}
            ),
        )
        results.append(result)
        assert result.variables["growth_rate"] == pytest.approx([0.1, 0.125, 0.15, 0.175, 0.2])
    assert results[0].variables["population"] == pytest.approx(results[1].variables["population"])
    with pytest.raises(SimulationError, match="covers"):
        simulate_model(
            document,
            SimulationParameters(
                final_time=2, time_step=0.25, input_series={"growth_rate": series}
            ),
        )
    with pytest.raises(SimulationError, match="exogenous"):
        simulate_model(
            exponential_model(),
            SimulationParameters(
                final_time=1, time_step=0.25, input_series={"growth_rate": series}
            ),
        )


def test_scenarios_and_partial_failure():
    result = run_scenarios(
        ScenarioRunRequest(
            model=exponential_model(),
            parameters=SimulationParameters(final_time=1, time_step=0.25),
            scenarios=[
                Scenario(name="base"),
                Scenario(name="high", parameters={"growth_rate": 0.2}),
                Scenario(name="invalid", parameters={"unknown": 1}),
            ],
            failure_policy="keep_partial",
        )
    )
    assert result.status == "partial"
    assert (
        result.runs[1].result.variables["population"][-1]
        > result.runs[0].result.variables["population"][-1]
    )
    assert result.runs[2].status == "error"
    assert comparison_csv(result).splitlines()[0] == "scenario,time,population,growth,growth_rate"


def test_sensitivity_is_reproducible():
    request = SensitivityRequest(
        model=exponential_model(),
        parameters=SimulationParameters(final_time=1, time_step=0.25),
        runs=10,
        seed=99,
        targets=[SamplingTarget(name="growth_rate", distribution="uniform", low=0.05, high=0.2)],
    )
    first = run_sensitivity(request)
    second = run_sensitivity(request)
    assert first.config_hash == second.config_hash
    assert first.summary == second.summary
    assert first.successful_runs == 10
    assert first.failed_runs == 0
    other = run_sensitivity(request.model_copy(update={"seed": 100}))
    assert other.config_hash != first.config_hash


def test_calibration_recovers_parameter_and_creates_revision():
    model = exponential_model()
    parameters = SimulationParameters(final_time=1, time_step=0.25)
    baseline = simulate_model(model, parameters)
    times = [0, 0.5, 1]
    observations = {
        "population": [
            baseline.variables["population"][baseline.time.index(value)] for value in times
        ]
    }
    result = run_calibration(
        CalibrationRequest(
            model=model,
            parameters=parameters,
            targets=[CalibrationTarget(name="growth_rate", initial=0.2, low=0.01, high=0.5)],
            time=times,
            observations=observations,
        )
    )
    assert result.success
    assert result.fitted_parameters["growth_rate"] == pytest.approx(0.1, abs=1e-7)
    assert result.metrics["rmse"] < 1e-7
    assert result.fitted_model.provenance.kind == "calibration"
    assert result.fitted_model.model_hash() != model.model_hash()
    assert calibration_csv(result).splitlines()[2].startswith("population,0.5,105.0625,105.0625")


def test_unicode_labels_use_pysd_without_fallback():
    document = exponential_model()
    labels = {"population": "Кролики", "growth": "Рождаемость", "growth_rate": "Коэффициент"}
    variables = [item.model_copy(update={"label": labels[item.id]}) for item in document.variables]
    document = document.model_copy(update={"variables": variables})
    result = simulate_model(document, SimulationParameters(final_time=1, time_step=0.25))
    assert result.engine == "pysd"
    assert result.fallback_reason is None


def test_nary_multiplication_is_normalized():
    expression = TypeAdapter(Expression).validate_python(
        {
            "op": "mul",
            "args": [
                {"op": "ref", "name": "a"},
                {"op": "ref", "name": "b"},
                {"op": "ref", "name": "c"},
            ],
        }
    )
    assert expression.op == "mul"
    assert expression.args[0].op == "mul"


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, *args], cwd=ROOT, capture_output=True, text=True, timeout=120, check=False
    )


def test_analysis_cli(tmp_path):
    model_path = tmp_path / "model.json"
    model_path.write_text(json.dumps(exponential_model().model_dump(mode="json")), encoding="utf-8")
    scenarios_path = tmp_path / "scenarios.json"
    scenarios_path.write_text(
        json.dumps(
            {"parameters": {"final_time": 1, "time_step": 0.25}, "scenarios": [{"name": "base"}]}
        ),
        encoding="utf-8",
    )
    result = run_cli(
        str(ROOT / "scenarios.py"),
        "--model",
        str(model_path),
        "--scenarios",
        str(scenarios_path),
        "--output",
        str(tmp_path / "scenario_result.json"),
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "comparison.csv").is_file()

    sensitivity_path = tmp_path / "sensitivity_input.json"
    sensitivity_path.write_text(
        json.dumps(
            {
                "parameters": {"final_time": 1, "time_step": 0.25},
                "runs": 3,
                "seed": 1,
                "targets": [
                    {"name": "growth_rate", "distribution": "uniform", "low": 0.05, "high": 0.2}
                ],
            }
        ),
        encoding="utf-8",
    )
    result = run_cli(
        str(ROOT / "sensitivity.py"),
        "--model",
        str(model_path),
        "--config",
        str(sensitivity_path),
        "--output",
        str(tmp_path / "sensitivity_result.json"),
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "sensitivity_result.csv").is_file()

    calibration_path = tmp_path / "observations.json"
    calibration_path.write_text(
        json.dumps(
            {
                "parameters": {"final_time": 1, "time_step": 0.25},
                "targets": [{"name": "growth_rate", "initial": 0.2, "low": 0.01, "high": 0.5}],
                "time": [0, 0.5, 1],
                "observations": {"population": [100, 105.0625, 110.3812890625]},
            }
        ),
        encoding="utf-8",
    )
    result = run_cli(
        str(ROOT / "calibrate.py"),
        "--model",
        str(model_path),
        "--observations",
        str(calibration_path),
        "--output",
        str(tmp_path / "calibration_result.json"),
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "fitted_model.json").is_file()
    assert (tmp_path / "calibration_result.csv").is_file()
