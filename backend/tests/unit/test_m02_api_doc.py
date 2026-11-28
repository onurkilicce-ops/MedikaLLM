"""The full 200 example in src/timing/API.md must equal the real service output
for the same SYNTHETIC rows (limitation messages are abbreviated in the doc,
so only their codes are compared). Guards against contract/doc drift."""
from __future__ import annotations

import json
from pathlib import Path

from src.timing import repository, service

_DOC = Path(__file__).resolve().parents[2] / "src" / "timing" / "API.md"


def test_api_md_full_example_matches_service_output(monkeypatch):
    rows = {
        "DB00006": repository.DrugTimingRow(
            1, "DB00006", "[SYNTHETIC] Timing Agent A",
            "[SYNTHETIC] The elimination half-life is 4-6 hours.[A900002]",
            "[SYNTHETIC] Peak plasma concentrations are reached within 0.5-1 hours after oral administration."
            "[A900001]"),
        "DB00682": repository.DrugTimingRow(2, "DB00682", "[SYNTHETIC] Timing Agent C", "", "Not Available"),
    }
    refs = {1: [
        repository.ReferenceRow(1, "A900001", "article", None, None, "[SYNTHETIC] Synthetic absorption study.",
                                None, None),
        repository.ReferenceRow(1, "A900002", "article", None, None, "[SYNTHETIC] Synthetic elimination study.",
                                None, None),
    ]}
    monkeypatch.setattr(repository, "read_timing_data", lambda ids, tokens_of: (rows, refs))
    live = service.compare(["DB00006", "DB00682", "DB99999"]).model_dump(mode="json")
    doc = _DOC.read_text(encoding="utf-8")
    block = doc.split("## Tam 200 örneği", 1)[1].split("```json", 1)[1].split("```", 1)[0]
    example = json.loads(block)
    for d in (live, example):
        d["limitations"] = [{"code": x["code"]} for x in d["limitations"]]
    assert example == live
