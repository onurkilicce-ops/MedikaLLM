"""M-02 food/situation table: DrugBank food-interaction directives -> rows, times
read only from instruction sentences and always from the DRUG's point of view.
All texts are SYNTHETIC paraphrases of the sentence shapes seen in the data."""
from __future__ import annotations

import pytest

from src.timing import food, table
from src.timing.food import Span, classify, mineral_kind, pair_cells, timing_of, timing_text


def tt(text, row):
    return timing_text(timing_of(text, row))


# ------------------------------------------------------------- directions --
@pytest.mark.parametrize("text,row,expected", [
    # counted from the item
    ("Take on an empty stomach. Take at least 1 hour before or 2 hours after meals.", "meal",
     "≥1 sa önce veya ≥2 sa sonra"),
    ("Take separate from antacids. Take at least 2 hours before or after antacids.", "minerals_antacids",
     "≥2 sa önce veya ≥2 sa sonra"),
    ("Take before a meal. Take 30 minutes before breakfast.", "meal", "30 dk önce"),
    ("Take after a meal. Take within 30 minutes after a meal.", "meal", "≤30 dk sonra"),
    ("Take on an empty stomach. Take 30 minutes to 1 hour before breakfast.", "meal", "0,5–1 sa önce"),
    ("Take on an empty stomach. Take one hour before meals.", "meal", "1 sa önce"),
    ("Avoid multivalent ions. Separate medication administration by at least 4 hours.", "minerals_antacids",
     "≥4 sa önce veya ≥4 sa sonra"),
    # 'after taking antacids': still counted from the item
    ("Avoid antacids. Take at least 2 hours after taking antacids.", "minerals_antacids", "≥2 sa sonra"),
    # counted from the drug: the side flips
    ("Take on an empty stomach. Avoid food for at least 1 hour after taking this medication.", "meal",
     "≥1 sa önce"),
    ("Avoid multivalent ions. Antacids should be taken at least 4 hours after drug administration.",
     "minerals_antacids", "≥4 sa önce"),
    ("Take on an empty stomach. Food should be avoided for 2 hours before each dose.", "meal", "≥2 sa sonra"),
    # item is the subject, drug named after the time
    ("Avoid multivalent ions. Cations should be taken at least 6 hours before or 2 hours after the agent.",
     "minerals_antacids", "≥2 sa önce veya ≥6 sa sonra"),
])
def test_direction_is_from_the_drug_point_of_view(text, row, expected):
    assert tt("[SYNTHETIC] " + text, row) == expected


def test_caffeine_before_the_administration_is_flipped():
    t = timing_of("[SYNTHETIC] Avoid caffeine. Caffeine should be avoided for at least 12 hours before the "
                  "administration.", "caffeine")
    assert timing_text(t) == "≥12 sa sonra"


@pytest.mark.parametrize("text,row", [
    # measurement / missed-dose sentences are never instructions
    ("Take with food. Food delays the Cmax by 2 hours.", "meal"),
    ("Take with or without food. A high-fat meal reduces the AUC; absorption is delayed by 1 hour.", "meal"),
    ("Take at the same time every day. If more than 12 hours since your missed dose, skip it.", "routine"),
    # a sentence with more times than were read shows no time
    ("Avoid solid foods. Do not eat for at least 2 hours, and do not drink for at least 30 minutes before "
     "and after use.", "meal"),
    # the time is about something else than the row's item
    ("Take with food. Take 1 hour before bedtime.", "meal"),
])
def test_no_time_when_it_cannot_be_read_safely(text, row):
    assert timing_of("[SYNTHETIC] " + text, row) is None


def test_time_unit_and_bounds_are_kept():
    t = timing_of("[SYNTHETIC] Take on an empty stomach. Take 30 minutes to 2 hours before meals.", "meal")
    assert t.before == Span(0.5, 2.0, False) and t.after is None
    assert timing_text(t) == "0,5–2 sa önce"
    t = timing_of("[SYNTHETIC] Take after a meal. Take up to 1 hour after a meal.", "meal")
    assert t.after.at_most and timing_text(t) == "≤1 sa sonra"


def test_quote_is_the_original_sentence_not_the_normalised_one():
    s = "Take one hour before meals."
    t = timing_of("[SYNTHETIC] Take on an empty stomach. " + s, "meal")
    assert t.quote == s


# --------------------------------------------------------------- classify --
@pytest.mark.parametrize("entry,row,kind", [
    ("Avoid alcohol. [SYNTHETIC] Alcohol adds sedation.", "alcohol", "avoid"),
    ("Avoid excessive or chronic alcohol consumption. [SYNTHETIC]", "alcohol", "limit"),
    ("Avoid grapefruit products. [SYNTHETIC]", "grapefruit", "avoid"),
    ("Exercise caution with St. John's Wort. [SYNTHETIC]", "herbal", "limit"),
    ("Take with food. [SYNTHETIC]", "meal", "take_with"),
    ("Take with or without food. [SYNTHETIC]", "meal", "info"),
    ("Avoid milk and dairy products. [SYNTHETIC]", "dairy_calcium", "avoid"),
    ("Take with a full glass of water. [SYNTHETIC]", "water", "take_with"),
    ("Ensure consistent vitamin K intake. [SYNTHETIC]", "diet_other", "limit"),
])
def test_directive_maps_to_row_and_kind(entry, row, kind):
    c = classify(entry)
    assert (c.row, c.kind, c.source) == (row, kind, "drugbank")
    assert c.source_text == entry


def test_unknown_directive_is_kept_not_dropped():
    c = classify("[SYNTHETIC] Chew the tablet thoroughly. It tastes bitter.")
    assert c.row == "diet_other" and c.kind == "info"
    assert c.text == "[SYNTHETIC] Chew the tablet thoroughly."


def test_st_johns_wort_is_not_a_sentence_end():
    c = classify("Avoid St. John's Wort. [SYNTHETIC] It lowers levels.")
    assert c.row == "herbal" and c.kind == "avoid"


# -------------------------------------------------- selected drugs as ions --
def _ions(name, cats=()):
    c = mineral_kind(name, list(cats))
    return (set(c.ions), c.antacid, c.binder)


@pytest.mark.parametrize("name,cats,expected", [
    ("calcium carbonate", [], ({"calcium"}, True, False)),
    ("ferrous sulfate", [], ({"iron"}, False, False)),
    ("sucralfate", [], ({"aluminum"}, False, False)),
    ("magnesium oxide", [], ({"magnesium"}, False, False)),
    ("[synthetic] agent", ["Antacids"], (set(), True, False)),
    ("sodium bicarbonate", ["Antacids"], (set(), True, False)),
    ("cholestyramine", [], (set(), False, True)),
    # monovalent salts carry no multivalent ion; a broad category is not evidence of one
    ("potassium chloride", ["Mineral Supplements"], (set(), False, False)),
    ("sodium fluoride", ["Mineral Supplements"], (set(), False, False)),
    # parenteral / topical products: no oral chelation rule applies
    ("iron dextran", [], (set(), False, False)),
    ("ferric carboxymaltose", [], (set(), False, False)),
    ("edetate calcium disodium", [], (set(), False, False)),
    ("zinc oxide", [], (set(), False, False)),
    ("aluminum chloride", [], (set(), False, False)),
    ("[synthetic] agent", ["Anticoagulants"], (set(), False, False)),
    ("warfarin", [], (set(), False, False)),
])
def test_mineral_kind(name, cats, expected):
    assert _ions(name, cats) == expected


def _cells(*entries):
    return [classify(e) for e in entries]


def _o(drug_id, name, cats=()):
    return (drug_id, name, mineral_kind(name.lower(), list(cats)))


def test_pair_names_the_other_drug_and_the_rule_it_comes_from():
    cells = _cells("Avoid iron supplements. [SYNTHETIC]",
                   "Avoid multivalent ions. [SYNTHETIC] Take at least 2 hours before or after these ions.")
    out = pair_cells("DB00001", cells, [_o("DB00001", "X"), _o("DB00002", "Synthetic Aluminum hydroxide")])
    assert len(out) == 1
    c = out[0]
    assert c.with_drug_id == "DB00002" and c.row == "selected_drugs" and c.kind == "separate"
    assert c.text.startswith("Synthetic Aluminum hydroxide: ayrı alın (alüminyum içerir; ağızdan birlikte alındığında).")
    assert "Dayanak: «Çok değerlikli iyonlarla" in c.text


def test_pair_never_uses_a_rule_about_another_single_ion():
    cells = _cells("Avoid iron supplements. [SYNTHETIC]")
    assert pair_cells("DB00001", cells, [_o("DB00002", "Synthetic Aluminum hydroxide")]) == []


def test_pair_uses_the_rule_about_the_ion_the_drug_carries():
    cells = _cells("Take at least 2 hours before or after iron supplements. [SYNTHETIC] Iron lowers absorption.")
    out = pair_cells("DB00001", cells, [_o("DB00002", "Ferrous sulfate")])
    assert len(out) == 1 and "demir içerir" in out[0].text
    assert timing_text(out[0].timing) == "≥2 sa önce veya ≥2 sa sonra"


def test_pair_al_mg_antacid_rule_is_not_applied_to_iron_or_calcium():
    cells = _cells("Take separate from antacids. [SYNTHETIC] Take at least 2 hours before or 6 hours after "
                   "taking antacids containing aluminum or magnesium.")
    others = [_o("DB00002", "Ferrous sulfate"), _o("DB00003", "Calcium carbonate"),
              _o("DB00004", "Magnesium hydroxide")]
    out = pair_cells("DB00001", cells, others)
    assert [c.with_drug_id for c in out] == ["DB00004"]


def test_pair_general_antacid_rule_applies_to_any_antacid():
    cells = _cells("Take separate from antacids. Take at least 2 hours before or after antacids. [SYNTHETIC]")
    out = pair_cells("DB00001", cells, [_o("DB00002", "Sodium bicarbonate", ["Antacids"]),
                                         _o("DB00003", "Potassium chloride", ["Mineral Supplements"])])
    assert [c.with_drug_id for c in out] == ["DB00002"] and "antasit içerir" in out[0].text


def test_pair_multivalent_rule_is_not_applied_to_monovalent_or_parenteral_salts():
    cells = _cells("Avoid multivalent ions. [SYNTHETIC] Separate administration by at least 2 hours.")
    others = [_o("DB00002", "Potassium chloride", ["Mineral Supplements"]), _o("DB00003", "Sodium fluoride"),
              _o("DB00004", "Iron dextran"), _o("DB00005", "Zinc oxide")]
    assert pair_cells("DB00001", cells, others) == []


def test_calcium_drug_gets_a_rule_that_names_calcium():
    cells = _cells("Avoid milk and dairy products. [SYNTHETIC] Calcium binds the drug.")
    out = pair_cells("DB00001", cells, [_o("DB00002", "Synthetic calcium carbonate")])
    assert len(out) == 1 and "kalsiyum içerir" in out[0].text


def test_milk_only_rule_is_not_extended_to_a_calcium_drug():
    cells = _cells("Avoid milk and dairy products. [SYNTHETIC] Take at least 2 hours before or after milk.")
    assert pair_cells("DB00001", cells, [_o("DB00002", "Calcium carbonate")]) == []


def test_info_and_take_with_cells_are_never_paired():
    cells = _cells("Administer calcium supplement. [SYNTHETIC]")
    assert pair_cells("DB00001", cells, [_o("DB00002", "Calcium carbonate")]) == []


# ------------------------------------------- review findings (regressions) --
M = "minerals_antacids"


@pytest.mark.parametrize("text,row,expected", [
    # 'after taking THE antacid' is counted from the antacid
    ("Take agent 1 hour before or 4 hours after taking the antacid.", M, "1 sa önce veya 4 sa sonra"),
    # the item's own use / dose is not the drug
    ("Take at least 4 hours after antacid use.", M, "≥4 sa sonra"),
    ("Take 2 hours before calcium supplement doses.", M, "2 sa önce"),
    ("Take at least 2 hours before or 4 hours after iron supplement dosing.", M, "≥2 sa önce veya ≥4 sa sonra"),
    # a prohibited window is a minimum separation, never '≤'
    ("Do not take iron supplements within 2 hours after taking this medication.", M, "≥2 sa önce"),
    ("Do not take antacids up to 2 hours before this medication.", M, "≥2 sa sonra"),
    ("Do not take mineral products up to 2 hours before or after this medication.", M, "≥2 sa önce veya ≥2 sa sonra"),
    # lower bounds of 'more than' / avoid sentences are kept
    ("Take more than 1 hour before or 2 hours after a meal.", "meal", "≥1 sa önce veya ≥2 sa sonra"),
    ("Do not have food or water for 10 minutes after administration.", "meal", "≥10 dk önce"),
    ("Avoid consuming food 2 hours before and 1 hour after each dose.", "meal", "≥1 sa önce veya ≥2 sa sonra"),
    # a positive 'within' stays an upper bound
    ("Take within 30 minutes after a meal.", "meal", "≤30 dk sonra"),
])
def test_review_direction_and_bounds(text, row, expected):
    assert tt(text + " [SYNTHETIC]", row) == expected


def test_review_one_sided_separate_by_is_not_made_two_sided():
    assert timing_of("Separate the agent from these products by at least 2 hours before "
                     "administration. [SYNTHETIC]", "dairy_calcium") is None


@pytest.mark.parametrize("entry", [
    "Take with food. [SYNTHETIC] Separate administration from antacids by at least 2 hours.",
    "Take on an empty stomach. [SYNTHETIC] Space doses of cholestyramine by at least 4 hours.",
])
def test_review_separate_by_about_another_item_is_not_shown_in_this_row(entry):
    c = classify(entry)
    assert c.row == "meal" and c.timing is None


@pytest.mark.parametrize("entry,kind,word", [
    ("Avoid multivalent ions.", "avoid", "almayın"),
    ("Avoid concomitant mineral supplements.", "avoid", "almayın"),
    ("Avoid goitrogenic foods.", "avoid", "kaçının"),
    ("Avoid high-fiber foods.", "avoid", "kaçının"),
    ("Do not take with bile acid sequestrants.", "avoid", "almayın"),
])
def test_review_kind_matches_its_turkish_text(entry, kind, word):
    c = classify(entry + " [SYNTHETIC]")
    assert c.kind == kind and c.text.endswith(word)


def test_review_no_directive_says_avoid_but_writes_take_separately():
    from src.timing.food import _D
    assert not [t for _, _, k, t in _D if k == "avoid" and t.endswith("ayrı alın")]
    assert not [t for _, _, k, t in _D if k == "separate" and t.endswith("almayın")]


def test_review_table_422_doc_says_one_to_ten():
    from src.timing.router import _TABLE_RESPONSES
    assert "1-10" in _TABLE_RESPONSES[422]["description"]


# ---------------------------------------------------------- table.build --
def _fake(monkeypatch, drugs, foods, cats=None):
    by_id = {d: (i + 1, n) for i, (d, n) in enumerate(drugs)}
    fd = {by_id[d][0]: es for d, es in foods.items()}
    cd = {by_id[d][0]: cs for d, cs in (cats or {}).items()}
    monkeypatch.setattr(table, "read_table_data", lambda ids: (by_id, fd, cd))


def test_build_rows_columns_and_missing_drug(monkeypatch):
    _fake(monkeypatch, [("DB00001", "[SYNTHETIC] Agent A"), ("DB00002", "[SYNTHETIC] Agent B")],
          {"DB00001": ["Avoid alcohol. [SYNTHETIC]",
                       "Take on an empty stomach. Take at least 1 hour before or 2 hours after meals. [SYNTHETIC]"],
           "DB00002": []})
    r = table.build(["DB00001", "DB00002", "DB99999"]).model_dump(mode="json")
    assert r["schema_version"] == "m02-timing-table/1"
    assert [d["found"] for d in r["drugs"]] == [True, True, False]
    assert [d["has_food_entries"] for d in r["drugs"]] == [True, False, False]
    assert [x["row_id"] for x in r["rows"]] == ["meal", "alcohol"]  # ROWS order, only rows with cells
    meal = r["rows"][0]["cells"]
    assert list(meal) == ["DB00001"]
    c = meal["DB00001"][0]
    assert c["timing_text"] == "≥1 sa önce veya ≥2 sa sonra"
    assert c["before"] == {"low_hours": 1.0, "high_hours": None, "at_least": True, "at_most": False}
    assert c["timing_quote"] == "Take at least 1 hour before or 2 hours after meals. [SYNTHETIC]"
    assert "güvenli" in r["notice"]


def test_build_shows_label_cells_with_their_product_without_product_choice(monkeypatch):
    _fake(monkeypatch, [("DB00001", "Ciprofloxacin"), ("DB00002", "Sucralfate")], {})
    r = table.build(["DB00001", "DB00002"]).model_dump(mode="json")
    rows = {x["row_id"]: x["cells"] for x in r["rows"]}
    dairy = rows["dairy_calcium"]["DB00001"][0]
    assert dairy["source"] == "label" and "(UK)" in dairy["product"]
    assert dairy["timing_text"] == "1–2 sa önce veya ≥4 sa sonra"
    assert dairy["source_url"].startswith("https://")
    pair = rows["selected_drugs"]["DB00001"]
    assert [p["with_drug_id"] for p in pair] == ["DB00002"]
    assert "DB00002" not in rows["selected_drugs"]  # the label rule is about ciprofloxacin, not both ways


def test_build_empty_rows_when_no_statements(monkeypatch):
    _fake(monkeypatch, [("DB00001", "[SYNTHETIC] Agent A")], {"DB00001": ["  "]})
    r = table.build(["DB00001"])
    assert r.rows == [] and r.drugs[0].has_food_entries is False


def test_request_validation():
    from pydantic import ValidationError
    assert table.TableRequest(drug_ids=["DB00001"]).drug_ids == ["DB00001"]
    for bad in ([], ["DB00001", "DB00001"], ["db00001"], ["DB0001"], [f"DB{i:05d}" for i in range(11)]):
        with pytest.raises(ValidationError):
            table.TableRequest(drug_ids=bad)
    with pytest.raises(ValidationError):
        table.TableRequest(drug_ids=["DB00001"], foods=["milk"])


def test_every_row_label_is_turkish_and_unique():
    ids = [r for r, _ in food.ROWS]
    assert len(ids) == len(set(ids))
    assert all(food.ROW_LABEL[r] for r in ids)
