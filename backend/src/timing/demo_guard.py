"""Check the M-02 README demo target BEFORE the app is started (M02-D6).

    uv run python -m src.timing.demo_guard      # exit 0 only for a confirmed synthetic DB

The app reads ``DO_POSTGRES_URL`` from the process and otherwise falls back to
``.env`` / ``POSTGRES_URL``; its startup can write to the database. A demo
started from a new terminal where the variable was not set would therefore
open the application database. This guard reads ONLY the process
environment (never ``.env``) and refuses unless all of these hold:

  * ``DO_POSTGRES_URL`` is set in this process;
  * it is a ``postgresql`` URL without query options, on a loopback host;
  * no libpq redirect (``PGHOSTADDR``, ``PGSERVICE``, ``PGSERVICEFILE``) is
    set in the process or in the ``.env`` files ``run.py`` loads;
  * the database name ends in ``_synth`` and equals ``M02_DEMO_CONFIRM``;
  * connected read-only, the server reports that database and it holds no
    user outside the synthetic test domain.

Exit codes: 0 confirmed; 2 refused (nothing was started or written).
Output never contains the password.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple

SYNTH_EMAIL_DOMAIN = "synthetic-medicallm.org"
CONFIRM_ENV = "M02_DEMO_CONFIRM"
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}
_REDIRECTING_PG_ENV = ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE")
_BACKEND = Path(__file__).resolve().parents[2]


def _dotenv_paths() -> List[Path]:
    """The .env files run.py loads (backend/.env and the repository .env)."""
    return [p for p in (_BACKEND / ".env", _BACKEND.parent / ".env") if p.is_file()]


def _dotenv_keys(path: Path) -> set:
    keys = set()
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                keys.add(line.split("=", 1)[0].replace("export ", "").strip())
    except OSError:
        pass
    return keys


def check_target(environ=None, connect: bool = True) -> Tuple[bool, List[str]]:
    """Return (ok, messages). ``environ`` defaults to ``os.environ``."""
    env = os.environ if environ is None else environ
    raw = env.get("DO_POSTGRES_URL", "")
    if not raw:
        return False, ["DO_POSTGRES_URL is not set in this terminal; set it to the synthetic demo database "
                       "first (the app would otherwise fall back to .env / POSTGRES_URL)."]
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import ArgumentError

    try:
        url = make_url(raw)
    except ArgumentError:
        return False, ["DO_POSTGRES_URL is not a valid database URL."]
    problems: List[str] = []
    # libpq redirects that win over the host in the URL. run.py loads .env into
    # the process before the app connects, so the .env files are checked too
    # (key names only; values are never read out).
    for name in _REDIRECTING_PG_ENV:
        if env.get(name):
            problems.append(f"unset {name}; libpq would use it instead of the host in the URL.")
    for path in _dotenv_paths():
        keys = _dotenv_keys(path)
        for name in _REDIRECTING_PG_ENV:
            if name in keys:
                problems.append(f"{name} is set in {path.name} ({path.parent.name}/); run.py would load it.")
    if url.drivername not in ("postgresql", "postgresql+psycopg2"):
        problems.append(f"driver '{url.drivername}' is not postgresql.")
    if url.query:
        problems.append("URL query options are not allowed (they can change the real host/database).")
    host = (url.host or "").lower()
    if host not in _LOOPBACK:
        problems.append(f"host '{host or '?'}' is not a loopback address.")
    db = url.database or ""
    if not db.endswith("_synth"):
        problems.append(f"database '{db}' does not end with '_synth'.")
    if env.get(CONFIRM_ENV, "") != db:
        problems.append(f"set {CONFIRM_ENV}={db} to confirm this is the throw-away demo database.")
    if problems or not connect:
        return (not problems), problems or [f"target {db} on {host}:{url.port or 5432} passes the static checks."]
    return _check_connected(url, db, host)


def _check_connected(url, db: str, host: str) -> Tuple[bool, List[str]]:
    from sqlalchemy import create_engine, inspect, text

    engine = create_engine(url, connect_args={"connect_timeout": 5,
                                              "options": "-c default_transaction_read_only=on"})
    try:
        with engine.connect() as conn:
            current = conn.execute(text("SELECT current_database()")).scalar_one()
            if current != db:
                return False, [f"server reports database '{current}', expected '{db}'."]
            if "users" in set(inspect(conn).get_table_names()):
                foreign = conn.execute(text("SELECT count(*) FROM users WHERE email NOT LIKE :p"),
                                       {"p": f"%@{SYNTH_EMAIL_DOMAIN}"}).scalar_one()
                if foreign:
                    return False, [f"database '{db}' holds {foreign} non-synthetic user(s); refusing."]
    except Exception as exc:  # type name only: no URL or password
        return False, [f"could not check the target ({type(exc).__name__})."]
    finally:
        engine.dispose()
    return True, [f"OK: synthetic demo target '{db}' on {host}:{url.port or 5432} confirmed."]


def main(argv: Optional[List[str]] = None) -> int:
    ok, messages = check_target()
    for msg in messages:
        print(("" if ok else "REFUSED: ") + msg)
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
