import argparse
import asyncio
import os
from pathlib import Path

from pipeline.ablation import run_ablation
from pipeline.benchmark import run_benchmark
from pipeline.evaluation import export_annotation_tasks
from pipeline.io import write_json_atomic
from pipeline.llm import create_llm


async def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate LLM generation quality")
    parser.add_argument("--provider", default=os.environ.get("LLM_PROVIDER", "openrouter"))
    parser.add_argument("--fixture", type=Path, default=os.environ.get("LLM_FIXTURE_PATH"))
    parser.add_argument("--prompts-file", type=Path, default=None)
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--prompt-ids", default="")
    parser.add_argument("--max-repairs", type=int, default=2)
    parser.add_argument(
        "--mode",
        choices=("direct", "typed_no_repair", "full", "ablation"),
        default="full",
    )
    parser.add_argument(
        "--corpus-role",
        choices=("development", "regression", "blind"),
        default="regression",
    )
    parser.add_argument("--bootstrap-samples", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--annotations", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--artifacts-dir", type=Path, default=None)
    args = parser.parse_args()
    output = args.output or Path(
        "out/ablation.json" if args.mode == "ablation" else "out/benchmark.json"
    )
    if args.annotations is not None and (
        args.mode != "ablation" or args.artifacts_dir is None
    ):
        parser.error("--annotations requires --mode ablation and --artifacts-dir")
    llm = create_llm(args.provider, args.fixture)
    try:
        common = {
            "runs": args.runs,
            "prompt_ids": [item for item in args.prompt_ids.split(",") if item] or None,
            "prompts_path": args.prompts_file,
            "artifacts_dir": args.artifacts_dir,
            "max_repairs": args.max_repairs,
            "concurrency": args.concurrency,
            "corpus_role": args.corpus_role,
        }
        if args.mode == "ablation":
            result = await run_ablation(
                llm,
                **common,
                bootstrap_samples=args.bootstrap_samples,
                seed=args.seed,
            )
        else:
            result = await run_benchmark(llm, generation_mode=args.mode, **common)
        model = (
            os.environ.get("LOCAL_LLM_MODEL", "")
            if args.provider in {"local", "vllm", "openai_compatible"}
            else os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini")
        )
        result["provider"] = args.provider
        result["model"] = model if args.provider != "fixture" else None
        if args.mode != "ablation":
            result["llm_settings"] = {
                field: getattr(llm, field, None)
                for field in (
                    "structured_output",
                    "component_structured_output",
                    "pattern_shortcut",
                    "allow_unstructured_fallback",
                    "max_tokens",
                    "request_retries",
                    "seed",
                    "provider_options",
                )
            }
        if args.annotations is not None:
            export_annotation_tasks(
                result["arms"],
                args.annotations,
                seed=args.seed,
            )
        write_json_atomic(output, result)
        if args.mode == "ablation":
            for arm, report in result["arms"].items():
                print(
                    f"{arm}: cases={report['cases']}, "
                    f"executable={report['executable_rate']:.1%}, "
                    f"semantic={report['semantic_rate']:.1%}, "
                    f"behavior={report['behavior_rate']:.1%}"
                )
        else:
            print(
                f"benchmark: cases={result['cases']}, "
                f"executable={result['executable_rate']:.1%}, "
                f"semantic={result['semantic_rate']:.1%}, "
                f"behavior={result['behavior_rate']:.1%}, "
                f"finite={result['finite_rate']:.1%}"
            )
        print(f"output={output}")
        return 0
    finally:
        await llm.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
