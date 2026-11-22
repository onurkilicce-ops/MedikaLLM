"""Check that the inline citations in an answer point at real tool sources.

Tools register every retrievable record (DrugBank record, interaction edge,
PubMed article, ...) under a REF id and the model is told to cite them as
``[N]``. Nothing used to verify that the numbers in the final answer exist,
so a fabricated ``[7]`` looked exactly like a real citation. This module
compares the cited numbers with the sources actually collected during the
request; the chat stream reports the result and the UI warns on mismatches.
It does NOT judge whether a source supports a claim — that still needs a
human reviewer.
"""
from __future__ import annotations

import re
from typing import Iterable

# Same grammar the frontend renders as citation badges:
# [1], [1, 2], [REF3], and full-width 【4】.
_CITATION_RE = re.compile(
    r"[\[【](?:REF)?\s*(\d+(?:\s*,\s*(?:REF)?\s*\d+)*)\s*[\]】]",
    re.IGNORECASE,
)


def cited_numbers(content: str) -> list[int]:
    """Citation numbers in first-occurrence order (deduplicated)."""
    seen: list[int] = []
    for match in _CITATION_RE.finditer(content or ""):
        for part in match.group(1).split(","):
            digits = re.sub(r"[^0-9]", "", part)
            if digits:
                n = int(digits)
                if n not in seen:
                    seen.append(n)
    return seen


def _source_numbers(sources: Iterable[dict]) -> set[int]:
    numbers: set[int] = set()
    for src in sources or []:
        match = re.search(r"(\d+)", str((src or {}).get("ref", "")))
        if match:
            numbers.add(int(match.group(1)))
    return numbers


def uncited_lines(content: str) -> int:
    """Count substantive answer lines that carry no inline citation.

    A deterministic transparency signal, not a claim checker: headings, very
    short lines and lines that are themselves citations are ignored; every
    other line without ``[N]`` is counted. The model is instructed to cite
    each clinical sentence inline, so a non-zero count marks statements the
    user cannot trace to a retrieved record (e.g. advice added from the
    model's general knowledge).
    """
    count = 0
    for raw in (content or "").splitlines():
        line = raw.strip()
        if len(line) < 30 or line.startswith("#") or line.startswith("|---"):
            continue
        if _CITATION_RE.search(line):
            continue
        stripped = line.strip("*_>-• ").rstrip(":")
        if len(stripped) < 30:
            continue  # bold section titles such as "**Clinical implication**"
        count += 1
    return count


def check_citations(content: str, sources: list[dict] | None) -> dict:
    """Summarise how the answer's citations relate to collected sources."""
    cited = cited_numbers(content)
    available = _source_numbers(sources or [])
    unknown = [n for n in cited if n not in available]
    return {
        "cited_refs": cited,
        "unknown_refs": unknown,
        "available_ref_count": len(available),
        # Sources were retrieved but the answer cites none of them: the text
        # may contain claims the user cannot trace back to a record.
        "uncited_answer_with_sources": bool(available) and not cited,
        # Lines without an inline citation in an answer that had sources.
        "uncited_lines": uncited_lines(content) if available else 0,
    }
