import argparse
import asyncio
import os
import sys
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from pipeline.artifacts import write_model_artifacts
from pipeline.conversation import respond_to_message
from pipeline.exceptions import EngineError
from pipeline.io import read_json, write_json_atomic
from pipeline.llm import create_llm
from pipeline.schemas import ConversationRequest
from version import VERSION


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Respond in a system dynamics conversation")
    parser.add_argument("--input", type=Path, required=True, help="ConversationRequest JSON")
    parser.add_argument("--workdir", type=Path, default=Path("work/latest"))
    parser.add_argument("--output", type=Path, default=Path("out/response.json"))
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
        request = ConversationRequest.model_validate(read_json(args.input))
        llm = create_llm(args.provider, args.fixture)
        response = await respond_to_message(request, llm, workdir=args.workdir)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(args.output, response.model_dump(mode="json"))
        files = [args.output.name]
        if response.model is not None:
            files.extend(write_model_artifacts(response.model, args.output.parent / "model.json"))
        manifest = {
            "schema_version": "2.0",
            "kind": "chat",
            "status": "done",
            "response_kind": response.kind,
            "generator_version": VERSION,
            "provider": args.provider,
            "llm_routing": (
                asdict(llm.last_decision)
                if getattr(llm, "last_decision", None) is not None
                else None
            ),
            "model_hash": response.model.model_hash() if response.model else None,
            "validation": response.model.validation.model_dump(mode="json")
            if response.model
            else None,
            "created_at": datetime.now(UTC).isoformat(),
            "duration_seconds": round(time.monotonic() - started, 3),
            "files": files,
        }
        write_json_atomic(args.manifest or args.output.parent / "manifest.json", manifest)
        print(f"conversation response written to {args.output}")
        return 0
    except (EngineError, ValidationError, OSError, ValueError) as exc:
        print(f"conversation failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if llm is not None:
            await llm.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
