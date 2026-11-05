from __future__ import annotations

from pathlib import Path

from .io import read_json, write_json_atomic
from .schemas import ModelDocument

REPORT_SOURCES = (
    "benchmark-openrouter-independent-14x3-v6.json",
    "benchmark-openrouter-fitz-hugh-v8-targeted.json",
    "benchmark-openrouter-residual-transport-v8-targeted.json",
    "benchmark-openrouter-independent-confirmation-10x3-v3.json",
    "benchmark-openrouter-residual-confirmation-v4-targeted.json",
)


def _artifacts_path(root: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute() and path.parts[:3] == ("/", "app", "work_api"):
        return root / "out" / Path(*path.parts[3:])
    return root / "out" / path


def build_corpus(root: Path) -> dict:
    selected = {}
    used_reports = []
    for report_name in REPORT_SOURCES:
        report_path = root / "out" / report_name
        if not report_path.is_file():
            continue
        report = read_json(report_path)
        used_reports.append(report_name)
        for case in report["results"]:
            if not case.get("behavior_pass") or not case.get("semantic_pass"):
                continue
            prompt_id = case["prompt_id"]
            if prompt_id.startswith(("accept", "blind")):
                continue
            directory = _artifacts_path(root, case["artifacts"])
            prompt = read_json(directory / "prompt.json")
            document = ModelDocument.model_validate(read_json(directory / "model.json"))
            if document.brief is None or not document.brief.components:
                continue
            selected[prompt_id] = {
                "id": prompt_id,
                "description": prompt["description"],
                "components": [
                    component.model_dump(mode="json")
                    for component in document.brief.components
                ],
                "time": document.time.model_dump(mode="json"),
                "assumptions": [
                    assumption.model_dump(mode="json") for assumption in document.assumptions
                ],
                "source": {
                    "report": report_name,
                    "run": case["run"],
                    "model_hash": document.model_hash(),
                    "expected_behavior": prompt.get("expected_behavior"),
                },
            }
    return {
        "schema_version": "1.0",
        "kind": "lexical_component_rag",
        "source_reports": used_reports,
        "examples": [selected[key] for key in sorted(selected)],
    }


def write_corpus(root: Path, output: Path) -> dict:
    corpus = build_corpus(root)
    if not corpus["examples"]:
        raise ValueError("no validated ComponentPlan examples found")
    write_json_atomic(output, corpus)
    return corpus
