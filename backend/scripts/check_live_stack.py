"""Live check of the chat stack WITHOUT writing anything.

What it verifies, each as a separate result:
  1. config   — which settings are present (never prints secret values)
  2. database — read-only connection (default_transaction_read_only=on) and
                 the row counts of the three core drug tables
  3. agent    — the LangChain agent object can be constructed
  4. llm      — real chat turns through Session.handle_user_query_streamed:
                 real LLM provider, real tools, real (read-only) database.
                 Conversation persistence is replaced by an in-memory no-op,
                 so no conversation, message or quota row is written; a
                 follow-up question shares the in-memory conversation (and
                 so its history) with the question before it.

Per prompt it records the provider-reported token usage of every model call,
any rate-limit wait notices, the provider's limit headers afterwards, the
tools' STATUS lines, sources and the citation check.

It costs real LLM calls and counts against the provider's daily quota
(about 8K tokens per drug question on Groq's free tier). Run from backend/:

    uv run python scripts/check_live_stack.py --pause 65 --out live_check.json
    uv run python scripts/check_live_stack.py --only normal_chat,single_drug
    uv run python scripts/check_live_stack.py --skip-llm      # no provider calls

Prompts marked back-to-back run without the pause, to show the wait notice
when the per-minute budget is exhausted. Output is JSON; answers are
truncated and contain no credentials.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)  # settings read ../.env and .env relative to backend/

NO_RECORD_PAIR_DEFAULT = "Amoxicillin,Loratadine"

# (name, prompt, conversation key, back-to-back with the previous prompt).
# Prompts sharing a conversation key share one in-memory conversation.
DEFAULT_PROMPTS = [
    ("normal_chat", "Merhaba! Kısaca ne tür sorularda yardımcı olabilirsin?", "c1", False),
    ("single_drug", "Varfarin (warfarin) nedir ve ne için kullanılır?", "c2", False),
    ("two_drug_interaction", "Warfarin ile aspirin arasında belgelenmiş bir etkileşim var mı?", "c3", False),
    ("follow_up_same_conversation",
     "Bu etkileşim kaydı hangi kaynağa dayanıyor ve önem derecesi nedir?", "c3", False),
    ("unknown_drug", "Xyzzyl ile warfarin arasında belgelenmiş bir etkileşim var mı?", "c4", False),
    ("no_record_pair", "{a} ile {b} arasında belgelenmiş bir etkileşim var mı?", "c5", False),
    ("pubmed_three_articles",
     "Metformin ve laktik asidoz riski hakkında PubMed'den 3 makale bulur musun?", "c6", False),
    ("back_to_back_first", "Parasetamol nedir, ne için kullanılır?", "c7", False),
    ("back_to_back_second", "İbuprofen nedir, ne için kullanılır?", "c8", True),
]


def _config_report(settings) -> dict:
    db = urlparse(settings.postgres_url or "")
    env_files = [str(p) for p in (BACKEND.parent / ".env", BACKEND / ".env") if p.exists()]
    return {
        "env_files_found": env_files,
        "llm_base_url_host": urlparse(settings.llm_base_url).hostname,
        "llm_model": settings.llm_model_id,
        "llm_api_key_present": bool(settings.llm_api_key),
        "llm_request_timeout_seconds": settings.llm_request_timeout_seconds,
        "llm_max_retries": settings.llm_max_retries,
        "llm_request_token_budget": settings.llm_request_token_budget,
        "chat_history_token_budget": settings.chat_history_token_budget,
        "db_host": db.hostname,
        "db_port": db.port,
        "db_name": (db.path or "").lstrip("/"),
        "db_url_present": bool(settings.postgres_url),
    }


def _install_read_only_engine(settings):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.db import sql_client

    connect_args = {
        "connect_timeout": 10,
        "options": "-c default_transaction_read_only=on",
    }
    if "sslmode=" not in settings.postgres_url:
        connect_args["sslmode"] = settings.db_sslmode
    engine = create_engine(settings.postgres_url, pool_pre_ping=True, connect_args=connect_args)
    sql_client._engine = engine
    sql_client._SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    return engine


def _db_report(engine) -> dict:
    from sqlalchemy import text

    with engine.connect() as conn:
        report = {"transaction_read_only": conn.execute(text("SHOW transaction_read_only")).scalar()}
        for table in ("drugs", "drug_synonyms", "drug_interactions"):
            report[f"count_{table}"] = conn.execute(text(f"SELECT count(*) FROM {table}")).scalar()
        conn.rollback()
    return report


def _in_memory_session(agent, key: str):
    from src.conversations.models import Conversation
    from src.session import session as session_mod
    from src.session.session import Session

    # No persistence: the live check must not write conversation rows.
    session_mod.conv_service.add_message = lambda *_a, **_k: (True, 0)

    s = Session.__new__(Session)
    s.session_id = f"live-{key}"
    s.conversation_id = f"live-{key}"
    s.user_id = "live-check"
    s.agent = agent
    now = datetime.now().isoformat()
    s.conversation = Conversation(conversation_id=s.conversation_id, user_id="live-check",
                                  created_at=now, updated_at=now)
    return s


async def _run_prompt(session, prompt: str, is_doctor: bool) -> dict:
    from src.agent import provider_limits
    from src.agent.langchain_agent import build_system_prompt

    notices: list[dict] = []
    provider_limits.set_wait_notifier(notices.append)  # inherited by the agent's tasks
    earlier_messages = len(session.conversation.messages)

    started = time.time()
    events = []
    async for ev in session.handle_user_query_streamed(prompt, system_prompt=build_system_prompt(is_doctor=is_doctor)):
        events.append(ev)
    elapsed = round(time.time() - started, 1)

    terminal = events[-1] if events else {}
    out = {
        "prompt": prompt,
        "seconds": elapsed,
        "terminal_event": terminal.get("type"),
        "earlier_messages_in_conversation": earlier_messages,
        "wait_notices": [{k: n.get(k) for k in ("retry_after_seconds", "limit")} for n in notices],
        "provider_limits_after": provider_limits.snapshot(),
    }
    if terminal.get("type") == "error":
        out["error"] = {k: terminal.get(k) for k in ("code", "message", "retryable", "retry_after_seconds")}
        return out
    tools_used = []
    for t in terminal.get("tool_executions", []):
        first_line = (t.get("tool_result") or "").strip().split("\n", 1)[0]
        tools_used.append({"tool": t.get("tool_name"), "args": t.get("tool_args"), "status_line": first_line})
    out.update({
        "tools": tools_used,
        "sources": [{"ref": s.get("ref"), "title": s.get("title"), "url": s.get("url")}
                    for s in terminal.get("sources") or []],
        "citation_check": terminal.get("citation_check"),
        "llm_usage": terminal.get("llm_usage"),
        "answer_excerpt": (terminal.get("final_content") or "")[:1500],
        "sources_events_during_stream": sum(1 for e in events if e.get("type") == "sources"),
    })
    return out


async def _run_all(agent, args) -> dict:
    """All prompts in ONE event loop: the model's HTTP client keeps pooled
    connections, which must not outlive the loop they were opened on."""
    wanted = set(args.only.split(",")) if args.only else None
    pair_a, pair_b = [p.strip() for p in args.no_record_pair.split(",", 1)]
    sessions: dict = {}
    results: dict = {}
    for name, prompt, conversation, back_to_back in DEFAULT_PROMPTS:
        if wanted is not None and name not in wanted:
            continue
        if results and args.pause and not back_to_back:
            await asyncio.sleep(args.pause)
        session = sessions.setdefault(conversation, _in_memory_session(agent, conversation))
        text = prompt.format(a=pair_a, b=pair_b)
        # Own task per prompt: its context (wait notifier) does not leak.
        result = await asyncio.create_task(_run_prompt(session, text, is_doctor=args.role == "doctor"))
        result["back_to_back"] = back_to_back
        results[name] = result
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", help="write the JSON report here")
    parser.add_argument("--skip-llm", action="store_true", help="do not call the LLM provider")
    parser.add_argument("--pause", type=float, default=0.0,
                        help="seconds to wait between prompts (lets a per-minute token budget refill)")
    parser.add_argument("--only", help="comma-separated prompt names to run (default: all)")
    parser.add_argument("--role", choices=("doctor", "general"), default="doctor",
                        help="system prompt role (default: doctor)")
    parser.add_argument("--no-record-pair", default=NO_RECORD_PAIR_DEFAULT,
                        help="two drug names with no interaction record, 'A,B'")
    args = parser.parse_args()

    from src.config import settings

    report: dict = {"config": _config_report(settings)}
    try:
        engine = _install_read_only_engine(settings)
        report["database"] = _db_report(engine)
    except Exception as exc:  # report, do not crash
        report["database"] = {"error": type(exc).__name__}

    try:
        from src.agent.agent import MedicalAgent
        from src.agent.langchain_agent import create_medical_agent

        agent = MedicalAgent(create_medical_agent())
        report["agent"] = {"constructed": True}
    except Exception as exc:
        report["agent"] = {"constructed": False, "error": type(exc).__name__}
        agent = None

    if args.skip_llm or agent is None:
        report["llm"] = {"skipped": True}
    else:
        report["llm"] = asyncio.run(_run_all(agent, args))

    text_out = json.dumps(report, ensure_ascii=False, indent=1, default=str)
    if args.out:
        Path(args.out).write_text(text_out, encoding="utf-8")
    print(text_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
