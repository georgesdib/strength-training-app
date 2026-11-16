"""Explain the System: retrieve project sources, ask the model, check citations."""

from __future__ import annotations

from dataclasses import dataclass

from strength_coach.agents.client import LLMClient
from strength_coach.intelligence.knowledge.allowlist import KnowledgeConfig
from strength_coach.intelligence.knowledge.citations import Citation, extract
from strength_coach.intelligence.knowledge.retrieval import RetrievedChunk, search


@dataclass(frozen=True)
class ExplainResult:
    answer: str
    citations: tuple[Citation, ...]
    warnings: tuple[str, ...]
    grounded: bool
    tokens: int | None
    chunks: tuple[RetrievedChunk, ...]


SYSTEM = (
    "You explain how this training system works. Use the PROJECT SOURCES below when they answer "
    "the question. If they do not, answer from general knowledge and state clearly that the answer "
    "is ungrounded and may not match this project. Never invent file paths. Cite project claims as "
    "[path:start-end] and put a short quoted phrase from the cited lines in backticks next to the "
    "citation. Keep the answer under {words} words. Do not prescribe training or give medical advice."
)


def _sources(chunks: tuple[RetrievedChunk, ...]) -> str:
    blocks = []
    for chunk in chunks:
        label = "TEST EXPECTATION" if "/test" in chunk.path or chunk.path.startswith("tests/") else "SOURCE"
        blocks.append(
            f"[{label} {chunk.path}:{chunk.line_start}-{chunk.line_end}]\n"
            f"{chunk.text}"
        )
    return "\n\n".join(blocks)


def run_explain(
    config: KnowledgeConfig, client: LLMClient, question: str,
) -> ExplainResult:
    chunks = tuple(search(
        config.index_path, question,
        top_k=config.top_k, max_chars=config.max_context_chars,
    ))
    source_text = _sources(chunks)
    if not source_text:
        source_text = "(No matching project source was retrieved.)"
    prompt = (
        f"QUESTION:\n{question}\n\nPROJECT SOURCES:\n{source_text}\n\n"
        "If no project source was retrieved, say that the answer is ungrounded."
    )
    response = client.complete(prompt, system=SYSTEM.format(words=config.max_answer_words))
    citations = tuple(extract(response.text, config, config.index_path))
    warnings: list[str] = []
    if chunks and not citations:
        warnings.append("the answer contains no project citation")
    for citation in citations:
        if not citation.verified and citation.warning:
            warnings.append(f"{citation.path}:{citation.line_start}: {citation.warning}")
    return ExplainResult(
        answer=response.text,
        citations=citations,
        warnings=tuple(dict.fromkeys(warnings)),
        grounded=bool(chunks and citations and all(c.verified for c in citations)),
        tokens=response.tokens,
        chunks=chunks,
    )
