from __future__ import annotations

import json
import math
import os
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .exceptions import ModelValidationError
from .io import read_json
from .schemas import ContractModel

_TOKEN = re.compile(r"[^\W\d_]+", re.UNICODE)


class RagExample(ContractModel):
    id: str
    description: str
    components: list[dict]
    time: dict
    assumptions: list[dict]
    source: dict


class RagCorpus(ContractModel):
    schema_version: str
    kind: str
    source_reports: list[str]
    examples: list[RagExample]


@dataclass(frozen=True)
class RagHit:
    example: RagExample
    score: float


def _tokens(value: str) -> Counter[str]:
    return Counter(_TOKEN.findall(value.casefold()))


def _idf(documents: list[Counter[str]]) -> dict[str, float]:
    frequencies = Counter(token for document in documents for token in document)
    count = len(documents)
    return {
        token: math.log((count + 1) / (frequency + 1)) + 1
        for token, frequency in frequencies.items()
    }


def _norm(document: Counter[str], idf: dict[str, float]) -> float:
    return math.sqrt(sum((count * idf.get(token, 1.0)) ** 2 for token, count in document.items()))


def retrieve(
    description: str,
    examples: list[RagExample],
    *,
    limit: int = 1,
    min_score: float = 0.08,
) -> list[RagHit]:
    if not 1 <= limit <= 3:
        raise ValueError("RAG limit must be between 1 and 3")
    if not 0 <= min_score <= 1:
        raise ValueError("RAG min_score must be between 0 and 1")
    documents = [
        _tokens(f"{example.description} {json.dumps(example.components, ensure_ascii=False)}")
        for example in examples
    ]
    idf = _idf(documents)
    query = _tokens(description)
    query_norm = _norm(query, idf)
    if query_norm == 0:
        return []
    hits = []
    for example, document in zip(examples, documents, strict=True):
        document_norm = _norm(document, idf)
        if document_norm == 0:
            continue
        score = sum(
            count * idf.get(token, 1.0) ** 2 * document.get(token, 0)
            for token, count in query.items()
        ) / (query_norm * document_norm)
        if score >= min_score:
            hits.append(RagHit(example=example, score=score))
    return sorted(hits, key=lambda hit: (-hit.score, hit.example.id))[:limit]


def load_examples(path: Path) -> list[RagExample]:
    if not path.is_file():
        raise ModelValidationError(f"RAG corpus not found: {path}")
    try:
        corpus = RagCorpus.model_validate(read_json(path))
    except Exception as exc:
        raise ModelValidationError(f"invalid RAG corpus: {path}: {exc}") from exc
    ids = [example.id for example in corpus.examples]
    if len(ids) != len(set(ids)):
        raise ModelValidationError("RAG corpus example ids must be unique")
    return corpus.examples


def component_rag_context(description: str) -> tuple[str, list[str]]:
    enabled = os.environ.get("LLM_RAG_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
    if not enabled:
        return "", []
    default_path = Path(__file__).with_name("rag_examples.json")
    path = Path(os.environ.get("LLM_RAG_CORPUS_PATH", default_path))
    try:
        limit = int(os.environ.get("LLM_RAG_MAX_EXAMPLES", "1"))
        min_score = float(os.environ.get("LLM_RAG_MIN_SCORE", "0.08"))
        max_chars = int(os.environ.get("LLM_RAG_MAX_CHARS", "3500"))
    except ValueError as exc:
        raise ModelValidationError("invalid numeric RAG settings") from exc
    if not 500 <= max_chars <= 8000:
        raise ModelValidationError("LLM_RAG_MAX_CHARS must be between 500 and 8000")
    hits = retrieve(
        description,
        load_examples(path),
        limit=limit,
        min_score=min_score,
    )
    contexts = []
    sources = []
    for hit in hits:
        plan = {
            "components": hit.example.components,
            "time": hit.example.time,
            "assumptions": hit.example.assumptions,
        }
        context = (
            f"\n\nПроверенный RAG пример {hit.example.id} (similarity={hit.score:.3f}).\n"
            "Используй только структуру механизма и способ записи. Не копируй ids, stocks, "
            "numeric values, units или horizon: возьми их из текущего описания. Validators "
            "остаются обязательными.\n"
            f"Описание примера: {hit.example.description}\n"
            f"ComponentPlan примера: {json.dumps(plan, ensure_ascii=False, separators=(',', ':'))}"
        )
        if len(context) > max_chars:
            continue
        contexts.append(context)
        sources.append(hit.example.id)
    return "".join(contexts), sources
