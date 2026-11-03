import argparse
import sys
from pathlib import Path

from pydantic import ValidationError

from pipeline.analysis_schemas import SensitivityRequest
from pipeline.exceptions import EngineError
from pipeline.io import read_json, write_json_atomic, write_stage
from pipeline.scenarios import run_sensitivity, sensitivity_csv


def main() -> int:
    parser = argparse.ArgumentParser(description="Run seeded sensitivity analysis")
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--workdir", type=Path, default=Path("work/latest_sensitivity"))
    parser.add_argument("--output", type=Path, default=Path("out/sensitivity.json"))
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    try:
        write_stage(args.workdir, "sensitivity")
        payload = read_json(args.config)
        request = SensitivityRequest.model_validate(
            {
                **payload,
                "model": read_json(args.model),
            }
        )
        result = run_sensitivity(request)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(args.output, result.model_dump(mode="json"))
        csv_path = args.output.with_suffix(".csv")
        csv_path.write_text(sensitivity_csv(result), encoding="utf-8")
        write_json_atomic(
            args.manifest or args.output.parent / "manifest.json",
            {
                "schema_version": "2.0",
                "kind": "sensitivity",
                "status": result.status,
                "model_hash": result.model_hash,
                "config_hash": result.config_hash,
                "seed": result.seed,
                "successful_runs": result.successful_runs,
                "failed_runs": result.failed_runs,
                "files": [args.output.name, csv_path.name],
            },
        )
        write_stage(args.workdir, "done")
        print(f"sensitivity written to {args.output}")
        return 0
    except (EngineError, ValidationError, OSError, ValueError) as exc:
        print(f"sensitivity failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
