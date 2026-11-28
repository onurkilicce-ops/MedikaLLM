"""Read-only M-02 data inventory: how much Tmax / half-life text exists and
how much of it the M-02 rules (``src/timing/RULES.md``) can structure.

    uv run python scripts/audit_m02_data.py                 # uses DO_POSTGRES_URL
    uv run python scripts/audit_m02_data.py --out m02_inventory.json

Safety:
  * the connection is opened with ``default_transaction_read_only=on`` and
    ``SHOW transaction_read_only`` must answer ``on`` before anything else is
    read; otherwise nothing is read and the exit code is 1;
  * only ``drugs`` (6 text columns + ids) and ``drug_references (drug_pk,
    ref_id)`` are read - never users, patients, conversations or interactions;
  * the report holds counts only: no drug text, no names, no connection URL,
    host, user or password. Errors are reported by exception type only.

Exit codes: 0 = inventory complete; 1 = database not reachable / read-only not
confirmed / read failed; 2 = invalid arguments.

Counts describe the stored text and the rule outcome only. "Parsed" means the
M-02 rules produced a value without a review flag; it is not a statement that
the value is clinically correct (no expert check has been done).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

REPORT_VERSION = 1
PARSED_FIELDS = ("half_life", "absorption")
COUNT_ONLY_FIELDS = ("metabolism", "clearance", "route_of_elimination")


def _engine(url: str, sslmode: Optional[str]):
    from sqlalchemy import create_engine

    connect_args = {"connect_timeout": 10, "options": "-c default_transaction_read_only=on"}
    if sslmode and "sslmode=" not in url:
        connect_args["sslmode"] = sslmode
    return create_engine(url, pool_pre_ping=True, connect_args=connect_args)


def _empty_counter() -> Dict[str, int]:
    return {"total": 0, "empty": 0, "placeholder": 0, "text_present": 0}


def build_inventory(conn) -> dict:
    from sqlalchemy import text

    from src.timing import calc
    from src.timing.parser import DURATION_RE, HALF_LIFE_KW, TMAX_KW, is_placeholder, parse_field, reference_tokens
    from src.timing.repository import HALF_LIFE_STORED_MAX

    refs: Dict[int, set] = {}
    for drug_pk, ref_id in conn.execute(text("SELECT drug_pk, ref_id FROM drug_references WHERE ref_id <> ''")):
        refs.setdefault(drug_pk, set()).add(ref_id)

    fields: Dict[str, dict] = {f: _empty_counter() for f in PARSED_FIELDS + COUNT_ONLY_FIELDS}
    parsed: Dict[str, dict] = {
        f: {"field_status": Counter(), "measurements": 0, "measurements_review_required": 0,
            "measurement_review_reasons": Counter(), "review_item_reasons": Counter(),
            "measure_basis": Counter(), "keyword_present": 0, "keyword_present_but_no_measurement": 0,
            "fields_with_inline_reference_tokens": 0,
            "measurement_reference_status": Counter(),
            "measurements_with_any_condition": 0, "measurements_by_condition": Counter(),
            "measurements_with_conflict_group": 0}
        for f in PARSED_FIELDS
    }
    derived = {"computed": 0, "not_computed": 0, "not_computed_reasons": Counter()}
    half_life_len = {"exactly_stored_max": 0, "over_stored_max": 0, "stored_max": HALF_LIFE_STORED_MAX}
    duration_expr = {f: 0 for f in COUNT_ONLY_FIELDS}
    keywords = {"half_life": HALF_LIFE_KW, "absorption": TMAX_KW}
    total = 0

    rows = conn.execution_options(stream_results=True).execute(text(
        "SELECT id, half_life, absorption, metabolism, clearance, route_of_elimination FROM drugs ORDER BY id"))
    for row in rows:
        total += 1
        values = {"half_life": row.half_life, "absorption": row.absorption, "metabolism": row.metabolism,
                  "clearance": row.clearance, "route_of_elimination": row.route_of_elimination}
        for f, value in values.items():
            c = fields[f]
            c["total"] += 1
            if value is None or not value.strip():
                c["empty"] += 1
            elif is_placeholder(value):
                c["placeholder"] += 1
            else:
                c["text_present"] += 1
                if f in COUNT_ONLY_FIELDS and DURATION_RE.search(value):
                    duration_expr[f] += 1
        hl = row.half_life or ""
        if len(hl) == HALF_LIFE_STORED_MAX:
            half_life_len["exactly_stored_max"] += 1
        elif len(hl) > HALF_LIFE_STORED_MAX:
            half_life_len["over_stored_max"] += 1

        drug_refs = refs.get(row.id, set())
        for f in PARSED_FIELDS:
            value = values[f]
            fp = parse_field(f, value, stored_max_length=HALF_LIFE_STORED_MAX if f == "half_life" else None)
            p = parsed[f]
            p["field_status"][fp.status] += 1
            if value and any(k.search(value) for k in keywords[f]):
                p["keyword_present"] += 1
                if not fp.values:
                    p["keyword_present_but_no_measurement"] += 1
            if value and reference_tokens(value):
                p["fields_with_inline_reference_tokens"] += 1
            for r in fp.reviews:
                p["review_item_reasons"][r.reason] += 1
            for v in fp.values:
                p["measurements"] += 1
                p["measure_basis"][v.basis] += 1
                if v.review_reasons:
                    p["measurements_review_required"] += 1
                for reason in v.review_reasons:
                    p["measurement_review_reasons"][reason] += 1
                if v.conflict_group:
                    p["measurements_with_conflict_group"] += 1
                status, _, _ = calc.reference_status(v.reference_tokens, drug_refs)
                p["measurement_reference_status"][status] += 1
                cats = [k for k in ("route", "formulation", "population", "food_state", "dosing", "phase",
                                    "matrix", "kinetics") if v.conditions[k]]
                if v.conditions["analyte"] != "not_stated":
                    cats.append("analyte")
                if cats:
                    p["measurements_with_any_condition"] += 1
                for k in cats:
                    p["measurements_by_condition"][k] += 1
                if f == "half_life":
                    d = calc.five_half_lives(v, fp.flags)
                    derived[d["status"]] += 1
                    for reason in d["not_computed_reasons"]:
                        derived["not_computed_reasons"][reason] += 1

    def plain(obj):
        if isinstance(obj, Counter):
            return dict(sorted(obj.items()))
        if isinstance(obj, dict):
            return {k: plain(v) for k, v in obj.items()}
        return obj

    return {
        "drugs_total": total,
        "fields": fields,
        "half_life_length": half_life_len,
        "parsed_fields": plain(parsed),
        "derived_five_half_lives": plain(derived),
        "count_only_fields_with_duration_expression_not_parsed": duration_expr,
        "drugs_with_reference_rows": len(refs),
    }


def run(url: Optional[str], sslmode: Optional[str]) -> dict:
    from sqlalchemy import text

    from src.timing.parser import PARSER_VERSION

    report: dict = {"report_version": REPORT_VERSION, "parser_version": PARSER_VERSION,
                    "database": {"connected": False, "transaction_read_only": None},
                    "status": "error", "exit_code": 1}
    if not url:
        report["error"] = "no_database_url"
        return report
    engine = None
    try:
        engine = _engine(url, sslmode)
        with engine.connect() as conn:
            report["database"]["connected"] = True
            read_only = conn.execute(text("SHOW transaction_read_only")).scalar()
            report["database"]["transaction_read_only"] = read_only
            if read_only != "on":
                report["error"] = "read_only_not_confirmed"
                return report
            report["inventory"] = build_inventory(conn)
            conn.rollback()
        report["status"] = "ok"
        report["exit_code"] = 0
    except Exception as exc:  # report the type only: no URL, host or SQL text
        report["error"] = type(exc).__name__
    finally:
        if engine is not None:
            engine.dispose()
    return report


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", help="also write the JSON report to this file")
    args = parser.parse_args(argv)

    import os

    url = os.getenv("M02_AUDIT_DB_URL") or os.getenv("DO_POSTGRES_URL") or os.getenv("POSTGRES_URL")
    if not url:
        try:
            from src.config import settings

            url = settings.postgres_url
        except Exception:
            url = None
    report = run(url, os.getenv("DB_SSLMODE"))
    out = json.dumps(report, indent=2, ensure_ascii=False)
    print(out)
    if args.out:
        Path(args.out).write_text(out + "\n", encoding="utf-8")
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
