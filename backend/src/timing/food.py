"""DrugBank food-interaction text -> one table of timing instructions.

DrugBank stores each food interaction as a short directive followed by an
explanation ("Take on an empty stomach. Take at least 1 hour before or 2 hours
after meals."). The directives form a small closed vocabulary (about 70 in the
whole database), so each one is mapped explicitly to a table row and a Turkish
instruction. A time is read only from an INSTRUCTION sentence ("Take ...",
"Separate ...", "Allow ...", "should be taken ..."); measurement sentences
("Food delays the Cmax by 30 minutes") and missed-dose notes are never read as
a time. Pure functions: no database, no LLM. The DrugBank sentence always goes
with the cell.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

# ------------------------------------------------------------------ rows --
ROWS: List[Tuple[str, str]] = [
    ("meal", "Yemek (aç / tok)"),
    ("dairy_calcium", "Süt ürünleri ve kalsiyum"),
    ("minerals_antacids", "Antasit, demir, mineraller ve bağlayıcılar"),
    ("selected_drugs", "Seçilen diğer ilaçlarla"),
    ("grapefruit", "Greyfurt"),
    ("alcohol", "Alkol"),
    ("caffeine", "Kafein"),
    ("herbal", "Bitkisel ürünler ve takviyeler"),
    ("water", "Su ve sıvı"),
    ("diet_other", "Diğer besin ve diyet"),
    ("routine", "Kullanım düzeni"),
]
ROW_LABEL = dict(ROWS)

# kind: how strong the instruction is (drives the cell colour on screen)
#   avoid | separate | limit | take_with | take_without | info
_D = [
    # meal
    (r"take with or without food", "meal", "info", "Yemekle veya yemeksiz alınabilir"),
    (r"take with a high[- ]fat meal", "meal", "take_with", "Yağlı bir yemekle alın"),
    (r"take with food", "meal", "take_with", "Yemekle alın"),
    (r"take on an empty stomach", "meal", "take_without", "Aç karnına alın"),
    (r"take separate from meals", "meal", "separate", "Yemeklerden ayrı alın"),
    (r"take before a meal", "meal", "take_without", "Yemekten önce alın"),
    (r"take after a meal", "meal", "take_with", "Yemekten sonra alın"),
    (r"do not take with or immediately after a high[- ]fat meal", "meal", "avoid", "Yağlı yemekle veya hemen sonrasında almayın"),
    (r"avoid fatty foods", "meal", "avoid", "Yağlı yiyeceklerden kaçının"),
    (r"avoid solid foods", "meal", "avoid", "Katı yiyeceklerden kaçının"),
    # dairy / calcium
    (r"avoid milk and dairy products", "dairy_calcium", "avoid", "Süt ve süt ürünleriyle birlikte almayın"),
    (r"avoid calcium supplements/calcium rich foods", "dairy_calcium", "avoid", "Kalsiyum takviyesi ve kalsiyumdan zengin besinlerle birlikte almayın"),
    (r"take at least 2 hours before or after calcium supplements", "dairy_calcium", "separate", "Kalsiyum takviyesinden ayrı alın"),
    (r"administer calcium supplement", "herbal", "info", "Kalsiyum takviyesi önerilir"),
    # minerals / antacids
    (r"avoid multivalent ions", "minerals_antacids", "avoid", "Çok değerlikli iyonlarla (kalsiyum, demir, magnezyum, alüminyum, çinko) birlikte almayın"),
    (r"take separate from antacids", "minerals_antacids", "separate", "Antasitlerden ayrı alın"),
    (r"avoid antacids", "minerals_antacids", "avoid", "Antasitlerle birlikte almayın"),
    (r"avoid iron supplements", "minerals_antacids", "avoid", "Demir takviyesiyle birlikte almayın"),
    # grapefruit / juice
    (r"avoid grapefruit products", "grapefruit", "avoid", "Greyfurt ve greyfurt suyundan kaçının"),
    (r"exercise caution with grapefruit products", "grapefruit", "limit", "Greyfurt ürünlerinde dikkatli olun"),
    (r"avoid fruit juice", "diet_other", "avoid", "Meyve suyuyla almayın"),
    # alcohol
    (r"avoid excessive or chronic alcohol consumption", "alcohol", "limit", "Aşırı veya sürekli alkolden kaçının"),
    (r"avoid alcohol", "alcohol", "avoid", "Alkolden kaçının"),
    # caffeine
    (r"limit caffeine intake", "caffeine", "limit", "Kafeini sınırlayın"),
    (r"avoid caffeine", "caffeine", "avoid", "Kafeinden kaçının"),
    (r"avoid xanthines", "caffeine", "avoid", "Ksantinlerden (kafein, teofilin) kaçının"),
    # herbal / supplements
    (r"avoid st\.? john'?s wort", "herbal", "avoid", "Sarı kantarondan (St. John's Wort) kaçının"),
    (r"exercise caution with st\.? john'?s wort", "herbal", "limit", "Sarı kantaronda dikkatli olun"),
    (r"avoid herbs and supplements with anticoagulant/antiplatelet activity", "herbal", "avoid",
     "Kan sulandırıcı etkili bitki ve takviyelerden kaçının (sarımsak, zencefil, ginkgo …)"),
    (r"avoid echinacea", "herbal", "avoid", "Ekinezyadan kaçının"),
    (r"avoid hypertensive herbs", "herbal", "avoid", "Tansiyon yükseltici bitkilerden kaçının"),
    (r"avoid natural licorice", "herbal", "avoid", "Doğal meyan kökünden kaçının"),
    (r"administer vitamin supplements", "herbal", "info", "Vitamin takviyesi gerekebilir"),
    (r"administer iron supplement", "herbal", "info", "Demir takviyesi gerekebilir"),
    (r"administer folic acid supplement", "herbal", "info", "Folik asit takviyesi gerekebilir"),
    (r"avoid vitamin a supplements", "herbal", "avoid", "A vitamini takviyesinden kaçının"),
    # water / fluids
    (r"take with a full glass of water", "water", "take_with", "Bir bardak dolusu suyla alın"),
    (r"take with plain water", "water", "take_with", "Yalnız sade suyla alın"),
    (r"take with fluids", "water", "take_with", "Sıvıyla alın"),
    (r"drink plenty of fluids", "water", "take_with", "Bol sıvı için"),
    # other diet
    (r"avoid potassium-containing products", "diet_other", "avoid", "Potasyum içeren ürünlerden kaçının"),
    (r"increase consumption of potassium-rich foods", "diet_other", "info", "Potasyumdan zengin besinleri artırın"),
    (r"limit salt intake", "diet_other", "limit", "Tuzu sınırlayın"),
    (r"avoid tyramine-containing foods and supplements", "diet_other", "avoid", "Tiramin içeren besinlerden (eski peynir, salam …) kaçının"),
    (r"avoid foods rich in vitamin k", "diet_other", "avoid", "K vitamininden zengin besinlerden kaçının"),
    (r"ensure consistent vitamin k intake", "diet_other", "limit", "K vitamini alımını sabit tutun"),
    (r"avoid drastic dietary changes", "diet_other", "avoid", "Ani diyet değişikliklerinden kaçının"),
    (r"do not take with bran and high fiber foods", "diet_other", "avoid", "Kepek ve yüksek lifli besinlerle birlikte almayın"),
    (r"take with foods containing vitamin c", "diet_other", "take_with", "C vitamini içeren besinlerle alın"),
    (r"limit foods and supplements high in vitamin c", "diet_other", "limit", "C vitamininden zengin besin ve takviyeleri sınırlayın"),
    (r"limit iodine intake", "diet_other", "limit", "İyot alımını sınırlayın"),
    (r"avoid iodine-containing foods and supplements", "diet_other", "avoid", "İyot içeren besin ve takviyelerden kaçının"),
    (r"avoid chocolate", "diet_other", "avoid", "Çikolatadan kaçının"),
    (r"avoid histamine-containing foods and supplements", "diet_other", "avoid", "Histamin içeren besinlerden kaçının"),
    (r"avoid a ketogenic diet", "diet_other", "avoid", "Ketojenik diyetten kaçının"),
    (r"limit the intake of phenylalanine and tyrosine", "diet_other", "limit", "Fenilalanin ve tirozin alımını sınırlayın"),
    (r"limit foods and supplements high in flavonoids", "diet_other", "limit", "Flavonoidden zengin besinleri sınırlayın"),
    (r"avoid dietary avidin", "diet_other", "avoid", "Çiğ yumurta akından kaçının"),
    (r"take with a light meal or snack", "meal", "take_with", "Hafif bir yemek veya atıştırmalıkla alın"),
    (r"avoid concomitant mineral supplements", "minerals_antacids", "avoid", "Mineral takviyeleriyle birlikte almayın"),
    (r"take at least 2 hours before or after iron supplements", "minerals_antacids", "separate", "Demir takviyesinden ayrı alın"),
    (r"do not take with bile acid sequestrants", "minerals_antacids", "avoid", "Safra asidi bağlayıcılarla (kolestiramin vb.) birlikte almayın"),
    (r"avoid high-fiber foods", "diet_other", "avoid", "Yüksek lifli besinlerden kaçının"),
    (r"avoid avocado", "diet_other", "avoid", "Avokadodan kaçının"),
    (r"avoid foods high in furanocoumarins", "diet_other", "avoid", "Furanokumarin içeren besinlerden (greyfurt, kereviz …) kaçının"),
    (r"avoid goitrogenic foods", "diet_other", "avoid", "Guatrojenik besinlerden (soya, lahana, brokoli …) kaçının"),
    (r"avoid foods rich in citrate", "diet_other", "avoid", "Sitrattan zengin besinlerden kaçının"),
    (r"administer vitamin a supplementation", "herbal", "info", "A vitamini takviyesi önerilir"),
    # routine
    (r"take at the same time every day", "routine", "info", "Her gün aynı saatte alın"),
    (r"no food interactions are expected", "routine", "info", "Besin etkileşimi beklenmiyor"),
]
DIRECTIVES = [(re.compile(r"^\s*" + rx + r"\b", re.I), row, kind, tr) for rx, row, kind, tr in _D]

# ------------------------------------------------------------- timing --
_WORDS = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "eight": "8", "twelve": "12",
          "half an?": "0.5", "an?": "1"}
_N1 = r"\d+(?:[.,]\d+)?"
_NUM = rf"({_N1})(?:\s*(?:-|–|to)\s*({_N1}))?"
_UNIT = r"(minutes?|mins?|hours?|hrs?|h)\b"
# '30 minutes to 2 hours before' (two units)
_MIXED = re.compile(rf"({_N1})\s*(minutes?|mins?|hours?|hrs?)\s*(?:-|–|to)\s*({_N1})\s*(minutes?|mins?|hours?|hrs?)\s*"
                    r"(?:before|prior to)\b", re.I)
_AT_MOST = re.compile(r"\b(?:within|up to|no more than|not more than)\s*$", re.I)
# What the time is measured against, per row ('before meals', 'after antacids').
_ROW_ITEM = {
    "meal": r"meals?|food|eating|breakfast|lunch|dinner|snacks?|a meal|first meal|high[- ]fat meal|food or drink",
    "dairy_calcium": r"dairy|milk|calcium",
    "minerals_antacids": r"antacids?|iron|calcium|magnesium|alumin\w*|zinc|(?:multivalent|polyvalent|divalent) "
                         r"(?:ions|cations)|cations|minerals?|(?:\w+\s+)?supplements?|(?:containing\s+)?products?|"
                         r"(?:bile acid )?sequestrants?",
    "diet_other": r"bran|fiber|fibre|foods?",
    "caffeine": r"caffeine|coffee",
    "grapefruit": r"grapefruit",
    "alcohol": r"alcohol",
}
# the time is counted from the DRUG ('after taking this medication', 'before each dose',
# 'after drug X administration')
_DRUG_OBJECT = re.compile(r"\s*(?:(?:each|the|a|its|every|your)\s+)?"
                          r"(?:(?!before\b|after\b|eating\b|meals?\b|food\b|breakfast\b)\w+\s+){0,2}?"
                          r"(?:administration|use|using|taking|dosing|doses?|this (?:medication|drug|medicine)"
                          r"|the (?:medication|drug))\b", re.I)
# every time quantity of a sentence; a sentence with more of them than were read is not
# shown as a time (its sentence is shown instead): 'Avoid eating for at least 2 hours, and
# drinking for 30 minutes ...' (two times, one read)
_ANY_TIME = re.compile(r"\b\d+(?:[.,]\d+)?\s*(?:(?:-|–|to)\s*\d+(?:[.,]\d+)?\s*)?(?:minutes?|mins?|hours?|hrs?)\b", re.I)
# a sentence that gives an instruction may carry a time
_INSTRUCTION = re.compile(r"^\s*(?:take|separate|allow|administer|space|wait|avoid|do not|should be taken|"
                          r"\w+(?:\s+\w+){0,3}\s+should be (?:taken|administered|given))\b|\bshould be (?:taken|"
                          r"administered|given)\b|\bshould (?:be avoided|avoid)\b|^\s*levothyroxine\b|"
                          r"\bseparate medication administration\b", re.I)
# measurement / missed-dose sentences are never instructions
_NOT_INSTRUCTION = re.compile(r"\b(?:cmax|auc|bioavailability|absorption is (?:increased|reduced|delayed)|delays?|"
                              r"reduction in|missed dose|since your|more than \d+\s*hours since)\b", re.I)
_BEFORE_OR_AFTER = re.compile(
    rf"(?:at least|approximately|about)?\s*{_NUM}\s*{_UNIT}\s*(?:before|prior to)\s*(?:or|and)\s*"
    rf"(?:at least\s*)?(?:{_NUM}\s*{_UNIT}\s*)?after\b", re.I)
_SEPARATE_BY = re.compile(rf"\b(?:separate|space)\w*\b[^.]*?\bby (?:at least |approximately )?{_NUM}\s*{_UNIT}", re.I)
_BEFORE = re.compile(rf"(?:at least\s*|approximately\s*|about\s*)?{_NUM}\s*{_UNIT}\s*(?:before|prior to)\b", re.I)
_AFTER = re.compile(rf"(?:at least\s*|for at least\s*)?{_NUM}\s*{_UNIT}\s*after\b", re.I)
_AT_LEAST = re.compile(r"\b(?:at least|at leats|more than|no less than|not less than)\b", re.I)
_AT_LEAST_BEFORE = re.compile(r"\b(?:at least|at leats|more than|no less than|not less than)\s*$", re.I)
# a prohibited window ('Do not take X within 2 hours after ...', 'Avoid food 2 hours before
# ...') is a MINIMUM separation, never an upper bound
_PROHIBIT = re.compile(r"^\s*(?:do not|don't|never|avoid)\b|\bshould not\b|\bshould (?:be avoided|avoid)\b", re.I)
# specific item words of each row (generic 'products', 'supplements', 'foods' left out): used
# to tell that a 'Separate ... by N hours' sentence is about ANOTHER row's item
_SPECIFIC = {
    "meal": r"meals?|food|eating|breakfast|lunch|dinner|snacks?",
    "dairy_calcium": r"dairy|milk|calcium",
    "minerals_antacids": r"antacids?|iron|calcium|magnesium|alumin\w*|zinc|multivalent|polyvalent|divalent|cations|"
                         r"minerals?|sequestrants?|cholestyramine|colestipol|colesevelam|sucralfate",
    "diet_other": r"bran|fiber|fibre",
    "caffeine": r"caffeine|coffee",
    "grapefruit": r"grapefruit",
    "alcohol": r"alcohol",
}


def _words_to_digits(s: str) -> str:
    for w, d in _WORDS.items():
        s = re.sub(rf"\b{w}\s+(?=(?:minutes?|hours?)\b)", d + " ", s, flags=re.I)
    return s


def _hours(n: str, unit: str) -> float:
    v = float(n.replace(",", "."))
    return round(v / 60.0, 4) if unit.lower().startswith("m") else v


@dataclass(frozen=True)
class Span:
    low: float
    high: Optional[float]      # None = a single value
    at_least: bool
    at_most: bool = False      # 'within 30 minutes after', 'up to 1 hour after'


@dataclass(frozen=True)
class Timing:
    before: Optional[Span]     # take the DRUG this long before the item
    after: Optional[Span]      # or take the DRUG this long after the item
    quote: str                 # the instruction sentence the time came from


def _span(m, i: int, at_least: bool) -> Optional[Span]:
    a, b, unit = m.group(i), m.group(i + 1), m.group(i + 2)
    if a is None or unit is None:
        return None
    return Span(_hours(a, unit), _hours(b, unit) if b else None, at_least)


def _sentences(text: str) -> List[str]:
    # 'St. John's Wort' and decimals are not sentence ends
    masked = re.sub(r"\bSt\.", "St\x01", text)
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z])", masked)
    return [p.replace("\x01", ".").strip() for p in parts if p.strip()]


def _is_item(row: Optional[str], text: str) -> bool:
    if row is None or row not in _ROW_ITEM:
        return True
    return bool(re.match(rf"\s*(?:\w+\s+){{0,4}}?(?:{_ROW_ITEM[row]})\b", text, re.I))


def _item_before(row: Optional[str], prefix: str) -> bool:
    return row in _ROW_ITEM and bool(re.search(rf"\b(?:{_ROW_ITEM[row]})\b", prefix, re.I))


def _object(row: Optional[str], s: str, start: int, end: int) -> str:
    """'item' when the time is counted from the row's item ('2 hours after meals'),
    'drug' when it is counted from the drug ('after taking this medication', 'before
    each dose', 'before or 2 hours after drug X' with the item as subject),
    '' when it is about something else ('before bedtime')."""
    tail = s[end:end + 80]
    d = _DRUG_OBJECT.match(tail)
    if d and row in _ROW_ITEM and re.search(rf"\b(?:{_ROW_ITEM[row]})\b", d.group(0), re.I):
        d = None  # the item's own use / dose: 'after antacid use', 'before calcium supplement doses'
    item_next = row in _ROW_ITEM and re.match(rf"\s*(?:(?:the|a|an|any|other)\s+)?(?:of\b|(?:{_ROW_ITEM[row]})\b)",
                                              tail[d.end():] if d else "", re.I)
    if d and not item_next:
        # 'after drug X administration (to take antacids)'; but 'after taking antacids' and
        # 'after administration of mineral supplements' are counted from the item
        return "drug"
    if _is_item(row, tail):
        return "item"
    if _item_before(row, s[:start]):
        return "drug"   # the item is the subject: 'cations ... 6 hours before or 2 hours after drug X'
    return ""


def _flip(t: "Timing") -> "Timing":
    # counted from the drug: the item comes X before the drug -> the drug comes X AFTER the item
    return Timing(t.after, t.before, t.quote)


def timing_of(text: str, row: Optional[str] = None) -> Optional[Timing]:
    """The first time stated in an instruction sentence of the entry, from the
    DRUG's point of view: 'before' = take the drug this long before the row's item,
    'after' = take it this long after the item."""
    for s0 in _sentences(text):
        if not _INSTRUCTION.search(s0) or _NOT_INSTRUCTION.search(s0):
            continue
        s = _words_to_digits(s0)
        n_times = len(_ANY_TIME.findall(s))
        if n_times > 2:
            continue  # too many times in one sentence to read safely; the sentence is shown
        def whole(m) -> bool:  # the match must hold every time of the sentence
            return len(_ANY_TIME.findall(m.group(0))) >= n_times

        prohibit = bool(_PROHIBIT.search(s))

        def lower_bound(m) -> bool:
            return prohibit or bool(_AT_LEAST.search(m.group(0)) or _AT_LEAST_BEFORE.search(s[:m.start()]))

        m = _MIXED.search(s)
        if m and whole(m):
            obj = _object(row, s, m.start(), m.end())
            if obj:
                sp = Span(_hours(m.group(1), m.group(2)), _hours(m.group(3), m.group(4)), lower_bound(m))
                t = Timing(sp, None, s0)
                return _flip(t) if obj == "drug" else t
        m = _BEFORE_OR_AFTER.search(s)
        if m and whole(m):
            obj = _object(row, s, m.start(), m.end())
            if obj:
                at_least = lower_bound(m)
                before = _span(m, 1, at_least)
                after = _span(m, 4, at_least) or before  # '2 hours before or after X'
                t = Timing(before, after, s0)
                return _flip(t) if obj == "drug" else t
        m = _SEPARATE_BY.search(s)
        if m and whole(m):
            span_text = m.group(0)
            own = row not in _SPECIFIC or re.search(rf"\b(?:{_ROW_ITEM[row]})\b", span_text, re.I)
            other = any(re.search(rf"\b(?:{rx})\b", span_text, re.I) for r, rx in _SPECIFIC.items() if r != row)
            one_sided = re.match(r"\s*(?:before|after|prior to)\b", s[m.end():], re.I)
            if one_sided or (other and not own):
                # 'by 2 hours before administration' names one side only; 'Separate ... from
                # antacids by 2 hours' in the meal row is about another item: no time here
                continue
            sp = _span(m, 1, True)
            return Timing(sp, sp, s0)
        found = []
        for rx, side in ((_BEFORE, "before"), (_AFTER, "after")):
            x = rx.search(s)
            if not x:
                continue
            obj = _object(row, s, x.start(), x.end())
            if not obj:
                continue
            at_most = bool(_AT_MOST.search(s[:x.start()])) and not prohibit
            sp = _span(x, 1, lower_bound(x) or (prohibit and bool(_AT_MOST.search(s[:x.start()]))))
            sp = Span(sp.low, sp.high, sp.at_least, at_most)
            # counted from the drug, the side flips: 'food 2 h before each dose' -> drug 2 h after food
            if obj == "drug":
                side = "after" if side == "before" else "before"
            found.append((side, sp))
        # every time in the sentence must be accounted for ('Avoid eating for at least 2 hours,
        # and drinking for 30 minutes ...' reads only one: not shown as a time)
        if found and len({side for side, _ in found}) == len(found) and len(found) >= n_times:
            d = dict(found)
            return Timing(d.get("before"), d.get("after"), s0)
    return None


# --------------------------------------------------------------- cells --
@dataclass
class Cell:
    row: str
    kind: str
    text: str                  # Turkish instruction
    timing: Optional[Timing]
    source_text: str           # the whole DrugBank entry (or label excerpt)
    source: str                # 'drugbank' | 'label'
    source_ref: str = ""
    source_url: str = ""
    product: str = ""          # label rules: the product the statement belongs to
    with_drug_id: str = ""     # selected_drugs row: the other selected drug


def classify(entry: str) -> Cell:
    """One DrugBank food-interaction entry -> one cell. An unknown directive is
    kept in 'diet_other' with the English text, never dropped."""
    for rx, row, kind, tr in DIRECTIVES:
        if rx.search(entry):
            return Cell(row, kind, tr, timing_of(entry, row), entry, "drugbank")
    head = _sentences(entry)[0] if entry.strip() else entry
    return Cell("diet_other", "info", head, timing_of(entry, "diet_other"), entry, "drugbank")


# ---------------------------------------------- selected drugs as minerals --
# Which multivalent ions a selected drug carries, read from its name. Only ORAL chelation is
# what the food-interaction rules are about, so parenteral and topical products are left out.
_ION_NAME = {
    "calcium": r"calcium",
    "iron": r"ferrous|ferric|iron|polysaccharide-iron",
    "magnesium": r"magnesium",
    "aluminum": r"alumin(?:i)?um|sucralfate",
    "zinc": r"zinc",
    "other": r"bismuth|lanthanum",
}
_ION_TR = {"calcium": "kalsiyum", "iron": "demir", "magnesium": "magnezyum", "aluminum": "alüminyum",
           "zinc": "çinko", "other": "çok değerlikli iyon"}
_MULTIVITAMIN = re.compile(r"\bmultivitamins?\b|\bmultiple vitamins?\b", re.I)
_BINDER = re.compile(r"\b(?:cholestyramine|colestipol|colesevelam|sevelamer)\b", re.I)
_NOT_ORAL = re.compile(r"\b(?:dextran|sucrose|carboxymaltose|derisomaltose|isomaltoside|ferumoxytol|"
                       r"pyrophosphate citrate|sodium ferric gluconate|edetate|zinc oxide|zinc pyrithione|"
                       r"alumin(?:i)?um chloride|alumin(?:i)?um acetate)\b", re.I)
_ANTACID_CATEGORY = re.compile(r"\bantacids?\b", re.I)
_ANTACID_NAME = re.compile(r"\bantacids?\b|\b(?:alumin(?:i)?um|magnesium) hydroxide\b|\b(?:calcium|magnesium) carbonate\b|"
                           r"\bsodium bicarbonate\b|\bmagaldrate\b|\bhydrotalcite\b", re.I)


@dataclass(frozen=True)
class Carrier:
    ions: frozenset        # multivalent ions carried ('calcium', 'iron', ...)
    antacid: bool          # an antacid (by name or DrugBank category)
    binder: bool           # a bile-acid sequestrant / phosphate binder

    def __bool__(self) -> bool:
        return bool(self.ions or self.antacid or self.binder)

    def label(self) -> str:
        parts = [_ION_TR[i] for i in sorted(self.ions)]
        if self.antacid and not parts:
            parts.append("antasit")
        if self.binder:
            parts.append("bağlayıcı")
        return ", ".join(parts)


NO_CARRIER = Carrier(frozenset(), False, False)


def mineral_kind(name: str, categories: Sequence[str]) -> Carrier:
    """What a selected drug carries that an 'avoid multivalent ions / antacids / calcium'
    instruction is about. Monovalent salts (sodium, potassium, fluoride) carry no ions;
    a 'Mineral Supplements' category alone is not evidence of an ion."""
    n = name or ""
    if _NOT_ORAL.search(n):
        return NO_CARRIER
    ions = frozenset(i for i, rx in _ION_NAME.items() if re.search(rf"\b(?:{rx})\b", n, re.I))
    if _MULTIVITAMIN.search(n):
        ions = ions | {"calcium", "iron", "magnesium", "zinc"}
    antacid = bool(_ANTACID_NAME.search(n) or any(_ANTACID_CATEGORY.search(c or "") for c in categories))
    return Carrier(ions, antacid, bool(_BINDER.search(n)))


_GENERAL_IONS = re.compile(r"\b(?:multivalent|polyvalent|divalent|trivalent|cations|minerals?)\b", re.I)
_RULE_ION = {i: re.compile(rf"\b(?:{rx}|{_ION_TR[i]})\b", re.I) for i, rx in _ION_NAME.items()}
_RULE_BINDER = re.compile(r"\b(?:sequestrants?|binders?|cholestyramine|colestipol|colesevelam|sevelamer)\b", re.I)


def _rank(t: str, carrier: Carrier) -> int:
    """How directly a rule applies to the other drug; 9 = it does not."""
    named = {i for i, rx in _RULE_ION.items() if rx.search(t)}
    if carrier.ions & named:
        return 0                                  # the rule names the ion the drug carries
    if carrier.ions and _GENERAL_IONS.search(t):
        return 1                                  # 'multivalent ions', 'mineral supplements'
    if carrier.antacid and re.search(r"\bantacids?\b", t, re.I) and not named:
        return 2                                  # antacids in general (not 'antacids containing Al/Mg')
    if carrier.binder and _RULE_BINDER.search(t):
        return 3
    return 9


def pair_cells(drug_id: str, cells: Sequence[Cell], others: Sequence[Tuple[str, str, Carrier]]) -> List[Cell]:
    """For the selected_drugs row: this drug's separation rule shown against another selected
    drug that carries what the rule is about. others: (drug_id, name, mineral_kind(...)).
    A milk-only rule, or a rule about another ion ('antacids containing aluminum' for an iron
    salt), is never used. The cell names the other drug and the rule it is derived from."""
    out: List[Cell] = []
    for other_id, other_name, carrier in others:
        if other_id == drug_id or not carrier:
            continue
        usable = [c for c in cells if c.row in ("minerals_antacids", "dairy_calcium") and c.kind in ("avoid", "separate")]
        ranked = sorted(((_rank(c.source_text, carrier), i, c) for i, c in enumerate(usable)), key=lambda x: x[:2])
        ranked = [r for r in ranked if r[0] < 9]
        if not ranked:
            continue
        c = ranked[0][2]
        text = (f"{other_name}: ayrı alın ({carrier.label()} içerir; ağızdan birlikte alındığında). "
                f"Dayanak: «{c.text}»")
        out.append(Cell("selected_drugs", "separate", text, c.timing, c.source_text,
                        c.source, c.source_ref, c.source_url, c.product, with_drug_id=other_id))
    return out


def timing_text(t: Optional[Timing], subject: str = "") -> str:
    """Turkish wording of a time: '≥2 sa önce veya ≥2 sa sonra', '0,5–1 sa önce'."""
    if t is None:
        return ""

    def fmt(sp: Span) -> str:
        top = sp.high if sp.high is not None else sp.low
        minutes = top < 1

        def n(x: float) -> str:
            x = x * 60 if minutes else x
            s = f"{x:.2f}".rstrip("0").rstrip(".")
            return s.replace(".", ",")
        v = f"{n(sp.low)}–{n(sp.high)}" if sp.high is not None else n(sp.low)
        mark = "≤" if sp.at_most else ("≥" if sp.at_least and sp.high is None else "")
        return mark + v + (" dk" if minutes else " sa")
    parts = []
    if t.before:
        parts.append(f"{fmt(t.before)} önce")
    if t.after:
        parts.append(f"{fmt(t.after)} sonra")
    return " veya ".join(parts)
