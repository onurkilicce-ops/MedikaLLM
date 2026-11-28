"""
Pytest configuration shared across the suite.

Two design choices worth flagging:

1. **No real database in the unit-test layer.** The unit tests under
   `tests/unit/` exercise pure functions (email canonicalisation, password
   validators, etc.) and never touch SQLAlchemy. They run fast even on a
   developer laptop with no Postgres around.

2. **Lazy app construction for integration tests.** Importing `src.main`
   eagerly initialises the LLM agent and connects to the database, both of
   which we don't want in CI. Tests that need the real FastAPI app pull it
   in inside their fixture so the unit-test files don't pay the cost.

3. **Stub heavyweight ORM imports.** `src.db.sql_models` imports
   `pgvector.sqlalchemy.Vector`. CI doesn't install pgvector (or
   sentence-transformers, langchain, etc.) for the unit suite, so we
   slot a tiny stub into `sys.modules` before any test module imports
   the project. Anything that needs a real Vector column is in the
   integration suite, which has its own gating import-skip.
"""
import importlib
import os
import sys
import types
from pathlib import Path

import pytest

# Add backend/ to the path so `from src import ...` works from anywhere.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_TESTS_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_BACKEND_ROOT))


# --- Strict mode (CI) --------------------------------------------------------
# MEDICALLM_STRICT_TESTS=1 means "this environment is supposed to have the
# full locked dependency set, the synthetic PostgreSQL and the tokenizer
# data". In that mode:
#   * the real packages must import (no pgvector stub, no missing openai /
#     langchain) — checked before any test module is imported;
#   * every skip (test-level or module/conftest-level importorskip) is
#     reported as a FAILURE, so a missing dependency can never turn into a
#     green run with fewer tests;
#   * when the whole suite is collected, every tests/**/test_*.py file must
#     contribute at least one test (catches a module that silently vanished).
# Locally (unset) the historical skip behaviour is unchanged.
STRICT_TESTS = os.getenv("MEDICALLM_STRICT_TESTS") == "1"
_STRICT_REQUIRED_IMPORTS = (
    "openai",
    "langchain",
    "langchain_core",
    "langchain_openai",
    "langgraph",
    "pgvector.sqlalchemy",
    "tiktoken",
    "psycopg2",
)

if STRICT_TESTS:
    _missing = []
    for _name in _STRICT_REQUIRED_IMPORTS:
        try:
            importlib.import_module(_name)
        except Exception as exc:  # pragma: no cover - only fails in a broken env
            _missing.append(f"{_name}: {type(exc).__name__}: {exc}")
    if _missing:
        raise pytest.UsageError(
            "MEDICALLM_STRICT_TESTS=1 but required packages do not import "
            "(install with `uv sync --locked`):\n  " + "\n  ".join(_missing)
        )
    if not os.getenv("MEDICALLM_SYNTHETIC_PG_URL"):
        raise pytest.UsageError(
            "MEDICALLM_STRICT_TESTS=1 requires MEDICALLM_SYNTHETIC_PG_URL "
            "(a throw-away *_synth database) so the PostgreSQL tests run."
        )


def _strict_skip_message(longrepr) -> str:
    reason = longrepr[2] if isinstance(longrepr, tuple) and len(longrepr) == 3 else str(longrepr)
    return f"MEDICALLM_STRICT_TESTS=1: a skip is a failure in this environment ({reason})"


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if STRICT_TESTS and report.skipped and not hasattr(report, "wasxfail"):
        report.longrepr = _strict_skip_message(report.longrepr)
        report.outcome = "failed"


@pytest.hookimpl(hookwrapper=True)
def pytest_make_collect_report(collector):
    outcome = yield
    report = outcome.get_result()
    if STRICT_TESTS and report.skipped:
        report.longrepr = _strict_skip_message(report.longrepr)
        report.outcome = "failed"


def pytest_collection_finish(session):
    if not STRICT_TESTS:
        return
    config = session.config
    if config.option.keyword or config.option.markexpr or getattr(config.option, "deselect", None):
        return
    roots = {Path(a.split("::")[0]).resolve() for a in config.args}
    if not roots <= {_TESTS_ROOT, _BACKEND_ROOT}:
        return  # a subset was requested explicitly
    collected = {Path(str(item.path)).resolve() for item in session.items}
    on_disk = {p.resolve() for p in _TESTS_ROOT.rglob("test_*.py")}
    missing = sorted(str(p.relative_to(_TESTS_ROOT)) for p in on_disk - collected)
    if missing:
        raise pytest.UsageError(
            "MEDICALLM_STRICT_TESTS=1: these test modules collected no tests: " + ", ".join(missing)
        )


def _stub_module(name: str, attrs: dict | None = None) -> None:
    """Insert a placeholder module into sys.modules so `from X import Y`
    resolves without the real package being installed."""
    if name in sys.modules:
        return
    mod = types.ModuleType(name)
    for k, v in (attrs or {}).items():
        setattr(mod, k, v)
    sys.modules[name] = mod


# pgvector — sql_models imports `from pgvector.sqlalchemy import Vector`.
# We provide a no-op SQLAlchemy TypeDecorator-equivalent so the import
# succeeds and the metadata builds. None of the unit tests touch a
# Vector column.
try:
    import pgvector  # noqa: F401
except ImportError:
    if STRICT_TESTS:  # never stub in strict mode (already reported above)
        raise
    from sqlalchemy.types import UserDefinedType

    class _StubVector(UserDefinedType):
        cache_ok = True

        def __init__(self, dim=None):
            self.dim = dim

        def get_col_spec(self, **kw):
            return "VECTOR"

    _stub_module("pgvector")
    _stub_module("pgvector.sqlalchemy", {"Vector": _StubVector})


# Provide harmless test defaults for required env vars so importing the
# config module never blows up in CI. Real values come from secrets when
# a test actually exercises an external service (we don't, in this suite).
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-not-for-production-use-only-tests")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault(
    "DO_POSTGRES_URL",
    "postgresql://test:test@localhost:5432/medicallm_test",
)
