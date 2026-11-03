from pathlib import Path

from .codegen import export_vensim, generate_python_code
from .formats import export_xmile
from .io import write_json_atomic
from .schemas import ModelDocument


def write_model_artifacts(document: ModelDocument, output: Path) -> list[str]:
    output.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(output, document.model_dump(mode="json"))
    (output.parent / "model.py").write_text(generate_python_code(document), encoding="utf-8")
    (output.parent / "model.mdl").write_text(export_vensim(document), encoding="utf-8")
    files = [output.name, "model.py", "model.mdl"]
    if document.validation.capabilities.supported.get("xmile_export", False):
        (output.parent / "model.xmile").write_text(export_xmile(document), encoding="utf-8")
        files.append("model.xmile")
    return files
