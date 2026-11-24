"""Read-only database access for M-02.

Small and separate on purpose: ``drugs.service.get_drug`` turns some query
errors into ``None`` ("not found"). Here a database problem is ALWAYS raised
as :class:`TimingDataUnavailable` (-> HTTP 503) and never confused with an
unknown drug or with a drug that has no timing text.

Every read runs in a transaction marked ``READ ONLY`` (PostgreSQL rejects
any write in it) and is rolled back afterwards. Only the columns M-02 needs
are selected; interactions, products and other relations are not loaded.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from ..db import sql_client
from ..db.sql_models import DoctorRecord, Drug, DrugReference, UserRecord

# Column width of drugs.half_life (String(1000)); the importer cuts longer text.
HALF_LIFE_STORED_MAX: int = Drug.__table__.c.half_life.type.length


class TimingDataUnavailable(Exception):
    """The database could not be read. Carries only the exception type name."""


@dataclass(frozen=True)
class DrugTimingRow:
    pk: int
    drug_id: str
    name: str
    half_life: Optional[str]
    absorption: Optional[str]


@dataclass(frozen=True)
class ReferenceRow:
    drug_pk: int
    ref_id: str
    ref_type: str
    pubmed_id: Optional[str]
    isbn: Optional[str]
    citation: Optional[str]
    title: Optional[str]
    url: Optional[str]


def _begin_read_only(session) -> None:
    session.execute(text("SET TRANSACTION READ ONLY"))


def _run(fn):
    session = None
    try:
        session = sql_client.get_session()
        _begin_read_only(session)
        result = fn(session)
        session.rollback()
        return result
    except (SQLAlchemyError, OSError, RuntimeError) as exc:
        raise TimingDataUnavailable(type(exc).__name__) from exc
    finally:
        if session is not None:
            try:
                session.close()
            except Exception:  # pragma: no cover - close after a broken connection
                pass


def read_professional_flag(user_id: str) -> Optional[bool]:
    """``None`` = no such user; ``True`` = has a doctor profile (the existing
    ``is_doctor`` definition in ``auth.service``); ``False`` = no profile."""

    def q(session):
        row = session.execute(
            select(UserRecord.id, DoctorRecord.id)
            .outerjoin(DoctorRecord, DoctorRecord.user_pk == UserRecord.id)
            .where(UserRecord.user_id == user_id)
        ).first()
        if row is None:
            return None
        return row[1] is not None

    return _run(q)


def read_timing_data(
    drug_ids: Sequence[str], tokens_of
) -> Tuple[Dict[str, DrugTimingRow], Dict[int, List[ReferenceRow]]]:
    """Rows for the requested ids (missing ids are simply absent) and the
    reference rows of the SAME drugs whose ``ref_id`` occurs as an inline token
    in their stored text. ``tokens_of(text) -> list[str]`` is the parser's
    token extractor."""

    def q(session):
        rows = session.execute(
            select(Drug.id, Drug.drug_id, Drug.name, Drug.half_life, Drug.absorption)
            .where(Drug.drug_id.in_(list(drug_ids)))
        ).all()
        by_id = {
            r.drug_id: DrugTimingRow(pk=r.id, drug_id=r.drug_id, name=r.name,
                                     half_life=r.half_life, absorption=r.absorption)
            for r in rows
        }
        wanted_pks: List[int] = []
        wanted_tokens: List[str] = []
        for row in by_id.values():
            toks = tokens_of(row.half_life or "") + tokens_of(row.absorption or "")
            if toks:
                wanted_pks.append(row.pk)
                wanted_tokens.extend(t for t in toks if t not in wanted_tokens)
        refs: Dict[int, List[ReferenceRow]] = {}
        if wanted_pks:
            ref_rows = session.execute(
                select(DrugReference.drug_pk, DrugReference.ref_id, DrugReference.ref_type,
                       DrugReference.pubmed_id, DrugReference.isbn, DrugReference.citation,
                       DrugReference.title, DrugReference.url)
                .where(DrugReference.drug_pk.in_(wanted_pks), DrugReference.ref_id.in_(wanted_tokens))
            ).all()
            for r in ref_rows:
                refs.setdefault(r.drug_pk, []).append(ReferenceRow(
                    drug_pk=r.drug_pk, ref_id=r.ref_id, ref_type=r.ref_type, pubmed_id=r.pubmed_id or None,
                    isbn=r.isbn or None, citation=r.citation or None, title=r.title or None, url=r.url or None,
                ))
        return by_id, refs

    return _run(q)
