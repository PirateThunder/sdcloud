import argparse
from pathlib import Path

from pipeline.evaluation import (
    compare_model_reports,
    compare_report_sets,
    export_annotation_tasks,
    inter_annotator_agreement,
)
from pipeline.io import read_json, write_json_atomic


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline analysis of controlled LLM evaluations")
    subparsers = parser.add_subparsers(dest="command", required=True)

    compare = subparsers.add_parser("compare", help="Recompute paired ablation statistics")
    compare.add_argument("--report", type=Path, required=True)
    compare.add_argument("--bootstrap-samples", type=int, default=10_000)
    compare.add_argument("--seed", type=int, default=2026)
    compare.add_argument("--output", type=Path, required=True)

    model_compare = subparsers.add_parser(
        "compare-models", help="Compare two models on identical prompt/run/seed pairs"
    )
    model_compare.add_argument("--baseline", type=Path, required=True)
    model_compare.add_argument("--treatment", type=Path, required=True)
    model_compare.add_argument("--bootstrap-samples", type=int, default=10_000)
    model_compare.add_argument("--seed", type=int, default=2026)
    model_compare.add_argument("--output", type=Path, required=True)

    export = subparsers.add_parser("export", help="Export blind expert annotation tasks")
    export.add_argument("--report", type=Path, required=True)
    export.add_argument("--output-dir", type=Path, required=True)
    export.add_argument("--seed", type=int, default=2026)

    agreement = subparsers.add_parser("agreement", help="Calculate Cohen's kappa")
    agreement.add_argument("--first", type=Path, required=True)
    agreement.add_argument("--second", type=Path, required=True)
    agreement.add_argument("--include-no-model", action="store_true")
    agreement.add_argument("--output", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "compare":
        report = read_json(args.report)
        if report.get("kind") != "llm_ablation":
            parser.error("compare requires an llm_ablation report")
        result = {
            "schema_version": "1.0",
            "kind": "paired_ablation_analysis",
            "provider": report.get("provider"),
            "model": report.get("model"),
            "corpus_sha256": report.get("corpus_sha256"),
            "pipeline_sha256": report.get("pipeline_sha256"),
            "protocol_sha256": report.get("protocol_sha256"),
            "corpus_role": report.get("protocol", {}).get("corpus_role"),
            "comparisons": compare_report_sets(
                report["arms"],
                bootstrap_samples=args.bootstrap_samples,
                seed=args.seed,
            ),
        }
        write_json_atomic(args.output, result)
    elif args.command == "compare-models":
        result = compare_model_reports(
            read_json(args.baseline),
            read_json(args.treatment),
            bootstrap_samples=args.bootstrap_samples,
            seed=args.seed,
        )
        write_json_atomic(args.output, result)
    elif args.command == "export":
        report = read_json(args.report)
        if report.get("kind") != "llm_ablation":
            parser.error("export requires an llm_ablation report")
        result = export_annotation_tasks(
            report["arms"],
            args.output_dir,
            seed=args.seed,
        )
    else:
        result = inter_annotator_agreement(
            args.first,
            args.second,
            include_no_model=args.include_no_model,
        )
        write_json_atomic(args.output, result)
    print(f"output={args.output if args.command != 'export' else args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
