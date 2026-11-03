import argparse
import sys
from pathlib import Path

from pydantic import ValidationError

from pipeline.analysis_schemas import CalibrationRequest
from pipeline.calibration import calibration_csv, run_calibration
from pipeline.exceptions import EngineError
from pipeline.io import read_json, write_json_atomic, write_stage


def main() -> int:
    parser = argparse.ArgumentParser(description="Calibrate model parameters against observations")
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--workdir", type=Path, default=Path("work/latest_calibration"))
    parser.add_argument("--output", type=Path, default=Path("out/calibration.json"))
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    try:
        write_stage(args.workdir, "calibration")
        payload = read_json(args.observations)
        request = CalibrationRequest.model_validate(
            {
                **payload,
                "model": read_json(args.model),
            }
        )
        result = run_calibration(request)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(args.output, result.model_dump(mode="json"))
        write_json_atomic(
            args.output.parent / "fitted_model.json", result.fitted_model.model_dump(mode="json")
        )
        csv_path = args.output.with_suffix(".csv")
        csv_path.write_text(calibration_csv(result), encoding="utf-8")
        write_json_atomic(
            args.manifest or args.output.parent / "manifest.json",
            {
                "schema_version": "2.0",
                "kind": "calibration",
                "status": result.status,
                "success": result.success,
                "model_hash": result.fitted_model.model_hash(),
                "fitted_parameters": result.fitted_parameters,
                "metrics": result.metrics,
                "evaluations": result.evaluations,
                "files": [args.output.name, "fitted_model.json", csv_path.name],
            },
        )
        write_stage(args.workdir, "done")
        print(f"calibration written to {args.output}")
        return 0 if result.success else 1
    except (EngineError, ValidationError, OSError, ValueError) as exc:
        print(f"calibration failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
