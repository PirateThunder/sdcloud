import argparse
import asyncio
import os
from pathlib import Path

from pipeline.benchmark import run_benchmark
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
    parser.add_argument("--output", type=Path, default=Path("out/benchmark.json"))
    parser.add_argument("--artifacts-dir", type=Path, default=None)
    args = parser.parse_args()
    llm = create_llm(args.provider, args.fixture)
    try:
        result = await run_benchmark(
            llm,
            runs=args.runs,
            prompt_ids=[item for item in args.prompt_ids.split(",") if item] or None,
            prompts_path=args.prompts_file,
            artifacts_dir=args.artifacts_dir,
            max_repairs=args.max_repairs,
            concurrency=args.concurrency,
        )
        result["provider"] = args.provider
        if args.provider in {"local", "vllm", "openai_compatible"}:
            result["model"] = os.environ.get("LOCAL_LLM_MODEL", "")
        else:
            result["model"] = os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini")
        result["llm_settings"] = {
            "structured_output": getattr(llm, "structured_output", None),
            "max_tokens": getattr(llm, "max_tokens", None),
        }
        write_json_atomic(args.output, result)
        print(
            f"benchmark: cases={result['cases']}, executable={result['executable_rate']:.1%}, "
            f"semantic={result['semantic_rate']:.1%}, behavior={result['behavior_rate']:.1%}, "
            f"finite={result['finite_rate']:.1%}, output={args.output}"
        )
        return 0
    finally:
        await llm.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
