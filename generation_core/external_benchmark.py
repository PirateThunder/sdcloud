import argparse
from pathlib import Path

from pipeline.external_benchmark import run_external_benchmark
from pipeline.io import write_json_atomic


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import and compare an external SD model corpus without LLM calls"
    )
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--extension", choices=[".mdl", ".xmile"], default=".mdl")
    parser.add_argument("--cases", default="")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--rtol", type=float, default=1e-3)
    parser.add_argument("--atol", type=float, default=1e-5)
    parser.add_argument("--output", type=Path, default=Path("out/external-benchmark.json"))
    args = parser.parse_args()
    result = run_external_benchmark(
        args.root,
        extension=args.extension,
        cases=[item for item in args.cases.split(",") if item] or None,
        limit=args.limit,
        rtol=args.rtol,
        atol=args.atol,
    )
    write_json_atomic(args.output, result)
    print(
        f"external benchmark: models={result['total_models']}, references={result['reference_models']}, "
        f"imported={result['imported']}, simulated={result['simulated']}, "
        f"matched={result['matched']}, output={args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
