"""Live check of the chat stack WITHOUT writing anything.

What it verifies, each as a separate stage with an explicit ``status``:
  1. config   — which settings are present (never prints secret values)
  2. database — read-only connection: ``transaction_read_only`` must report
                 ``on`` BEFORE anything else is read; then, per table, whether
                 the three core drug tables exist and how many rows they hold
  3. agent    — the LangChain agent object can be constructed (only when the
                 LLM stage was requested)
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

    uv run python scripts/check_live_stack.py --skip-llm      # no provider calls
    uv run python scripts/check_live_stack.py --only normal_chat
    uv run python scripts/check_live_stack.py --pause 65 --out live_check.json

Exit codes (``overall.exit_code`` in the report is always the same value):
  0  every REQUESTED check ran to completion and passed. With ``--skip-llm``
     the LLM stage is reported as ``skipped_by_flag`` — that is NOT evidence
     that the provider works.
  1  a requested check failed or could not run (database unreachable,
     read-only mode not confirmed, missing table, agent construction failed,
     API key missing, provider error, no terminal ``done`` event, no provider
     call recorded, ...). Stages after a failed prerequisite are reported as
     ``not_run_*``, never as passed.
  2  invalid invocation (e.g. unknown or empty ``--only`` selection); rejected
     before any database connection or provider call.

A database with zero drug rows passes the database stage (the check itself
completed) but is reported as ``drug_data: "empty"``: an empty development
database is not verified DrugBank data. Row counts say nothing about clinical
correctness, and "no interaction record" never means "safe".

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

REPORT_VERSION = 2
EXIT_OK, EXIT_FAILED, EXIT_INVALID = 0, 1, 2

NO_RECORD_PAIR_DEFAULT = "Amoxicillin,Loratadine"
DRUG_TABLES = ("drugs", "drug_synonyms", "drug_interactions")

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
SCENARIO_NAMES = tuple(name for name, *_ in DEFAULT_PROMPTS)


class InvalidSelection(ValueError):
    """--only names no runnable scenario, or names unknown scenarios."""


def resolve_selection(only: str | None) -> list[str]:
    """Scenario names to run, in their fixed order.

    ``None`` (flag not given) means all scenarios. An explicitly given value
    must be a comma-separated list of known names: an empty value, an empty
    item or any unknown name is rejected as a whole — never a silent partial
    run and never "run everything".
    """
    if only is None:
        return list(SCENARIO_NAMES)
    items = [item.strip() for item in only.split(",")]
    if not only.strip() or any(not item for item in items):
        raise InvalidSelection("--only must be a comma-separated list of scenario names without empty items")
    unknown = sorted({item for item in items if item not in SCENARIO_NAMES})
    if unknown:
        raise InvalidSelection(f"unknown scenario name(s): {', '.join(unknown)}")
    wanted = set(items)
    return [name for name in SCENARIO_NAMES if name in wanted]


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
    """Read-only database stage. Never writes, never raises.

    Order matters: nothing is read before the session reports
    ``transaction_read_only = on``. Table existence, row count and read
    errors are reported separately: a real zero is ``0``, an unreadable
    count is ``null`` with an error type, never ``0``.
    """
    from sqlalchemy import text

    report: dict = {"status": "error", "connected": False, "transaction_read_only": None}
    try:
        conn_cm = engine.connect()
        conn = conn_cm.__enter__()
    except Exception as exc:
        report["error"] = type(exc).__name__
        return report
    try:
        report["connected"] = True
        try:
            read_only = conn.execute(text("SHOW transaction_read_only")).scalar()
        except Exception as exc:
            report["error"] = type(exc).__name__
            return report
        report["transaction_read_only"] = read_only
        if str(read_only).lower() != "on":
            report["status"] = "read_only_not_confirmed"
            return report  # nothing else is read

        tables: dict = {}
        for table in DRUG_TABLES:
            entry: dict = {"exists": None, "count": None}
            try:
                exists = conn.execute(
                    text("SELECT to_regclass(:name) IS NOT NULL"), {"name": f"public.{table}"}
                ).scalar()
                entry["exists"] = bool(exists)
                if entry["exists"]:
                    count = conn.execute(text(f"SELECT count(*) FROM {table}")).scalar()
                    entry["count"] = int(count) if count is not None else None
                    if entry["count"] is None:
                        entry["error"] = "count_unreadable"
                else:
                    entry["error"] = "table_missing"
            except Exception as exc:
                entry["error"] = type(exc).__name__
                try:
                    conn.rollback()  # leave the failed transaction; session stays read-only
                except Exception:
                    pass
            tables[table] = entry
        report["tables"] = tables

        counts = [t["count"] for t in tables.values()]
        if any(c is None for c in counts):
            report["drug_data"] = "unknown"
            report["status"] = "error"
            report["error"] = "table_check_failed"
        else:
            report["drug_data"] = "present" if all(c > 0 for c in counts) else (
                "empty" if all(c == 0 for c in counts) else "partial")
            report["status"] = "ok"
        report["drug_data_note"] = (
            "row counts only; not a check of clinical content, and an empty "
            "development database is not verified DrugBank data"
        )
        try:
            conn.rollback()
        except Exception:
            pass
        return report
    finally:
        try:
            conn_cm.__exit__(None, None, None)
        except Exception:
            pass


def _build_agent():
    from src.agent.agent import MedicalAgent
    from src.agent.langchain_agent import create_medical_agent

    return MedicalAgent(create_medical_agent())


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


def _scenario_status(out: dict) -> tuple[str, str | None]:
    """A scenario passes only with a terminal ``done`` event, a non-empty
    answer and at least one provider call recorded in ``llm_usage``."""
    terminal = out.get("terminal_event")
    if terminal == "error":
        return "failed", "terminal_error"
    if terminal != "done":
        return "failed", "no_terminal_done"
    if not out.get("answer_excerpt"):
        return "failed", "empty_answer"
    usage = out.get("llm_usage") or {}
    if not isinstance(usage, dict) or not usage.get("calls"):
        return "failed", "no_provider_call_recorded"
    return "ok", None


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
        "events_received": len(events),
        "earlier_messages_in_conversation": earlier_messages,
        "wait_notices": [{k: n.get(k) for k in ("retry_after_seconds", "limit")} for n in notices],
        "provider_limits_after": provider_limits.snapshot(),
    }
    if terminal.get("type") == "error":
        out["error"] = {k: terminal.get(k) for k in ("code", "message", "retryable", "retry_after_seconds")}
        return out
    if terminal.get("type") != "done":
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


async def _run_all(agent, args, selected: list[str] | None = None) -> dict:
    """Selected prompts in ONE event loop: the model's HTTP client keeps
    pooled connections, which must not outlive the loop they were opened on.

    Stops at the first failed scenario (the rest are reported as
    ``not_run_after_failure``) so a provider outage or exhausted quota is not
    hammered with further calls.
    """
    if selected is None:
        selected = resolve_selection(args.only)
    wanted = set(selected)
    pair_a, pair_b = [p.strip() for p in args.no_record_pair.split(",", 1)]
    sessions: dict = {}
    results: dict = {}
    failed = False
    for name, prompt, conversation, back_to_back in DEFAULT_PROMPTS:
        if name not in wanted:
            continue
        if failed:
            results[name] = {"status": "not_run_after_failure"}
            continue
        if results and args.pause and not back_to_back:
            await asyncio.sleep(args.pause)
        text = prompt.format(a=pair_a, b=pair_b)
        try:
            session = sessions.setdefault(conversation, _in_memory_session(agent, conversation))
            # Own task per prompt: its context (wait notifier) does not leak.
            result = await asyncio.create_task(_run_prompt(session, text, is_doctor=args.role == "doctor"))
        except Exception as exc:
            result = {"prompt": text, "terminal_event": None, "exception": type(exc).__name__}
        result["back_to_back"] = back_to_back
        status, reason = _scenario_status(result)
        result["status"] = status
        if reason:
            result["failure_reason"] = reason
            failed = True
        results[name] = result
    return results


def _finish(report: dict, failures: list[str], out_path: str | None) -> int:
    exit_code = EXIT_FAILED if failures else EXIT_OK
    report["overall"] = {
        "status": "failed" if failures else "ok",
        "exit_code": exit_code,
        "failures": failures,
        "llm_provider_verified": report.get("llm", {}).get("status") == "ok",
        "drugbank_data_present": report.get("database", {}).get("drug_data") == "present",
    }
    _emit(report, out_path)
    return exit_code


def _emit(report: dict, out_path: str | None) -> None:
    text_out = json.dumps(report, ensure_ascii=False, indent=1, default=str)
    if out_path:
        Path(out_path).write_text(text_out, encoding="utf-8")
    print(text_out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", help="write the JSON report here")
    parser.add_argument("--skip-llm", action="store_true", help="do not call the LLM provider")
    parser.add_argument("--pause", type=float, default=0.0,
                        help="seconds to wait between prompts (lets a per-minute token budget refill)")
    parser.add_argument("--only", help="comma-separated prompt names to run (default: all); "
                        f"known: {', '.join(SCENARIO_NAMES)}")
    parser.add_argument("--role", choices=("doctor", "general"), default="doctor",
                        help="system prompt role (default: doctor)")
    parser.add_argument("--no-record-pair", default=NO_RECORD_PAIR_DEFAULT,
                        help="two drug names with no interaction record, 'A,B'")
    args = parser.parse_args(argv)

    requested = {"skip_llm": bool(args.skip_llm), "only": args.only}
    # Validate the selection BEFORE any connection or provider call.
    try:
        selected = resolve_selection(args.only)
    except InvalidSelection as exc:
        report = {"report_version": REPORT_VERSION, "requested": requested,
                  "overall": {"status": "invalid_request", "exit_code": EXIT_INVALID, "error": str(exc),
                              "known_scenarios": list(SCENARIO_NAMES)}}
        _emit(report, args.out)
        return EXIT_INVALID
    requested["scenarios"] = [] if args.skip_llm else selected

    from src.config import settings

    report: dict = {"report_version": REPORT_VERSION, "requested": requested,
                    "config": _config_report(settings)}
    failures: list[str] = []

    # --- database (prerequisite for everything after it) -------------------
    try:
        engine = _install_read_only_engine(settings)
        report["database"] = _db_report(engine)
    except Exception as exc:  # report, do not crash
        report["database"] = {"status": "error", "connected": False, "error": type(exc).__name__}
    if report["database"].get("status") != "ok":
        failures.append(f"database:{report['database'].get('status')}")

    # --- agent + llm ----------------------------------------------------------
    if args.skip_llm:
        report["agent"] = {"status": "not_attempted", "reason": "skip_llm_flag"}
        report["llm"] = {"status": "skipped_by_flag",
                         "note": "--skip-llm: the provider was not called; this is not evidence that it works"}
    elif failures:
        report["agent"] = {"status": "not_attempted", "reason": "database_prerequisite_failed"}
        report["llm"] = {"status": "not_run_prerequisite_failed", "reason": "database"}
        failures.append("llm:not_run_prerequisite_failed")
    elif not settings.llm_api_key:
        report["agent"] = {"status": "not_attempted", "reason": "llm_api_key_missing"}
        report["llm"] = {"status": "not_run_missing_key"}
        failures.append("llm:not_run_missing_key")
    else:
        try:
            agent = _build_agent()
            report["agent"] = {"status": "ok", "constructed": True}
        except Exception as exc:
            report["agent"] = {"status": "error", "constructed": False, "error": type(exc).__name__}
            agent = None
            failures.append("agent:error")
        if agent is None:
            report["llm"] = {"status": "not_run_prerequisite_failed", "reason": "agent"}
            failures.append("llm:not_run_prerequisite_failed")
        else:
            try:
                scenarios = asyncio.run(_run_all(agent, args, selected))
                bad = [n for n, r in scenarios.items() if r.get("status") != "ok"]
                report["llm"] = {"status": "failed" if bad else "ok", "scenarios": scenarios}
                failures.extend(f"llm:{n}:{scenarios[n].get('failure_reason') or scenarios[n].get('status')}"
                                for n in bad)
            except Exception as exc:
                report["llm"] = {"status": "failed", "error": type(exc).__name__}
                failures.append("llm:error")

    return _finish(report, failures, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
