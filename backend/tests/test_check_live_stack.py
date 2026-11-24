"""R1-O2: scripts/check_live_stack.py must not report a failed or skipped
check as a success.

Fully offline and synthetic: the database engine, the agent factory and the
chat session are replaced by in-test fakes (no network, no database, no API
key). Every fake is installed with ``monkeypatch`` and therefore removed after
each test. The script is driven through ``main()`` with ``sys.argv`` so the
same tests also run against older versions of the script.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_live_stack.py"
ALL_SCENARIOS = [
    "normal_chat", "single_drug", "two_drug_interaction", "follow_up_same_conversation",
    "unknown_drug", "no_record_pair", "pubmed_three_articles", "back_to_back_first",
    "back_to_back_second",
]
# Synthetic, secret-looking values that must never reach the report or logs.
FAKE_KEY = "gsk_SYNTHETICKEY_do_not_print_7f3a"
FAKE_DB_PASSWORD = "SyntheticDbPw_do_not_print_91"
FAKE_DB_URL = f"postgresql://synth_user:{FAKE_DB_PASSWORD}@127.0.0.1:1/synthetic_live_synth"


@pytest.fixture
def script(monkeypatch):
    """Load the script as a module (it chdirs to backend/ at import time)."""
    cwd = os.getcwd()
    spec = importlib.util.spec_from_file_location("check_live_stack_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    finally:
        os.chdir(cwd)
    return module


# --------------------------------------------------------------------------- fakes

class FakeResult:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value

    def scalar_one(self):
        return self.value


class FakeConn:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, stmt, params=None):
        sql = str(stmt)
        self.db.statements.append(sql)
        if "SHOW transaction_read_only" in sql:
            return FakeResult(self.db.read_only)
        if "to_regclass" in sql:
            table = (params or {}).get("name", "").split(".")[-1]
            return FakeResult(table in self.db.counts)
        if "count(*)" in sql:
            table = sql.rsplit(" ", 1)[-1].strip()
            if table in self.db.count_errors:
                raise self.db.count_errors[table]
            if table not in self.db.counts:
                raise RuntimeError("UndefinedTable")
            return FakeResult(self.db.counts[table])
        raise AssertionError(f"unexpected SQL in live check: {sql}")

    def rollback(self):
        self.db.rollbacks += 1


class FakeDB:
    """Records every statement; never writes anything anywhere."""

    def __init__(self, *, read_only="on", counts=None, count_errors=None, connect_error=None):
        self.read_only = read_only
        self.counts = {"drugs": 17, "drug_synonyms": 33, "drug_interactions": 28} if counts is None else counts
        self.count_errors = count_errors or {}
        self.connect_error = connect_error
        self.statements: list[str] = []
        self.rollbacks = 0
        self.installs = 0

    def connect(self):
        if self.connect_error is not None:
            raise self.connect_error
        return FakeConn(self)

    def count_queries(self):
        return [s for s in self.statements if "count(*)" in s]


def _done_event(content="Synthetic greeting answer.", calls=1):
    return {
        "type": "done", "final_content": content, "sources": [], "tool_executions": [],
        "citation_check": {"unknown_refs": [], "uncited_lines": 0},
        "llm_usage": {"calls": calls, "input_tokens": 10 * calls, "output_tokens": 5 * calls, "per_call": []},
        "persisted": True, "request_id": "synthetic",
    }


class FakeConversation:
    def __init__(self):
        self.messages = []


class FakeSession:
    def __init__(self, events):
        self._events = events
        self.conversation = FakeConversation()

    async def handle_user_query_streamed(self, prompt, system_prompt=None):
        for ev in self._events:
            yield ev


class Harness:
    """Wires the fakes into the script and the app modules it imports."""

    def __init__(self, monkeypatch, script, *, db=None, api_key=FAKE_KEY, agent_error=None, events=None):
        self.script = script
        self.db = db or FakeDB()
        self.agent_builds = 0
        self.sessions_created: list[str] = []
        self.events = events or {}

        from src.config import settings

        monkeypatch.setattr(settings, "do_model_access_key", api_key)
        monkeypatch.setattr(settings, "do_postgres_url", FAKE_DB_URL)

        def _install(_settings):
            self.db.installs += 1
            return self.db

        monkeypatch.setattr(script, "_install_read_only_engine", _install)

        import src.agent.agent as agent_mod
        import src.agent.langchain_agent as lc_mod

        def _create(*_a, **_k):
            self.agent_builds += 1
            if agent_error is not None:
                raise agent_error
            return object()

        monkeypatch.setattr(lc_mod, "create_medical_agent", _create)
        monkeypatch.setattr(agent_mod, "MedicalAgent", lambda inner: ("synthetic-agent", inner))

        def _session(agent, key):
            self.sessions_created.append(key)
            return _SessionByKey(self, key)

        monkeypatch.setattr(script, "_in_memory_session", _session)

    def run(self, monkeypatch, capsys, *argv):
        monkeypatch.setattr(sys, "argv", ["check_live_stack.py", *argv])
        try:
            code = self.script.main()
        except SystemExit as exc:  # argparse errors
            code = exc.code
        captured = capsys.readouterr()
        try:
            report = json.loads(captured.out)
        except json.JSONDecodeError:
            report = None
        return code, report, captured.out + captured.err


class _SessionByKey(FakeSession):
    """Answers each prompt with the events configured for its scenario."""

    def __init__(self, harness, key):
        super().__init__([])
        self.harness = harness
        self.key = key

    async def handle_user_query_streamed(self, prompt, system_prompt=None):
        script = self.harness.script
        name = next(n for n, p, *_ in script.DEFAULT_PROMPTS
                    if p.format(a="Amoxicillin", b="Loratadine") == prompt)
        self.harness.provider_calls = getattr(self.harness, "provider_calls", []) + [name]
        for ev in self.harness.events.get(name, [_done_event()]):
            yield ev


def _llm_scenarios(report):
    llm = report.get("llm") or {}
    return llm.get("scenarios", llm)


# ======================================================================
# The four audited defects (exit code 0 on failure in f4ab516)
# ======================================================================

def test_db_error_with_skip_llm_exits_nonzero(script, monkeypatch, capsys):
    h = Harness(monkeypatch, script, db=FakeDB(connect_error=ConnectionError("synthetic: refused")))
    code, report, _ = h.run(monkeypatch, capsys, "--skip-llm")
    assert code == 1
    assert report["database"]["status"] == "error"
    assert report["database"]["connected"] is False
    assert report["llm"]["status"] == "skipped_by_flag"
    assert report["overall"]["exit_code"] == code
    assert report["overall"]["llm_provider_verified"] is False


def test_unknown_only_is_rejected_before_any_connection(script, monkeypatch, capsys):
    h = Harness(monkeypatch, script)
    code, report, _ = h.run(monkeypatch, capsys, "--only", "does_not_exist")
    assert code == 2
    assert report["overall"]["status"] == "invalid_request"
    assert "does_not_exist" in report["overall"]["error"]
    assert h.db.installs == 0 and h.db.statements == []
    assert h.agent_builds == 0 and h.sessions_created == []


def test_agent_construction_failure_exits_nonzero(script, monkeypatch, capsys):
    h = Harness(monkeypatch, script, agent_error=RuntimeError("synthetic agent failure"))
    code, report, _ = h.run(monkeypatch, capsys, "--only", "normal_chat")
    assert code == 1
    assert report["agent"]["status"] == "error"
    assert report["llm"]["status"] == "not_run_prerequisite_failed"
    assert h.sessions_created == []
    assert report["overall"]["exit_code"] == 1


def test_terminal_error_event_exits_nonzero(script, monkeypatch, capsys):
    error_event = {"type": "error", "code": "llm_unavailable", "message": "synthetic provider failure",
                   "retryable": True, "request_id": "synthetic"}
    h = Harness(monkeypatch, script, events={"normal_chat": [error_event]})
    code, report, _ = h.run(monkeypatch, capsys, "--only", "normal_chat")
    assert code == 1
    scenario = _llm_scenarios(report)["normal_chat"]
    assert scenario["status"] == "failed" and scenario["failure_reason"] == "terminal_error"
    assert scenario["error"]["code"] == "llm_unavailable"
    assert report["llm"]["status"] == "failed"
    assert report["overall"]["exit_code"] == 1


# ======================================================================
# Scenario selection
# ======================================================================

@pytest.mark.parametrize(
    "only",
    ["", " ", ",", "normal_chat,", ",normal_chat", "normal_chat,,single_drug",
     "normal_chat,does_not_exist", "NORMAL_CHAT"],
    ids=["empty", "blank", "comma", "trailing-comma", "leading-comma", "double-comma",
         "valid-plus-unknown", "wrong-case"],
)
def test_invalid_selection_makes_no_db_or_provider_call(script, monkeypatch, capsys, only):
    h = Harness(monkeypatch, script)
    code, report, _ = h.run(monkeypatch, capsys, "--only", only)
    assert code == 2
    assert report["overall"]["exit_code"] == 2
    assert h.db.installs == 0 and h.db.statements == []
    assert h.agent_builds == 0 and h.sessions_created == []


def test_valid_selection_runs_exactly_those_scenarios_in_order(script, monkeypatch, capsys):
    h = Harness(monkeypatch, script)
    code, report, _ = h.run(monkeypatch, capsys, "--only", "two_drug_interaction, normal_chat")
    assert code == 0
    assert list(_llm_scenarios(report)) == ["normal_chat", "two_drug_interaction"]
    assert report["requested"]["scenarios"] == ["normal_chat", "two_drug_interaction"]


# ======================================================================
# Read-only guard and data availability
# ======================================================================

@pytest.mark.parametrize("read_only", ["off", None, "0"])
def test_read_only_not_confirmed_reads_nothing_and_calls_no_provider(script, monkeypatch, capsys, read_only):
    h = Harness(monkeypatch, script, db=FakeDB(read_only=read_only))
    code, report, _ = h.run(monkeypatch, capsys, "--only", "normal_chat")
    assert code == 1
    assert report["database"]["status"] == "read_only_not_confirmed"
    assert h.db.statements == ["SHOW transaction_read_only"]
    assert h.db.count_queries() == []
    assert h.agent_builds == 0 and h.sessions_created == []
    assert report["llm"]["status"] == "not_run_prerequisite_failed"


def test_db_failure_stops_before_provider_calls(script, monkeypatch, capsys):
    h = Harness(monkeypatch, script, db=FakeDB(connect_error=OSError("synthetic")))
    code, report, _ = h.run(monkeypatch, capsys)
    assert code == 1
    assert h.agent_builds == 0 and h.sessions_created == []
    assert report["llm"]["status"] == "not_run_prerequisite_failed"


def test_empty_database_is_zero_not_error_and_not_verified_data(script, monkeypatch, capsys):
    h = Harness(monkeypatch, script, db=FakeDB(counts={"drugs": 0, "drug_synonyms": 0, "drug_interactions": 0}))
    code, report, _ = h.run(monkeypatch, capsys, "--skip-llm")
    assert code == 0
    db = report["database"]
    assert db["status"] == "ok" and db["drug_data"] == "empty"
    assert {t: v["count"] for t, v in db["tables"].items()} == {
        "drugs": 0, "drug_synonyms": 0, "drug_interactions": 0}
    assert all(v["exists"] is True for v in db["tables"].values())
    assert report["overall"]["drugbank_data_present"] is False


def test_unreadable_count_is_null_with_error_not_zero(script, monkeypatch, capsys):
    db = FakeDB(count_errors={"drug_interactions": RuntimeError("synthetic read failure")})
    h = Harness(monkeypatch, script, db=db)
    code, report, _ = h.run(monkeypatch, capsys, "--skip-llm")
    assert code == 1
    entry = report["database"]["tables"]["drug_interactions"]
    assert entry["count"] is None and entry["error"] == "RuntimeError"
    assert report["database"]["drug_data"] == "unknown"
    assert report["database"]["status"] == "error"


def test_missing_table_is_reported_separately(script, monkeypatch, capsys):
    h = Harness(monkeypatch, script, db=FakeDB(counts={"drugs": 5, "drug_synonyms": 5}))
    code, report, _ = h.run(monkeypatch, capsys, "--skip-llm")
    assert code == 1
    entry = report["database"]["tables"]["drug_interactions"]
    assert entry == {"exists": False, "count": None, "error": "table_missing"}
    assert not any("drug_interactions" in s and "count(*)" in s for s in h.db.statements)


def test_partial_data_is_labelled(script, monkeypatch, capsys):
    h = Harness(monkeypatch, script, db=FakeDB(counts={"drugs": 5, "drug_synonyms": 0, "drug_interactions": 0}))
    code, report, _ = h.run(monkeypatch, capsys, "--skip-llm")
    assert code == 0 and report["database"]["drug_data"] == "partial"


# ======================================================================
# Successful runs, deliberate skip, missing key
# ======================================================================

def test_healthy_full_run_passes(script, monkeypatch, capsys):
    h = Harness(monkeypatch, script)
    code, report, _ = h.run(monkeypatch, capsys)
    assert code == 0
    assert report["overall"] == {
        "status": "ok", "exit_code": 0, "failures": [],
        "llm_provider_verified": True, "drugbank_data_present": True,
    }
    scenarios = _llm_scenarios(report)
    assert list(scenarios) == ALL_SCENARIOS
    assert all(s["status"] == "ok" and s["terminal_event"] == "done" for s in scenarios.values())
    assert all(s["llm_usage"]["calls"] >= 1 for s in scenarios.values())
    assert report["database"]["transaction_read_only"] == "on"
    assert report["agent"]["status"] == "ok"


def test_skip_llm_succeeds_but_never_claims_the_provider_works(script, monkeypatch, capsys):
    h = Harness(monkeypatch, script)
    code, report, _ = h.run(monkeypatch, capsys, "--skip-llm")
    assert code == 0
    assert report["llm"]["status"] == "skipped_by_flag"
    assert report["agent"]["status"] == "not_attempted"
    assert report["overall"]["llm_provider_verified"] is False
    assert h.agent_builds == 0 and h.sessions_created == []
    assert report["requested"]["scenarios"] == []


def test_missing_api_key_is_a_failure_not_a_skip(script, monkeypatch, capsys):
    h = Harness(monkeypatch, script, api_key="")
    code, report, _ = h.run(monkeypatch, capsys, "--only", "normal_chat")
    assert code == 1
    assert report["llm"]["status"] == "not_run_missing_key"
    assert report["llm"]["status"] != "skipped_by_flag"
    assert h.agent_builds == 0 and h.sessions_created == []


# ======================================================================
# Streams that never reach a usable terminal "done"
# ======================================================================

@pytest.mark.parametrize(
    "events, reason",
    [
        ([{"type": "content", "content": "partial"}], "no_terminal_done"),
        ([{"type": "content", "content": "partial"}, {"type": "heartbeat"}], "no_terminal_done"),
        ([], "no_terminal_done"),
        ([_done_event(content="")], "empty_answer"),
        ([_done_event(calls=0)], "no_provider_call_recorded"),
    ],
    ids=["content-only", "ends-on-heartbeat", "no-events", "empty-answer", "no-provider-usage"],
)
def test_stream_without_usable_done_fails(script, monkeypatch, capsys, events, reason):
    h = Harness(monkeypatch, script, events={"normal_chat": events})
    code, report, _ = h.run(monkeypatch, capsys, "--only", "normal_chat")
    assert code == 1
    scenario = _llm_scenarios(report)["normal_chat"]
    assert scenario["status"] == "failed" and scenario["failure_reason"] == reason
    assert report["overall"]["llm_provider_verified"] is False


def test_first_failure_stops_further_provider_calls(script, monkeypatch, capsys):
    error_event = {"type": "error", "code": "llm_daily_quota", "message": "synthetic", "retryable": False}
    h = Harness(monkeypatch, script, events={"single_drug": [error_event]})
    code, report, _ = h.run(monkeypatch, capsys, "--only", "normal_chat,single_drug,unknown_drug")
    assert code == 1
    scenarios = _llm_scenarios(report)
    assert scenarios["normal_chat"]["status"] == "ok"
    assert scenarios["single_drug"]["status"] == "failed"
    assert scenarios["unknown_drug"] == {"status": "not_run_after_failure"}
    assert h.provider_calls == ["normal_chat", "single_drug"]


def test_exception_inside_a_scenario_is_a_failure(script, monkeypatch, capsys):
    class _Boom(FakeSession):
        async def handle_user_query_streamed(self, prompt, system_prompt=None):
            raise RuntimeError("synthetic crash with " + FAKE_KEY)
            yield  # pragma: no cover

    h = Harness(monkeypatch, script)
    monkeypatch.setattr(script, "_in_memory_session", lambda agent, key: _Boom([]))
    code, report, output = h.run(monkeypatch, capsys, "--only", "normal_chat")
    assert code == 1
    scenario = _llm_scenarios(report)["normal_chat"]
    assert scenario["status"] == "failed" and scenario["exception"] == "RuntimeError"
    assert FAKE_KEY not in output


# ======================================================================
# Secrets and report/exit-code consistency
# ======================================================================

@pytest.mark.parametrize(
    "harness_kwargs, argv",
    [
        ({}, []),
        ({}, ["--skip-llm"]),
        ({"db": FakeDB(connect_error=ConnectionError(f"could not connect to {FAKE_DB_URL}"))}, []),
        ({"db": FakeDB(read_only="off")}, []),
        ({"agent_error": RuntimeError(f"bad key {FAKE_KEY}")}, []),
        ({"events": {"normal_chat": [{"type": "error", "code": "llm_auth", "message": "synthetic"}]}}, []),
    ],
    ids=["healthy", "skip-llm", "db-error", "read-only-off", "agent-error", "provider-error"],
)
def test_report_contains_no_secrets_and_exit_code_matches(script, monkeypatch, capsys, tmp_path,
                                                         harness_kwargs, argv):
    h = Harness(monkeypatch, script, **harness_kwargs)
    out_file = tmp_path / "report.json"
    code, report, output = h.run(monkeypatch, capsys, *argv, "--out", str(out_file))
    written = out_file.read_text(encoding="utf-8")
    for blob in (output, written):
        assert FAKE_KEY not in blob
        assert FAKE_DB_PASSWORD not in blob
        assert "Authorization" not in blob and "Bearer " not in blob
        assert "postgresql://" not in blob
    assert json.loads(written) == report
    assert report["overall"]["exit_code"] == code
    assert (code == 0) == (report["overall"]["status"] == "ok") == (report["overall"]["failures"] == [])
    assert report["config"]["llm_api_key_present"] is True
    assert report["config"]["db_name"] == "synthetic_live_synth"
