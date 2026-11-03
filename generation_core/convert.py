import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from pipeline.artifacts import write_model_artifacts
from pipeline.codegen import export_vensim, generate_python_code
from pipeline.exceptions import EngineError, ModelValidationError
from pipeline.formats import export_xmile, import_model
from pipeline.io import write_json_atomic, write_stage
from pipeline.schemas import ModelDocument
from pipeline.validation import ensure_valid_model
from version import VERSION


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import or export system dynamics models")
    commands = parser.add_subparsers(dest="command", required=True)
    importer = commands.add_parser("import")
    importer.add_argument("--input", type=Path, required=True)
    importer.add_argument("--format", choices=["vensim", "xmile"])
    importer.add_argument("--workdir", type=Path, default=Path("work/latest_import"))
    importer.add_argument("--output", type=Path, default=Path("out/model.json"))
    importer.add_argument("--manifest", type=Path)
    exporter = commands.add_parser("export")
    exporter.add_argument("--model", type=Path, required=True)
    exporter.add_argument("--format", choices=["python", "vensim", "xmile", "json"], required=True)
    exporter.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "export":
            document = ensure_valid_model(
                ModelDocument.model_validate(json.loads(args.model.read_text(encoding="utf-8")))
            )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            if args.format == "python":
                content = generate_python_code(document)
            elif args.format == "vensim":
                content = export_vensim(document)
            elif args.format == "xmile":
                content = export_xmile(document)
            else:
                content = json.dumps(document.model_dump(mode="json"), ensure_ascii=False, indent=2)
            args.output.write_text(content, encoding="utf-8")
            print(f"model exported to {args.output}")
            return 0
        write_stage(args.workdir, "parse")
        file_format = args.format or {".mdl": "vensim", ".xmile": "xmile"}.get(
            args.input.suffix.lower()
        )
        if file_format is None:
            raise ModelValidationError("import format must be vensim or xmile")
        source = args.input.read_text(encoding="utf-8-sig")
        document = import_model(source, file_format, source_name=args.input.name)
        write_stage(args.workdir, "exports")
        files = write_model_artifacts(document, args.output)
        manifest = {
            "schema_version": "2.0",
            "kind": "import",
            "status": "done",
            "generator_version": VERSION,
            "source_format": file_format,
            "model_hash": document.model_hash(),
            "validation": document.validation.model_dump(mode="json"),
            "files": files,
        }
        write_json_atomic(args.manifest or args.output.parent / "manifest.json", manifest)
        write_stage(args.workdir, "done")
        print(f"model imported to {args.output}")
        return 0
    except (EngineError, ValidationError, OSError, ValueError) as exc:
        print(f"conversion failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
