"""M-03 rules (organs, protein roles, shared-protein explanations), including
the cases found in two adversarial review rounds. Every text is SYNTHETIC."""
from __future__ import annotations

import pytest

from src.mechanism import rules as R
from src.mechanism.models import MechanismRequest, OrganMention

S = "[SYNTHETIC] "
CYP = ("enzyme", "BE0000001", "Cytochrome P450 3A4")
PGP = ("transporter", "BE0000002", "P-glycoprotein 1")
ALB = ("carrier", "BE0000003", "Serum albumin")


def row(p, actions, known="yes", organism="Humans", inh="", ind=""):
    return R.ProteinRow(p[0], p[1], p[2], organism, known, actions, inh, ind)


def organs(text, field="route_of_elimination"):
    return [(m.organ, m.notes) for m in R.organ_mentions(field, S + text)[0]]


def notes_of(text, organ):
    got = [n for o, n in organs(text) if o == organ]
    assert len(got) == 1, organs(text)
    return got[0]


# --------------------------------------------------------------- roles --
@pytest.mark.parametrize("actions,expected", [
    ("substrate", ["substrate"]), ("Substrate, Inhibitor", ["substrate", "inhibitor"]),
    ("inducer", ["inducer"]), ("binder", ["other"]), ("", []), ("inhibitor, inhibitor", ["inhibitor"]),
    ("substrate; other/unknown", ["substrate", "other"]), ("inactivator", ["inhibitor"]),
    ("Negative  Modulator", ["other"]),
])
def test_roles(actions, expected):
    assert R.roles_of(actions) == expected


def test_only_human_proteins_are_compared():
    assert R.is_human("Humans") and R.is_human("Homo sapiens") and not R.is_human("Escherichia coli")
    ex, und = R.explain_pair("DB1", "DB2", [row(CYP, "inhibitor", organism="Rattus")], [row(CYP, "substrate")])
    assert ex == [] and und == []


# -------------------------------------------------------------- organs --
def test_no_share_is_attached_to_an_organ():
    """Percentages are read from the quote; the contract has no amount field."""
    assert "amount_text" not in OrganMention.model_fields
    text = S + "About 70% is excreted unchanged in urine; the rest is eliminated in feces."
    ms, _ = R.organ_mentions("route_of_elimination", text)
    assert [(m.organ, m.notes) for m in ms] == [("kidney", ()), ("bile_feces", ())]
    assert all(text[m.start:m.end] == m.quote for m in ms) and "70%" in ms[0].quote


@pytest.mark.parametrize("text,organ", [
    ("Primarily eliminated by the kidneys.", "kidney"), ("Extensively metabolized in the liver.", "liver"),
    ("Eliminated via exhaled air.", "lungs"), ("Excreted in faeces.", "bile_feces"), ("Mainly renal.", "kidney"),
    ("Mainly hepatic.", "liver"), ("Renal.", "kidney"), ("The kidneys are the main route.", "kidney"),
    ("Approximately 85% of a dose appears in the urine.", "kidney"), ("Hepatic, via CYP3A4.", "liver"),
    ("It undergoes hepatic metabolism.", "liver"), ("Fecal excretion accounts for 20% of the dose.", "bile_feces"),
    ("Urine: 65% unchanged.", "kidney"), ("Excreted in breast milk and urine.", "kidney"),
    ("Excreted in sweat and feces.", "bile_feces"), ("Total body clearance is 5 L/h, 60% of which is renal.", "kidney"),
    ("The major route of elimination is renal, with 70% of the dose excreted unchanged.", "kidney"),
    ("Excretion is predominantly renal and fecal.", "bile_feces"),
    ("Not only renal but also biliary excretion occurs.", "kidney"),
    ("Not only renal but also biliary excretion occurs.", "bile_feces"),
    ("Not less than 90% is excreted in urine.", "kidney"),
    ("Renal elimination is not saturated at therapeutic doses.", "kidney"),
    ("Excreted primarily in urine as unchanged drug since it is not metabolized.", "kidney"),
    ("Excreted in the urine (not metabolized).", "kidney"), ("Excreted in urine with no dose adjustment needed.", "kidney"),
    ("Excreted renally without metabolism.", "kidney"),
    ("Mostly excreted in urine, with less than 1% as unchanged drug.", "kidney"),
    ("More than 1% of the dose is excreted in feces.", "bile_feces"),
    ("When given with food, 60% is excreted in urine.", "kidney"),
    ("Renal clearance was lower in elderly compared with young subjects.", "kidney"),
    ("The drug is not metabolized by the liver and 95% is excreted in urine.", "kidney"),
    ("After i.v. administration, 80% is excreted in urine.", "kidney"),
])
def test_real_routes_are_kept_without_notes(text, organ):
    assert notes_of(text, organ) == ()


@pytest.mark.parametrize("text", [
    "Liver enzymes increased in some patients.", "Urinary retention was reported.", "Pulmonary absorption is rapid.",
    "Renal function should be monitored.", "Cholestyramine, a bile acid sequestrant, reduces its absorption.",
    "Half-life is 2.5 hours. Not available.",
])
def test_organ_words_that_are_not_routes_are_dropped(text):
    assert organs(text) == []


@pytest.mark.parametrize("text,organ,note", [
    ("It is not excreted renally.", "kidney", "negated_or_minor"),
    ("Renal excretion is negligible.", "kidney", "negated_or_minor"),
    ("Only traces appear in urine.", "kidney", "negated_or_minor"),
    ("Less than 1% is excreted unchanged in urine.", "kidney", "negated_or_minor"),
    ("No more than 3% appears in the urine.", "kidney", "negated_or_minor"),
    ("98% of the dose was excreted in feces, less than 1% in urine.", "kidney", "negated_or_minor"),
    ("The drug is not metabolized by the liver and 95% is excreted in urine.", "liver", "negated_or_minor"),
    ("Primarily hepatic (CYP2C9) with minor renal excretion.", "kidney", "negated_or_minor"),
    ("It is not known whether it is excreted in urine.", "kidney", "uncertain_statement"),
    ("Clearance is reduced in patients with renal impairment.", "kidney", "condition_context"),
    ("Clearance is reduced in hepatic cirrhosis.", "liver", "condition_context"),
    ("Clearance was decreased by 50% in renal failure.", "kidney", "condition_context"),
    ("Excreted in urine, but renal failure prolongs it.", "kidney", "condition_also_mentioned"),
    ("Excreted in urine and dialysis removes 30%.", "kidney", "condition_also_mentioned"),
    ("Excreted primarily in urine (no dose adjustment needed in mild impairment).", "kidney", "condition_also_mentioned"),
    ("Mainly hepatic metabolism to inactive metabolites.", "liver", "metabolite_mentioned"),
    ("Renal clearance is negligible, but 80% of the dose is recovered in urine as metabolites.", "kidney",
     "metabolite_mentioned"),
    ("Unlike drugX, which is renally excreted, this drug is eliminated in feces.", "kidney", "other_subject_possible"),
])
def test_organ_notes(text, organ, note):
    assert note in notes_of(text, organ)


def test_a_positive_segment_outweighs_a_negated_one():
    assert "negated_or_minor" not in notes_of(
        "Renal clearance is negligible, but 80% of the dose is recovered in urine as metabolites.", "kidney")
    assert notes_of("Excreted in urine, but renal failure prolongs it.", "kidney") == ("condition_also_mentioned",)


def test_time_units_end_a_sentence_and_abbreviations_do_not():
    assert organs("Renally cleared within 60 min. Not metabolized by the liver.") == [
        ("kidney", ()), ("liver", ("negated_or_minor",))]
    text = S + "After i.v. administration, 80% is excreted in urine."
    (m,), _ = R.organ_mentions("route_of_elimination", text)
    assert m.quote == text and text[m.start:m.end] == m.quote


def test_mention_and_quote_caps():
    ms, cut = R.organ_mentions("metabolism", S + "Hepatic metabolism. " * 200)
    assert len(ms) == R.MAX_MENTIONS_PER_FIELD and cut
    (m,), cut = R.organ_mentions("metabolism", S + "Hepatic metabolism " + "x" * 3000 + ".")
    assert m.quote_truncated and len(m.quote) == R.MAX_QUOTE_CHARS and not cut


# --------------------------------------------------------------- pairs --
def test_inhibitor_slows_the_enzyme_that_processes_the_substrate():
    ex, _ = R.explain_pair("DBA", "DBB", [row(CYP, "inhibitor", inh="strong")], [row(CYP, "substrate")])
    (x,) = ex
    assert (x.mechanism, x.perpetrator, x.victim, x.effect, x.directional) == (
        "inhibition", "DBA", "DBB", "victim_exposure_may_increase", True)
    assert "prodrug_reverses_direction" in x.caveats and "strength_not_stated" not in x.caveats
    assert x.evidence[0][4] == "strong"


def test_direction_does_not_depend_on_order():
    ex, _ = R.explain_pair("DBB", "DBA", [row(CYP, "substrate")], [row(CYP, "inhibitor")])
    (x,) = ex
    assert (x.perpetrator, x.victim) == ("DBA", "DBB") and "strength_not_stated" in x.caveats


def test_inducer_and_transporter_and_both_directions():
    ex, _ = R.explain_pair("DBA", "DBB", [row(CYP, "inducer"), row(PGP, "substrate, inhibitor")],
                           [row(CYP, "substrate"), row(PGP, "substrate, inhibitor")])
    got = {(x.kind, x.mechanism, x.perpetrator, x.effect) for x in ex}
    assert ("enzyme", "induction", "DBA", "victim_exposure_may_decrease") in got
    assert ("transporter", "inhibition", "DBA", "victim_transport_may_decrease") in got
    assert ("transporter", "inhibition", "DBB", "victim_transport_may_decrease") in got
    assert ex[0].kind == "enzyme"
    assert all("transport_direction_depends_on_protein" in x.caveats for x in ex if x.kind == "transporter")


def test_shared_substrate_is_weak_and_unknown_action_flagged():
    ex, _ = R.explain_pair("DBA", "DBB", [row(CYP, "substrate", known="unknown")], [row(CYP, "substrate")])
    (x,) = ex
    assert x.mechanism == "shared_substrate" and x.perpetrator is None and not x.directional
    assert x.effect == "competition_possible_not_established"
    assert {"shared_substrate_is_weak_evidence", "known_action_not_confirmed"} <= set(x.caveats)


def test_shared_protein_without_direction_and_no_shared_protein():
    ex, und = R.explain_pair("DBA", "DBB", [row(ALB, "binder")], [row(ALB, "carrier")])
    assert ex == [] and und == ["Serum albumin"]
    assert R.explain_pair("DBA", "DBB", [row(CYP, "inhibitor")], [row(PGP, "substrate")]) == ([], [])


def test_same_protein_matched_by_id_then_by_name():
    ex, _ = R.explain_pair("DBA", "DBB", [row(CYP, "inhibitor")], [row(("enzyme", "BE0000001", "CYP3A4"), "substrate")])
    assert len(ex) == 1
    # the same BE id filed under another kind is still the same protein (flagged)
    (x,) = R.explain_pair("DBA", "DBB", [row(CYP, "inhibitor")], [row(("transporter",) + CYP[1:], "substrate")])[0]
    assert x.kind == "transporter" and "listed_under_different_protein_kinds" in x.caveats
    # an id on one side only: the name decides
    (x,) = R.explain_pair("DBA", "DBB", [row(CYP, "inhibitor")], [row(("enzyme", "", CYP[2]), "substrate")])[0]
    assert x.mechanism == "inhibition"
    # different ids never match, even with the same name
    assert R.explain_pair("DBA", "DBB", [row(CYP, "inhibitor")], [row(("enzyme", "BE7", CYP[2]), "substrate")]) == ([], [])


def test_unidentified_proteins_never_match():
    blank = ("enzyme", "", "")
    assert R.explain_pair("DBA", "DBB", [row(blank, "inhibitor")], [row(blank, "substrate")]) == ([], [])


def test_duplicate_entries_for_one_drug_are_merged():
    ex, _ = R.explain_pair("DBA", "DBB", [row(CYP, "substrate"), row(CYP, "inhibitor")], [row(CYP, "substrate")])
    assert [x.mechanism for x in ex] == ["inhibition"]


def test_inhibitor_and_inducer_of_one_enzyme_have_no_net_direction():
    ex, _ = R.explain_pair("DBA", "DBB", [row(CYP, "inhibitor, inducer")], [row(CYP, "substrate")])
    assert [x.mechanism for x in ex] == ["inhibition", "induction"]
    assert all("perpetrator_listed_as_inhibitor_and_inducer" in x.caveats and not x.directional for x in ex)


def test_merge_keeps_known_action_and_strength_of_the_same_entry():
    ex, _ = R.explain_pair("DBA", "DBB", [row(CYP, "substrate", known="no"), row(CYP, "inhibitor", known="yes")],
                           [row(CYP, "substrate", known="no"), row(CYP, "substrate", known="yes")])
    (x,) = ex
    assert x.evidence[0][3] == "yes" and x.evidence[1][3] == "yes" and "known_action_not_confirmed" not in x.caveats
    # 'yes' without strength is preferred over 'no' with 'strong'; strengths are not mixed across entries
    (x,), _ = R.explain_pair("DBA", "DBB", [row(CYP, "inhibitor", known="yes"), row(CYP, "inhibitor", known="no", inh="strong")],
                             [row(CYP, "substrate")])
    assert x.evidence[0][3:] == ("yes", "") and "strength_not_stated" in x.caveats


def test_carrier_has_no_transport_direction():
    (x,), _ = R.explain_pair("DBA", "DBB", [row(ALB, "inhibitor")], [row(ALB, "substrate")])
    assert x.effect == "carrier_binding_may_change" and not x.directional
    assert "carrier_binding_direction_not_established" in x.caveats


def test_kind_comes_from_the_victims_substrate_entry():
    (x,), _ = R.explain_pair("DBA", "DBB", [row(CYP, "inhibitor", inh="strong")],
                             [row(("carrier",) + CYP[1:], "binder", known="unknown"), row(CYP, "substrate")])
    assert (x.kind, x.effect) == ("enzyme", "victim_exposure_may_increase")
    assert "listed_under_different_protein_kinds" not in x.caveats


def test_an_entry_without_id_never_bridges_two_ids():
    a = [row(("enzyme", "", "Cytochrome P450 3A"), "inhibitor", inh="strong"), row(("enzyme", "BE2", "Cytochrome P450 3A"), "inducer")]
    b = [row(("enzyme", "BE9", "Cytochrome P450 3A"), "substrate")]
    assert R.explain_pair("DBA", "DBB", a, b) == ([], [])


def test_shared_substrate_across_kinds_is_flagged():
    (x,), _ = R.explain_pair("DBA", "DBB", [row(("enzyme", "BE1", "P-gp"), "substrate")],
                             [row(("transporter", "BE1", "P-gp"), "substrate")])
    assert x.mechanism == "shared_substrate" and "listed_under_different_protein_kinds" in x.caveats


def test_an_explained_protein_is_not_also_listed_without_direction():
    ex, und = R.explain_pair("DBA", "DBB", [row(CYP, "inhibitor")],
                             [row(("enzyme", "BE0000001", "CYP3A4"), "substrate"),
                              row(("enzyme", "", "Cytochrome P450 3A4"), "other", known="unknown")])
    assert [x.mechanism for x in ex] == ["inhibition"] and und == []


# ------------------------------------------------------------- request --
@pytest.mark.parametrize("ids,ok", [(["DB00001"], True), ([], False), (["DB00001", "DB00001"], False),
                                    (["DB0001"], False), (["DB0000١"], False), ([f"DB{i:05d}" for i in range(11)], False)])
def test_request_validation(ids, ok):
    if ok:
        assert MechanismRequest(drug_ids=ids).drug_ids == ids
    else:
        with pytest.raises(Exception):
            MechanismRequest(drug_ids=ids)


# ------------------------------------------------- review round 3 regressions --
@pytest.mark.parametrize("text", [
    "Non-renal clearance accounts for about 70% of total clearance.", "It undergoes extra-hepatic metabolism.",
    "Elimination is mainly non-renal.", "The drug is cleared by non-hepatic pathways.", "It undergoes non-biliary elimination.",
    "Liver enzyme elevations were found in 5% of patients.", "Urinary retention.", "Renal colic.", "Hepatic necrosis.",
])
def test_round3_prefixed_and_event_words_are_not_routes(text):
    assert organs(text) == []


def test_round3_non_renal_with_a_named_organ_keeps_only_that_organ():
    assert organs("Clearance is mostly non-renal (hepatic).") == [("liver", ())]


@pytest.mark.parametrize("text,organ", [
    ("Radioactivity was recovered in urine (40%) and feces (55%) within 7 days.", "bile_feces"),
    ("The drug is excreted in urine and, to a lesser extent, feces.", "bile_feces"),
    ("Renal clearance is not reduced in the elderly.", "kidney"),
    ("Renal clearance did not differ between men and women.", "kidney"),
    ("Renal clearance was not different in elderly subjects.", "kidney"),
    ("Renal clearance does not change with age.", "kidney"),
    ("Urinary excretion is not dose-dependent.", "kidney"),
    ("Its metabolism is unknown, but about 60% is excreted unchanged in urine.", "kidney"),
    ("The drug is not known to inhibit CYP enzymes and is excreted unchanged in urine.", "kidney"),
    ("Clearance, which is predominantly renal, is reduced in the elderly.", "kidney"),
    ("Excreted in urine as unchanged drug 24 hours after dosing.", "kidney"),
    ("Eliminated predominantly via hepatobiliary excretion.", "bile_feces"),
    ("Eliminated unchanged by glomerular filtration and tubular secretion.", "kidney"),
    ("Metabolized in the liver primarily by CYP3A4. Less than 1% is excreted unchanged in the urine.", "liver"),
])
def test_round3_real_routes_without_notes(text, organ):
    assert notes_of(text, organ) == ()


@pytest.mark.parametrize("text,organ,note", [
    ("Metabolized in the liver primarily by CYP3A4. Less than 1% is excreted unchanged in the urine.", "kidney",
     "negated_or_minor"),
    ("Urinary excretion of unchanged drug is <1% of the dose.", "kidney", "negated_or_minor"),
    ("Renal excretion <1%.", "kidney", "negated_or_minor"),
    ("Less than 1 percent is excreted unchanged in urine.", "kidney", "negated_or_minor"),
    ("Only a small fraction (<2%) appears in urine.", "kidney", "negated_or_minor"),
    ("Hepatic; renal (minor).", "kidney", "negated_or_minor"),
    ("Fecal (90%), urinary (<5%).", "kidney", "negated_or_minor"),
    ("Little is known about hepatic metabolism of this drug.", "liver", "uncertain_statement"),
    ("No data are available on biliary excretion.", "bile_feces", "uncertain_statement"),
])
def test_round3_minor_and_uncertain(text, organ, note):
    got = notes_of(text, organ)
    assert note in got
    if note == "uncertain_statement":
        assert "negated_or_minor" not in got


def test_round3_minor_metabolites_do_not_negate_the_liver():
    assert "negated_or_minor" not in notes_of("It is extensively metabolized in the liver to several minor metabolites.", "liver")


def test_round3_long_sentence_quote_contains_the_organ_word():
    text = "x" * 1200 + " is excreted in urine."
    (m,), _ = R.organ_mentions("clearance", text)
    assert m.quote_truncated and "urine" in m.quote and text[m.start:m.end] == m.quote


def test_round3_ambiguous_id_less_entries_explain_nothing():
    a = [row(("enzyme", "", "Cytochrome P450 3A4"), "inhibitor", inh="strong")]
    b = [row(("enzyme", "BE1", "Cytochrome P450 3A4"), "substrate"), row(("enzyme", "BE2", "Cytochrome P450 3A4"), "substrate")]
    # shared by name, but which protein is meant is unknown: no explanation, listed without direction
    assert R.explain_pair("DBA", "DBB", a, b) == ([], ["Cytochrome P450 3A4"])
    a = [row(("enzyme", "BE1", "X"), "substrate"), row(("enzyme", "BE2", "X"), "substrate"), row(("enzyme", "", "X"), "inhibitor")]
    assert R.explain_pair("DBA", "DBB", a, [row(("enzyme", "BE7", "X"), "substrate")]) == ([], ["X"])


# ------------------------------------------------- review round 4 regressions --
@pytest.mark.parametrize("text,organ", [
    ("Renal excretion is not a significant route of elimination.", "kidney"),
    ("The drug is not significantly metabolized by the liver.", "liver"),
    ("There is no significant renal excretion of unchanged drug.", "kidney"),
    ("No significant hepatic metabolism occurs.", "liver"),
    ("Elimination does not depend on hepatic metabolism.", "liver"),
    ("The drug is not excreted in urine, feces, or bile.", "bile_feces"),
    ("It is not eliminated in the urine and feces.", "bile_feces"),
    ("Less than 5.0% is recovered in urine.", "kidney"),
])
def test_round4_denials_are_negated(text, organ):
    assert "negated_or_minor" in notes_of(text, organ)


@pytest.mark.parametrize("text,organ", [
    ("The hepatic metabolism of the drug has not been fully characterized.", "liver"),
    ("Biliary excretion has not been evaluated.", "bile_feces"),
    ("The metabolism in the liver is not well understood.", "liver"),
])
def test_round4_not_characterized_is_uncertain(text, organ):
    got = notes_of(text, organ)
    assert "uncertain_statement" in got and "negated_or_minor" not in got


@pytest.mark.parametrize("text,organ", [
    ("Renal excretion is impaired in premature infants.", "kidney"),
    ("Hepatic clearance is reduced in patients with cirrhosis.", "liver"),
])
def test_round4_route_with_a_condition(text, organ):
    assert notes_of(text, organ) == ("condition_also_mentioned",)


@pytest.mark.parametrize("text,organ", [
    ("Approximately 80% of the dose is excreted in the urine as minor glucuronide conjugates.", "kidney"),
    ("Renal clearance is not saturable and accounts for 70% of total clearance.", "kidney"),
])
def test_round4_not_negations(text, organ):
    assert "negated_or_minor" not in notes_of(text, organ)


@pytest.mark.parametrize("text", [
    "Concentrations in lung tissue exceed those in plasma.", "The drug accumulates in the liver.",
    "Cobicistat inhibits tubular secretion of creatinine.",
    "The dose should be reduced when the glomerular filtration rate is below 30 mL/min.",
    "It is metabolized by CYP3A4 and is an inhibitor of BSEP (bile salt export pump).",
])
def test_round4_not_routes(text):
    assert [o for o, _ in organs(text) if o in ("lungs", "liver", "kidney", "bile_feces") and
            not ("liver" == o and "metabolized" in text)] == []


@pytest.mark.parametrize("text,note,present", [
    ("Renal clearance in elderly subjects was similar to that in young subjects.", "other_subject_possible", False),
    ("In patients with normal renal function, 90% is excreted in urine.", "condition_also_mentioned", False),
    ("Hydroxyurea is excreted in urine.", "metabolite_mentioned", False),
    ("In rats, 90% of the dose was excreted in feces.", "animal_study", True),
])
def test_round4_flags(text, note, present):
    organ = "bile_feces" if "feces" in text else "kidney"
    assert (note in notes_of(text, organ)) is present


def test_round4_quote_window_cut_markers():
    text = "Absorbed well. Excreted in urine, " + "x " * 600 + "end."
    ms, _ = R.organ_mentions("route_of_elimination", text)
    (m,) = [x for x in ms if x.organ == "kidney"]
    assert m.quote_truncated and not m.cut_before and m.cut_after and text[m.start:m.end] == m.quote


def test_round4_unknown_strength_is_not_preferred_and_duplicates_collapse():
    (x,), _ = R.explain_pair("DBA", "DBB", [row(CYP, "inhibitor", known="unknown", inh="unknown"),
                                           row(CYP, "inhibitor", known="unknown", inh="strong")], [row(CYP, "substrate")])
    assert x.evidence[0][4] == "strong" and "strength_not_stated" not in x.caveats
    ex, _ = R.explain_pair("DBA", "DBB", [row(("enzyme", "BE0002638", "CYP3A4"), "inhibitor", inh="strong")],
                           [row(("enzyme", "BE0002638", "Cytochrome P450 3A4"), "substrate"),
                            row(("enzyme", "", "CYP3A4"), "substrate")])
    assert len(ex) == 1


def test_round4_shared_substrate_kind_does_not_depend_on_order():
    a = [row(("carrier", "BE9", "Serum albumin"), "substrate", known="no")]
    b = [row(("enzyme", "BE9", "Serum albumin"), "substrate", known="no")]
    (x,), _ = R.explain_pair("DBA", "DBB", a, b)
    (y,), _ = R.explain_pair("DBB", "DBA", b, a)
    assert x.kind == y.kind


# --------------------------------------- final blocker sweep (round 5) regressions --
@pytest.mark.parametrize("text,organ", [
    ("The drug is eliminated unchanged without hepatic metabolism.", "liver"),
    ("It is excreted unchanged in urine without undergoing hepatic metabolism.", "liver"),
    ("The drug is eliminated in feces without renal excretion.", "kidney"),
    ("The drug is eliminated by the liver rather than the kidneys.", "kidney"),
    ("The drug is mainly excreted in the urine, rather than in feces.", "bile_feces"),
    ("The drug is eliminated in feces rather than urine.", "kidney"),
    ("Excretion occurs in feces as opposed to urine.", "kidney"),
    ("Excreted in bile instead of urine.", "kidney"),
    ("Hepatic metabolism is absent.", "liver"), ("There is an absence of hepatic metabolism.", "liver"),
    ("The compound is devoid of hepatic metabolism.", "liver"), ("The drug lacks renal excretion.", "kidney"),
    ("Fecal excretion is nonexistent.", "bile_feces"), ("Urinary excretion is undetectable.", "kidney"),
    ("Renal excretion was below the limit of quantification.", "kidney"),
    ("Biliary excretion is unlikely to be significant.", "bile_feces"), ("Renal clearance is unimportant.", "kidney"),
    ("Renal excretion is essentially zero.", "kidney"), ("Renal excretion is virtually nil.", "kidney"),
    ("0% of the dose is excreted in urine.", "kidney"), ("The drug escapes hepatic metabolism.", "liver"),
    ("The drug bypasses hepatic first-pass metabolism.", "liver"),
    ("It is resistant to hepatic metabolism and excreted unchanged in urine.", "liver"),
    ("Free of hepatic metabolism.", "liver"),
])
def test_round5_denials_never_reach_the_clearing_list(text, organ):
    got = notes_of(text, organ)
    assert "negated_or_minor" in got and "other_subject_possible" not in got


@pytest.mark.parametrize("text,organ", [
    ("The drug is eliminated by the liver rather than the kidneys.", "liver"),
    ("The drug is eliminated in feces rather than urine.", "bile_feces"),
    ("It is excreted unchanged in urine without undergoing hepatic metabolism.", "kidney"),
    ("10% of the dose is excreted in urine.", "kidney"),
])
def test_round5_the_affirmed_organ_stays_clean(text, organ):
    assert notes_of(text, organ) == ()


# ------------------------------------------- Astra review (attribution, hedging, ids) --
def test_astra_a_sentence_naming_another_drug_is_flagged_with_that_name():
    text = S + "Ritonavir is mainly excreted in urine. The drug itself is eliminated in feces."
    ms, _ = R.organ_mentions("route_of_elimination", text, ["ritonavir"])
    kidney = [m for m in ms if m.organ == "kidney"][0]
    feces = [m for m in ms if m.organ == "bile_feces"][0]
    assert "other_drug_named" in kidney.notes and kidney.other_drugs == ("Ritonavir",)
    assert "other_drug_named" not in feces.notes and feces.other_drugs == ()


def test_astra_name_matching_is_whole_word_and_generic_substances_are_ignored():
    ms, _ = R.organ_mentions("route_of_elimination", S + "Excreted in urine as urea and water.", ["urea", "water", "ure"])
    assert ms[0].notes == () and ms[0].other_drugs == ()
    assert "urea" not in R.name_candidates("Excreted as urea") and "excreted" in R.name_candidates("Excreted as urea")


@pytest.mark.parametrize("text,organ", [
    ("It may be excreted in urine.", "kidney"),
    ("The drug is possibly eliminated via bile.", "bile_feces"),
    ("Renal excretion has not been confirmed.", "kidney"),
    ("Hepatic metabolism is unverified.", "liver"),
    ("The drug is thought to be metabolized in the liver.", "liver"),
    ("Biliary excretion is likely.", "bile_feces"),
])
def test_astra_hedged_routes_are_uncertain(text, organ):
    got = notes_of(text, organ)
    assert "uncertain_statement" in got and "negated_or_minor" not in got


def test_astra_unlikely_is_still_a_denial_not_a_hedge():
    assert "negated_or_minor" in notes_of("Biliary excretion is unlikely.", "bile_feces")


def test_astra_same_name_different_ids_are_both_kept():
    a = [row(("enzyme", "BE1", "Cytochrome P450 2C"), "inhibitor", inh="strong"),
         row(("enzyme", "BE2", "Cytochrome P450 2C"), "inhibitor", inh="strong")]
    b = [row(("enzyme", "BE1", "Cytochrome P450 2C"), "substrate"), row(("enzyme", "BE2", "Cytochrome P450 2C"), "substrate")]
    ex, _ = R.explain_pair("DBA", "DBB", a, b)
    assert sorted(x.protein_id for x in ex) == ["BE1", "BE2"]
    ex, und = R.explain_pair("DBA", "DBB", [row(("enzyme", "BE1", "X"), "binder"), row(("enzyme", "BE2", "X"), "binder")],
                             [row(("enzyme", "BE1", "X"), "binder"), row(("enzyme", "BE2", "X"), "binder")])
    assert ex == [] and und == ["X (BE1)", "X (BE2)"]
