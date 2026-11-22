"""The compact system prompt and tool descriptions keep the safety contract.

The prompt was compacted (about 3,900 -> 1,200 tokens) because it is re-sent
with every model call and Groq's free tier allows 8,000 tokens per minute.
These checks make sure a later edit cannot silently drop a non-negotiable
rule, bring back removed wording, or let the fixed overhead grow back.
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("langchain", reason="agent prompt imports langchain")

from langchain_core.utils.function_calling import convert_to_openai_tool  # noqa: E402

from src.agent import token_budget  # noqa: E402
from src.agent.langchain_agent import SYSTEM_PROMPT, build_system_prompt  # noqa: E402
from src.agent.tools import ALL_TOOLS  # noqa: E402
from src.users.models import PatientBase  # noqa: E402

REQUIRED_IN_CORE = [
    "TOOLS FIRST", "greetings",                                  # tools first, casual chat exempt
    "NO GAP-FILLING", "training knowledge", "general knowledge",  # no gap-filling, not even with a disclaimer
    "NEVER invent sources, citation numbers, severity labels",
    "STATUS:", "NO_RECORD is never", "UNKNOWN", "INCOMPLETE", "APPROXIMATE",
    "severity not rated (no source label)", "MAJOR/MODERATE/MINOR", "⚠️", "✅",
    "EXPLICITLY ASKS", "recommend_alternative_drug", "UNVERIFIED",
    "search_drugs_by_indication", "Name only drugs returned",
    "ASCII square brackets", "【", "this turn's tool outputs", "never fabricate numbers", "No References section",
    "dosing", "consulting a healthcare provider",
    "NEVER ask how many articles", "search_pubmed_multi", "aile öyküsü",
    "NEVER repeat a call with identical parameters", "never announce them",
    "HOW TO USE", "Terminology correction",
    "HTML", "single-line cells",
]

FORBIDDEN = [
    "LAST RESORT",            # old gap-filling fallback
    "SAFE ✅", "✅ SAFE",
    "monitoring INR",         # clinical example that primed unsupported advice
    "default 10",             # stale PubMed default
    "default of 10",
]


def _all_texts():
    patient = PatientBase(patient_id="p", user_id="u", name="Synthetic Patient", current_medications=["Warfarin"])
    prompts = [build_system_prompt(is_doctor=d, patient=p) for d in (False, True) for p in (None, patient)]
    tools = [json.dumps(convert_to_openai_tool(t), ensure_ascii=False) for t in ALL_TOOLS]
    return prompts, tools


def test_core_prompt_keeps_every_non_negotiable_rule():
    missing = [phrase for phrase in REQUIRED_IN_CORE if phrase not in SYSTEM_PROMPT]
    assert missing == []


def test_removed_wording_does_not_come_back():
    prompts, tools = _all_texts()
    for text in prompts + tools:
        for phrase in FORBIDDEN:
            assert phrase not in text, phrase


def test_role_blocks_keep_their_limits():
    doctor = build_system_prompt(is_doctor=True)
    general = build_system_prompt(is_doctor=False)
    assert "contraindications or allergy cross-reactivity: say these were not checked" in doctor
    assert "not medical advice" in general
    assert "without adding advice they do not contain" in general


def test_patient_rules_cover_mentioned_drugs_unnamed_review_and_allergy():
    patient = PatientBase(patient_id="p", user_id="u", name="Synthetic Patient", current_medications=["Warfarin"])
    text = build_system_prompt(is_doctor=True, patient=patient)
    assert "analyze_patient_medications" in text
    assert "additional_drugs=[]" in text
    assert "cross-reactivity" in text and "never infer it" in text


def test_tool_descriptions_keep_the_gates_and_defaults():
    by_name = {t.name: convert_to_openai_tool(t)["function"] for t in ALL_TOOLS}
    assert by_name["recommend_alternative_drug"]["description"].startswith("Only when the user explicitly asks")
    assert "UNVERIFIED" in by_name["recommend_alternative_drug"]["description"]
    assert by_name["analyze_patient_medications"]["description"].startswith("Active patient only")
    for name in ("search_pubmed", "search_pubmed_multi"):
        props = by_name[name]["parameters"]["properties"]["num_articles"]
        assert props["default"] == 5
        assert "default 5" in props["description"] and "max 10" in props["description"]
        assert "never ask" in props["description"]


def test_fixed_overhead_stays_within_the_budget():
    token_budget.warm_up(blocking=True)
    if token_budget.estimator_name() != "tiktoken:o200k_base":
        pytest.skip("tiktoken o200k_base encoding not available offline")
    prompt = token_budget.estimate_text_tokens(build_system_prompt(is_doctor=True))
    tools = sum(token_budget.estimate_text_tokens(json.dumps(convert_to_openai_tool(t))) for t in ALL_TOOLS)
    # Was 4,013 + 2,735 = 6,748. Leave headroom for small edits, not a regrowth.
    assert prompt <= 1400, prompt
    assert tools <= 1800, tools
