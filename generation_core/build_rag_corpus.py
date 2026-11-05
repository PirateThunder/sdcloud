import argparse
from pathlib import Path

from pipeline.rag_corpus import write_corpus


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a validated lexical ComponentPlan RAG corpus")
    parser.add_argument("--root", type=Path, default=Path(__file__).parent)
    parser.add_argument("--output", type=Path, default=Path("pipeline/rag_examples.json"))
    args = parser.parse_args()
    corpus = write_corpus(args.root, args.output)
    print(f"RAG corpus: {len(corpus['examples'])} examples, output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
