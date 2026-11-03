import argparse
import sys
from pathlib import Path

from pydantic import ValidationError

from pipeline.analysis_schemas import ScenarioRunRequest
from pipeline.exceptions import EngineError
from pipeline.io import read_json, write_json_atomic, write_stage
from pipeline.scenarios import comparison_csv, run_scenarios


def main() -> int:
    parser = argparse.ArgumentParser(description="Run scenarios for a canonical model")
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--scenarios", type=Path, required=True)
    parser.add_argument("--workdir", type=Path, default=Path("work/latest_scenarios"))
    parser.add_argument("--output", type=Path, default=Path("out/scenarios.json"))
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    try:
        write_stage(args.workdir, "scenarios")
        payload = read_json(args.scenarios)
        request = ScenarioRunRequest.model_validate(
            {
                **payload,
                "model": read_json(args.model),
            }
        )
        result = run_scenarios(request)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(args.output, result.model_dump(mode="json"))
        csv_path = args.output.with_name("comparison.csv")
        csv_path.write_text(comparison_csv(result), encoding="utf-8")
        write_json_atomic(
            args.manifest or args.output.parent / "manifest.json",
            {
                "schema_version": "2.0",
                "kind": "scenario",
                "status": result.status,
                "model_hash": result.model_hash,
                "runs": len(result.runs),
                "files": [args.output.name, csv_path.name],
            },
        )
        write_stage(args.workdir, "done")
        print(f"scenarios written to {args.output}")
        return 0 if result.status != "error" else 1
    except (EngineError, ValidationError, OSError, ValueError) as exc:
        print(f"scenarios failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
