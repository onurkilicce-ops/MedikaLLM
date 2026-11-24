"""M-02 compare service: stored text -> sourced measurements -> derived values.

No LLM, no external source, no write. ``timing_advice`` is explicitly
``not_evaluated`` in this delivery.
"""
from __future__ import annotations

from typing import Dict, List, Sequence

from . import calc, repository
from .models import (
    Conditions,
    DataStatus,
    DerivedDuration,
    Dispersion,
    DrugIdentity,
    DrugTimingResult,
    FieldReport,
    Limitation,
    OriginalQuantity,
    Quantity,
    ReferenceLink,
    ReviewItem,
    SourceExcerpt,
    TimingAdvice,
    TimingCompareResponse,
    TimingMeasurement,
)
from .parser import PARSER_VERSION, FieldParse, ParsedQuantity, ParsedValue, parse_field, reference_tokens

DRUGBANK_RECORD_URL = "https://go.drugbank.com/drugs/{drug_id}"

RESPONSE_LIMITATIONS = [
    Limitation(code="stored_text_not_reverified",
               message="Values are read from text stored in this database (DrugBank import). They were not "
                       "re-checked against the current original source; the record URL may show a newer version."),
    Limitation(code="rule_based_extraction",
               message=f"Rule-based extraction ({PARSER_VERSION}, src/timing/RULES.md). Text the rules cannot "
                       "structure safely is returned for review, not discarded. No confidence percentage is given."),
    Limitation(code="half_life_column_limit",
               message=f"half_life is stored in a {repository.HALF_LIFE_STORED_MAX}-character column; text of exactly "
                       "that length is flagged as possibly truncated and is not used for derived values."),
    Limitation(code="general_references_not_linked",
               message="A drug's general reference list is not treated as evidence for a value. A reference is "
                       "linked only when an inline token in the quoted sentence matches that drug's reference id."),
    Limitation(code="five_half_lives_is_an_approximation",
               message="'approx_five_half_lives' assumes one constant half-life (first-order decline). It must not "
                       "be read as complete elimination, as the end of the effect or as clearance to give another "
                       "drug."),
    Limitation(code="tmax_not_added",
               message="Tmax is a time after administration; a half-life is a duration. Tmax is never added to "
                       "the derived duration."),
    Limitation(code="timing_advice_not_evaluated",
               message="Timing advice between drugs or with food was not evaluated in this version."),
    Limitation(code="no_patient_data_no_dose",
               message="No patient, dose, personal drug level or clinical interval is used or produced."),
    Limitation(code="no_expert_acceptance",
               message="Not clinically validated. The Form A M-02 expert acceptance (agreed drug set, >=90%) has "
                       "not been carried out."),
]


def _q(p: ParsedQuantity) -> Quantity:
    return Quantity(kind=p.kind, value=p.value, lower=p.lower, upper=p.upper, inclusive=p.inclusive)


def _measurements(drug_id: str, fp: FieldParse, refs: List[repository.ReferenceRow]) -> List[TimingMeasurement]:
    out: List[TimingMeasurement] = []
    text = fp.text or ""
    url = DRUGBANK_RECORD_URL.format(drug_id=drug_id)
    by_ref: Dict[str, List[repository.ReferenceRow]] = {}
    for r in refs:
        by_ref.setdefault(r.ref_id, []).append(r)
    for n, v in enumerate(fp.values, start=1):
        status, matched, unmatched = calc.reference_status(v.reference_tokens, by_ref.keys())
        links = [
            ReferenceLink(ref_id=r.ref_id, ref_type=r.ref_type, pubmed_id=r.pubmed_id, isbn=r.isbn,
                          citation=r.citation, title=r.title, url=r.url)
            for tok in matched for r in by_ref[tok]
        ]
        c = v.conditions
        out.append(TimingMeasurement(
            measurement_id=f"{drug_id}:{fp.source_field}:{n}",
            drug_id=drug_id,
            measure_type=v.measure_type,
            measure_basis=v.basis,
            source=SourceExcerpt(
                source_ref=f"drugbank:{drug_id}",
                source_record_url=url,
                source_field=fp.source_field,
                quote=text[v.sentence.start:v.sentence.end],
                quote_start=v.sentence.start,
                quote_end=v.sentence.end,
                value_text=text[v.value_span.start:v.value_span.end],
                value_start=v.value_span.start,
                value_end=v.value_span.end,
                truncated=False,
                stored_text_possibly_truncated=fp.possibly_truncated,
                inline_reference_tokens=list(v.reference_tokens),
                references=links,
                unmatched_reference_tokens=unmatched,
                reference_status=status,
                reference_scope=v.reference_scope,
                primary_reference_verified=status == "matched"
                and v.reference_scope in ("value_window", "sentence_single_value"),
            ),
            original=OriginalQuantity(kind=v.original.kind, value=v.original.value, lower=v.original.lower,
                                      upper=v.original.upper, inclusive=v.original.inclusive,
                                      unit=v.unit, lower_unit=v.lower_unit),
            hours=_q(v.hours),
            approximate=v.approximate,
            dispersion=Dispersion(kind="plus_minus", value_original=v.dispersion[0], unit=v.dispersion[2],
                                  value_hours=v.dispersion[1])
            if v.dispersion else None,
            conditions=Conditions(
                route=c["route"], formulation=c["formulation"], population=c["population"],
                food_state=c["food_state"], dosing=c["dosing"], analyte=c["analyte"],
                analyte_terms=c["analyte_terms"], phase=c["phase"], matrix=c["matrix"], kinetics=c["kinetics"],
                other=c["other"],
            ),
            time_reference=v.time_reference,
            review_required=bool(v.review_reasons),
            review_reasons=list(v.review_reasons),
            conflict_group=v.conflict_group,
            parser_version=PARSER_VERSION,
        ))
    return out


def _derived(fp: FieldParse, measurements: List[TimingMeasurement]) -> List[DerivedDuration]:
    out: List[DerivedDuration] = []
    for v, m in zip(fp.values, measurements):
        if v.measure_type != "half_life":
            continue
        d = calc.five_half_lives(v, fp.flags)
        out.append(DerivedDuration(
            derived_id=f"{m.measurement_id}:x5",
            based_on_measurement_id=m.measurement_id,
            status=d["status"],
            multiplier=calc.MULTIPLIER,
            hours=_q(d["hours"]) if d["hours"] is not None else None,
            not_computed_reasons=d["not_computed_reasons"],
            includes_tmax=False,
            assumptions=list(calc.ASSUMPTIONS),
            interpretation=calc.INTERPRETATION,
        ))
    return out


def _field_report(fp: FieldParse, ids: List[str]) -> FieldReport:
    text = fp.text or ""
    return FieldReport(
        source_field=fp.source_field,
        field_status=fp.status,
        stored_text=fp.text,
        stored_text_length=fp.length,
        stored_text_possibly_truncated=fp.possibly_truncated,
        measurement_ids=ids,
        review_items=[
            ReviewItem(source_field=r.source_field, quote=text[r.sentence.start:r.sentence.end],
                       quote_start=r.sentence.start, quote_end=r.sentence.end,
                       value_text=text[r.value_span.start:r.value_span.end] if r.value_span else None,
                       reason=r.reason)
            for r in fp.reviews
        ],
        field_flags=list(fp.flags),
    )


def _drug_limitations(half: FieldParse, absorption: FieldParse, ms: List[TimingMeasurement]) -> List[str]:
    out: List[str] = []
    if half.possibly_truncated:
        out.append("half_life_text_possibly_truncated")
    if half.status in ("empty", "placeholder"):
        out.append(f"half_life_text_{half.status}")
    if absorption.status in ("empty", "placeholder"):
        out.append(f"absorption_text_{absorption.status}")
    if absorption.status == "no_statement_found":
        out.append("no_tmax_statement_in_absorption_text")
    if any(m.conflict_group for m in ms):
        out.append("conflicting_values_kept_unresolved")
    if any(not m.source.primary_reference_verified for m in ms):
        out.append("some_values_without_verified_inline_reference")
    if half.status in ("unparsed_needs_review", "parsed_needs_review") or \
            absorption.status in ("unparsed_needs_review", "parsed_needs_review"):
        out.append("text_needs_human_review")
    return out


def compare(drug_ids: Sequence[str]) -> TimingCompareResponse:
    """Raises ``repository.TimingDataUnavailable`` on any database problem."""
    rows, refs = repository.read_timing_data(drug_ids, reference_tokens)
    results: List[DrugTimingResult] = []
    for position, drug_id in enumerate(drug_ids):
        row = rows.get(drug_id)
        if row is None:
            results.append(DrugTimingResult(
                position=position, requested_id=drug_id, lookup_status="not_found", drug=None,
                data_status=None, fields=[], measurements=[], derived=[],
                limitations=["drug_id_not_in_database"],
            ))
            continue
        half = parse_field("half_life", row.half_life, stored_max_length=repository.HALF_LIFE_STORED_MAX)
        absorption = parse_field("absorption", row.absorption)
        drug_refs = refs.get(row.pk, [])
        abs_ms = _measurements(row.drug_id, absorption, drug_refs)
        half_ms = _measurements(row.drug_id, half, drug_refs)
        derived = _derived(half, half_ms)
        measurements = abs_ms + half_ms
        results.append(DrugTimingResult(
            position=position,
            requested_id=drug_id,
            lookup_status="found",
            drug=DrugIdentity(drug_id=row.drug_id, name=row.name,
                              source_record_url=DRUGBANK_RECORD_URL.format(drug_id=row.drug_id)),
            data_status=DataStatus(tmax=absorption.status, half_life=half.status),
            fields=[
                _field_report(absorption, [m.measurement_id for m in abs_ms]),
                _field_report(half, [m.measurement_id for m in half_ms]),
            ],
            measurements=measurements,
            derived=derived,
            limitations=_drug_limitations(half, absorption, measurements),
        ))
    return TimingCompareResponse(
        parser_version=PARSER_VERSION,
        drugs=results,
        timing_advice=TimingAdvice(),
        limitations=list(RESPONSE_LIMITATIONS),
    )
