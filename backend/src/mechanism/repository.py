"""Read-only database access for M-03.

Same contract as M-02 (``timing.repository``): every read runs in a
``READ ONLY`` transaction that is rolled back, and any database problem is
raised as ``TimingDataUnavailable`` (-> 503), never as "not found".
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

from sqlalchemy import and_, or_, select

from ..db.sql_models import Drug, DrugCarrier, DrugEnzyme, DrugInteraction, DrugSynonym, DrugTransporter
from ..timing.repository import TimingDataUnavailable, _run  # noqa: F401  (re-exported for the router)
from .rules import ProteinRow



@dataclass(frozen=True)
class DrugMechanismRow:
    pk: int
    drug_id: str
    name: str
    route_of_elimination: str
    metabolism: str
    clearance: str


def read_mechanism_data(drug_ids: Sequence[str]) -> Tuple[
        Dict[str, DrugMechanismRow], Dict[int, List[ProteinRow]], List[Tuple[str, str, str]]]:
    """Rows for the requested ids (unknown ids are absent), their protein
    entries, and DrugBank interaction records BETWEEN the requested drugs as
    (from_drug_id, to_drug_id, description)."""

    def q(session):
        rows = session.execute(
            select(Drug.id, Drug.drug_id, Drug.name, Drug.route_of_elimination, Drug.metabolism, Drug.clearance)
            .where(Drug.drug_id.in_(list(drug_ids)))).all()
        by_id = {r.drug_id: DrugMechanismRow(r.id, r.drug_id, r.name, r.route_of_elimination or "",
                                             r.metabolism or "", r.clearance or "") for r in rows}
        pks = [r.pk for r in by_id.values()]
        proteins: Dict[int, List[ProteinRow]] = {pk: [] for pk in pks}
        if pks:
            e_rows = session.execute(
                select(DrugEnzyme.drug_pk, DrugEnzyme.enzyme_id, DrugEnzyme.name, DrugEnzyme.organism,
                       DrugEnzyme.known_action, DrugEnzyme.actions, DrugEnzyme.inhibition_strength,
                       DrugEnzyme.induction_strength, DrugEnzyme.id)
                .where(DrugEnzyme.drug_pk.in_(pks)).order_by(DrugEnzyme.drug_pk, DrugEnzyme.id)).all()
            for r in e_rows:
                proteins[r.drug_pk].append(ProteinRow(
                    "enzyme", r.enzyme_id or "", r.name or "", r.organism or "", r.known_action or "",
                    r.actions or "", r.inhibition_strength or "", r.induction_strength or ""))
            for kind, model, id_col in (("transporter", DrugTransporter, DrugTransporter.transporter_id),
                                        ("carrier", DrugCarrier, DrugCarrier.carrier_id)):
                t_rows = session.execute(
                    select(model.drug_pk, id_col, model.name, model.organism, model.known_action, model.actions,
                           model.id)
                    .where(model.drug_pk.in_(pks)).order_by(model.drug_pk, model.id)).all()
                for r in t_rows:
                    proteins[r.drug_pk].append(ProteinRow(
                        kind, r[1] or "", r.name or "", r.organism or "", r.known_action or "", r.actions or ""))
        recorded: List[Tuple[str, str, str]] = []
        if len(pks) > 1:
            pk_to_id = {r.pk: r.drug_id for r in by_id.values()}
            i_rows = session.execute(
                select(DrugInteraction.drug1_id, DrugInteraction.drug2_drugbank_id, DrugInteraction.description)
                .where(and_(DrugInteraction.drug1_id.in_(pks),
                            DrugInteraction.drug2_drugbank_id.in_(list(by_id))))
                .order_by(DrugInteraction.drug1_id, DrugInteraction.drug2_drugbank_id)).all()
            for r in i_rows:
                src = pk_to_id[r.drug1_id]
                if src != r.drug2_drugbank_id:
                    recorded.append((src, r.drug2_drugbank_id, r.description or ""))
        return by_id, proteins, recorded

    return _run(q)


def find_drug_names(candidates: Sequence[str]) -> Dict[str, set]:
    """Which candidate strings are a DrugBank drug name or synonym (exact,
    lower-case): ``{name: {drug_id, ...}}``. Used to tell whether a sentence of
    one drug's record names another drug. Read-only; bounded by the candidates."""
    cands = sorted({c for c in candidates if c})
    if not cands:
        return {}

    def q(session):
        out: Dict[str, set] = {}
        for i in range(0, len(cands), 500):
            chunk = cands[i:i + 500]
            for r in session.execute(select(Drug.name_lower, Drug.drug_id).where(Drug.name_lower.in_(chunk))):
                out.setdefault(r[0], set()).add(r[1])
            for r in session.execute(select(DrugSynonym.synonym_lower, Drug.drug_id)
                                     .join(Drug, Drug.id == DrugSynonym.drug_pk)
                                     .where(DrugSynonym.synonym_lower.in_(chunk))):
                out.setdefault(r[0], set()).add(r[1])
        return out

    return _run(q)
