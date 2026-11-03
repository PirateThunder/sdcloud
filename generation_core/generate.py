import argparse
import asyncio
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from pipeline.artifacts import write_model_artifacts
from pipeline.exceptions import EngineError
from pipeline.generation import generate_model
from pipeline.io import read_json, write_json_atomic
from pipeline.llm import create_llm
from pipeline.schemas import GenerationRequest
from version import VERSION


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a system dynamics model")
    parser.add_argument("--input", type=Path, required=True, help="GenerationRequest JSON")
    parser.add_argument("--workdir", type=Path, default=Path("work/latest"))
    parser.add_argument("--output", type=Path, default=Path("out/model.json"))
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--provider", default=os.environ.get("LLM_PROVIDER", "openrouter"))
    parser.add_argument(
        "--fixture",
        type=Path,
        default=os.environ.get("LLM_FIXTURE_PATH"),
        help="JSON responses for the fixture provider",
    )
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    started = time.monotonic()
    llm = None
    try:
        request = GenerationRequest.model_validate(read_json(args.input))
        llm = create_llm(args.provider, args.fixture)
        document = await generate_model(request, llm, workdir=args.workdir)
        files = write_model_artifacts(document, args.output)
        manifest = {
            "schema_version": "2.0",
            "kind": "generate",
            "status": "done",
            "generator_version": VERSION,
            "provider": args.provider,
            "model_hash": document.model_hash(),
            "validation": document.validation.model_dump(mode="json"),
            "created_at": datetime.now(UTC).isoformat(),
            "duration_seconds": round(time.monotonic() - started, 3),
            "files": files,
        }
        write_json_atomic(args.manifest or args.output.parent / "manifest.json", manifest)
        print(f"model written to {args.output}")
        return 0
    except (EngineError, ValidationError, OSError, ValueError) as exc:
        print(f"generation failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if llm is not None:
            await llm.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
