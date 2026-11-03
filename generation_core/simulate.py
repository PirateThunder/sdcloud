import argparse
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from pipeline.exceptions import EngineError
from pipeline.formats import export_csv
from pipeline.io import read_json, write_json_atomic, write_stage
from pipeline.schemas import ModelDocument, SimulationParameters
from pipeline.simulation import simulate_model
from version import VERSION


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Simulate a system dynamics model")
    parser.add_argument("--model", type=Path, required=True, help="ModelDocument JSON")
    parser.add_argument("--params", type=Path, required=True, help="SimulationParameters JSON")
    parser.add_argument("--workdir", type=Path, default=Path("work/latest_simulation"))
    parser.add_argument("--output", type=Path, default=Path("out/simulation.json"))
    parser.add_argument("--csv", type=Path)
    parser.add_argument("--manifest", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    started = time.monotonic()
    try:
        write_stage(args.workdir, "simulation")
        document = ModelDocument.model_validate(read_json(args.model))
        parameters = SimulationParameters.model_validate(read_json(args.params))
        result = simulate_model(document, parameters)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(args.output, result.model_dump(mode="json"))
        csv_path = args.csv or args.output.with_suffix(".csv")
        csv_path.write_text(export_csv(result), encoding="utf-8")
        manifest = {
            "schema_version": "2.0",
            "kind": "simulate",
            "status": "done",
            "generator_version": VERSION,
            "model_hash": document.model_hash(),
            "engine": result.engine,
            "requested_engine": result.requested_engine,
            "integration_method": result.integration_method,
            "requested_method": result.requested_method,
            "fallback_reason": result.fallback_reason,
            "created_at": datetime.now(UTC).isoformat(),
            "duration_seconds": round(time.monotonic() - started, 3),
            "points": len(result.time),
            "files": [args.output.name, csv_path.name],
        }
        write_json_atomic(args.manifest or args.output.parent / "manifest.json", manifest)
        write_stage(args.workdir, "done")
        print(f"simulation written to {args.output}")
        return 0
    except (EngineError, ValidationError, OSError, ValueError) as exc:
        print(f"simulation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
