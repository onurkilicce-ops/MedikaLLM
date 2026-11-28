"""M-03 service: assembles the response from the repository and the rules."""
from __future__ import annotations

from typing import List, Sequence

from . import repository, rules
from .models import (DrugInfo, DrugMechanism, DrugText, Explanation, MechanismResponse, OrganMention,
                     PairMechanism, ProteinEntry, RecordedInteraction, RoleEvidence)

_FIELDS = ("route_of_elimination", "metabolism", "clearance")
_PLACEHOLDER = {"not available", "n/a", "na", "none", "unknown", "-", "not applicable", "no data"}
MAX_STORED_CHARS = 20000
MAX_PROTEINS_SHOWN = 200


def _text(value: str) -> str:
    v = (value or "").strip().rstrip(".;: ").strip()
    return "" if v.lower() in _PLACEHOLDER else value or ""


def compare(drug_ids: Sequence[str]) -> MechanismResponse:
    by_id, proteins, recorded = repository.read_mechanism_data(drug_ids)
    # Which other drugs does each record's elimination text name? (DrugBank names/synonyms)
    texts_by_id = {d: " ".join(_text(getattr(r, f))[:MAX_STORED_CHARS] for f in _FIELDS) for d, r in by_id.items()}
    candidates = sorted({c for t in texts_by_id.values() for c in rules.name_candidates(t)})
    known = repository.find_drug_names(candidates) if candidates else {}
    drugs: List[DrugMechanism] = []
    for requested in drug_ids:
        row = by_id.get(requested)
        if row is None:
            drugs.append(DrugMechanism(requested_id=requested, lookup_status="not_found", drug=None, proteins=[],
                                       organs=[], organs_truncated=False, proteins_truncated=False, texts=[]))
            continue
        entries = [ProteinEntry(
            kind=p.kind, protein_id=p.protein_id, name=p.name, organism=p.organism, human=rules.is_human(p.organism),
            roles=rules.roles_of(p.actions), raw_actions=p.actions, known_action=p.known_action,
            inhibition_strength=p.inhibition_strength, induction_strength=p.induction_strength)
            for p in proteins.get(row.pk, [])[:MAX_PROTEINS_SHOWN]]
        texts, organs, organs_truncated = [], [], False
        for field in _FIELDS:
            value = _text(getattr(row, field))
            if not value.strip():
                continue
            texts.append(DrugText(source_field=field, stored_text=value[:MAX_STORED_CHARS],
                                  truncated=len(value) > MAX_STORED_CHARS))
            # parse the same bounded text that is shown, so every quote offset lies inside it
            # a name shared with this record (its own name/synonym) is not another drug
            others = sorted(n for n, ids in known.items() if ids - {row.drug_id} and row.drug_id not in ids)
            mentions, cut = rules.organ_mentions(field, value[:MAX_STORED_CHARS], others)
            organs_truncated = organs_truncated or cut
            organs += [OrganMention(organ=m.organ, source_field=field, quote=m.quote, quote_start=m.start,
                                    quote_end=m.end, notes=list(m.notes),
                                    quote_truncated=m.quote_truncated, quote_cut_before=m.cut_before,
                                    quote_cut_after=m.cut_after, other_drugs=list(m.other_drugs))
                       for m in mentions]
        drugs.append(DrugMechanism(requested_id=requested, lookup_status="found",
                                   drug=DrugInfo(drug_id=row.drug_id, name=row.name), proteins=entries,
                                   organs=organs, organs_truncated=organs_truncated,
                                   proteins_truncated=len(proteins.get(row.pk, [])) > MAX_PROTEINS_SHOWN, texts=texts))

    pairs: List[PairMechanism] = []
    for a, b in rules.pairs_of(drug_ids):
        rec = [RecordedInteraction(from_drug_id=f, to_drug_id=t, description=d)
               for f, t, d in dict.fromkeys(x for x in recorded if {x[0], x[1]} == {a, b})]
        if a not in by_id or b not in by_id:
            pairs.append(PairMechanism(drug_ids=[a, b], status="drug_not_found", explanations=[],
                                       shared_proteins_without_direction=[], recorded_interactions=rec))
            continue
        explained, undirected = rules.explain_pair(a, b, proteins.get(by_id[a].pk, []), proteins.get(by_id[b].pk, []))
        exps = [Explanation(
            protein_kind=x.kind, protein_id=x.protein_id, protein_name=x.protein_name, mechanism=x.mechanism,
            perpetrator_id=x.perpetrator, victim_id=x.victim, effect=x.effect,
            evidence=[RoleEvidence(drug_id=d, roles=list(r), raw_actions=raw, known_action=k, strength=s)
                      for d, r, raw, k, s in x.evidence],
            caveats=list(x.caveats), directional=x.directional) for x in explained]
        if any(x.directional for x in exps):
            status = "explained_by_shared_protein"
        elif exps and all(x.mechanism == "shared_substrate" for x in exps):
            status = "shared_substrate_only"
        elif exps or undirected:
            status = "shared_protein_no_direction"   # carrier binding / inhibitor+inducer conflict / no role
        else:
            status = "no_shared_protein_in_record"
        pairs.append(PairMechanism(drug_ids=[a, b], status=status, explanations=exps,
                                   shared_proteins_without_direction=undirected, recorded_interactions=rec))
    return MechanismResponse(drugs=drugs, pairs=pairs)
