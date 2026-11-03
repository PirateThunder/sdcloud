import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "llm_responses.json"


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def test_cli_generation_and_simulation(tmp_path):
    output = tmp_path / "model.json"
    generation = run_cli(
        str(ROOT / "generate.py"),
        "--input",
        str(ROOT / "examples" / "predator_prey.json"),
        "--provider",
        "fixture",
        "--fixture",
        str(FIXTURE),
        "--workdir",
        str(tmp_path / "work"),
        "--output",
        str(output),
    )
    assert generation.returncode == 0, generation.stderr
    document = json.loads(output.read_text(encoding="utf-8"))
    assert document["schema_version"] == "2.0"
    assert len(document["variables"]) == 10
    for name in ("model.py", "model.mdl", "model.xmile"):
        assert (tmp_path / name).is_file()

    simulation_output = tmp_path / "simulation.json"
    simulation = run_cli(
        str(ROOT / "simulate.py"),
        "--model",
        str(output),
        "--params",
        str(ROOT / "examples" / "simulation.json"),
        "--workdir",
        str(tmp_path / "simulation_work"),
        "--output",
        str(simulation_output),
    )
    assert simulation.returncode == 0, simulation.stderr
    result = json.loads(simulation_output.read_text(encoding="utf-8"))
    assert result["schema_version"] == "2.0"
    assert len(result["time"]) == 41
    assert len(result["variables"]) == 10
    assert (tmp_path / "simulation.csv").is_file()


def test_cli_import_and_export(tmp_path):
    output = tmp_path / "model.json"
    imported = run_cli(
        str(ROOT / "convert.py"),
        "import",
        "--input",
        str(ROOT / "tests" / "fixtures" / "models" / "teacup.mdl"),
        "--workdir",
        str(tmp_path / "work"),
        "--output",
        str(output),
    )
    assert imported.returncode == 0, imported.stderr
    document = json.loads(output.read_text(encoding="utf-8"))
    assert document["schema_version"] == "2.0"
    assert document["provenance"]["kind"] == "vensim_import"
    exported = tmp_path / "roundtrip.xmile"
    result = run_cli(
        str(ROOT / "convert.py"),
        "export",
        "--model",
        str(output),
        "--format",
        "xmile",
        "--output",
        str(exported),
    )
    assert result.returncode == 0, result.stderr
    assert "Teacup Temperature" in exported.read_text(encoding="utf-8")
