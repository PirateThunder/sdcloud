import json
from pathlib import Path

from pipeline.external_benchmark import run_external_benchmark
from pipeline.formats import import_vensim
from pipeline.schemas import SimulationParameters
from pipeline.simulation import simulate_model

MODELS = Path(__file__).parent / "fixtures" / "models"


def write_case(root: Path, name: str, model: str, reference: str) -> None:
    case = root / name
    case.mkdir(parents=True)
    (case / "model.mdl").write_text(model)
    (case / "output.tab").write_text(reference)


def test_external_benchmark_imports_simulates_and_compares_reference(tmp_path):
    source = (MODELS / "teacup.mdl").read_text()
    document = import_vensim(source)
    result = simulate_model(document, SimulationParameters())
    reference = (
        "Time\tOptional Control\tTeacup Temperature\n"
        f"0\t\t{result.variables['teacup_temperature'][0]}\n"
        f"30\t\t{result.variables['teacup_temperature'][-1]}\n"
    )
    write_case(tmp_path, "cooling", source, reference)
    report = run_external_benchmark(tmp_path)
    assert report["total_models"] == 1
    assert report["imported"] == 1
    assert report["simulated"] == 1
    assert report["matched"] == 1
    assert report["match_rate"] == 1
    assert report["results"][0]["stage"] == "done"
    assert report["results"][0]["compared_variables"] == 1
    assert report["results"][0]["compared_points"] == 2


def test_external_benchmark_rejects_pointwise_drift_and_reports_failures(tmp_path):
    source = (MODELS / "teacup.mdl").read_text()
    document = import_vensim(source)
    result = simulate_model(document, SimulationParameters())
    reference = (
        "Time\tTeacup Temperature\n"
        "0\t180\n"
        f"30\t{result.variables['teacup_temperature'][-1] + 100}\n"
    )
    write_case(tmp_path, "wrong_reference", source, reference)
    (tmp_path / "no_reference").mkdir()
    (tmp_path / "no_reference" / "model.mdl").write_text(source)
    write_case(tmp_path, "broken", "not a model", "Time\tvalue\n0\t0\n")
    report = run_external_benchmark(tmp_path)
    stages = {item["id"]: item["stage"] for item in report["results"]}
    assert stages == {
        "broken/model": "import",
        "no_reference/model": "no_reference",
        "wrong_reference/model": "comparison",
    }
    assert report["reference_models"] == 2
    assert report["imported"] == 1
    assert report["simulated"] == 1
    assert report["matched"] == 0
    assert report["results"][-1]["compared_points"] == 2


def test_external_benchmark_supports_case_selection_and_json_report(tmp_path):
    source = (MODELS / "teacup.mdl").read_text()
    write_case(tmp_path, "cooling", source, "Time\tTeacup Temperature\n0\t180\n")
    report = run_external_benchmark(tmp_path, cases=["cooling"], limit=1)
    assert report["total_models"] == 1
    assert report["matched"] == 1
    json.dumps(report)


def test_external_benchmark_rejects_stock_without_numeric_reference_points(tmp_path):
    source = (MODELS / "teacup.mdl").read_text()
    write_case(
        tmp_path,
        "empty_stock",
        source,
        "Time\tTeacup Temperature\n0\t\n30\t\n",
    )
    report = run_external_benchmark(tmp_path)
    assert report["simulated"] == 1
    assert report["matched"] == 0
    case = report["results"][0]
    assert case["stage"] == "comparison"
    assert case["compared_points"] == 0
    assert case["missing_variables"] == ["Teacup Temperature"]
