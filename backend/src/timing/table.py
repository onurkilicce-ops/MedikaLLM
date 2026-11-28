"""``POST /api/timing/table``: one table of timing instructions for the selected drugs.

Rows are foods and situations (meal, dairy/calcium, antacids/minerals, the other
selected drugs, grapefruit, alcohol ...), columns are the selected drugs. Cells come
from two sources, always shown with their source sentence:

* DrugBank's food-interaction entries of each drug (``food.classify``), read-only;
* the small, manually checked label catalog (``advice.SOURCES``), shown WITH its
  product (e.g. a UK label) instead of being hidden until a product is chosen.

A missing cell means the record has no statement; it is never "safe".
"""
from __future__ import annotations

from typing import Dict, List, Literal, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from ..db.sql_models import Drug, DrugCategory, DrugFoodInteraction
from . import food
from .advice import SOURCES, canonical_name
from .models import DRUGBANK_ID_RE, _Out
from .repository import _run

SCHEMA_VERSION = "m02-timing-table/1"


class TableRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    drug_ids: List[str] = Field(min_length=1, max_length=10)

    @field_validator("drug_ids")
    @classmethod
    def _ids(cls, v):
        if any(not isinstance(x, str) or not DRUGBANK_ID_RE.fullmatch(x) for x in v):
            raise ValueError("every id must be 'DB' followed by 5 ASCII digits")
        if len(set(v)) != len(v):
            raise ValueError("drug ids must be distinct")
        return v


class SpanOut(_Out):
    low_hours: float
    high_hours: Optional[float]
    at_least: bool
    at_most: bool


class CellOut(_Out):
    kind: Literal["avoid", "separate", "limit", "take_with", "take_without", "info"]
    text: str                       # Turkish instruction
    timing_text: str                # '≥2 sa önce veya ≥2 sa sonra' ('' = no time stated)
    before: Optional[SpanOut]       # take THIS drug this long before the item
    after: Optional[SpanOut]        # or this long after it
    source: Literal["drugbank", "label"]
    source_text: str                # the whole DrugBank entry or the label excerpt
    timing_quote: str               # the sentence the time was read from ('' = none)
    source_ref: str
    source_url: str
    product: str                    # label cells: the product the statement belongs to
    with_drug_id: str               # selected_drugs row: the other selected drug


class TableDrug(_Out):
    requested_id: str
    drug_id: Optional[str]
    name: Optional[str]
    found: bool
    has_food_entries: bool          # DrugBank food-interaction entries only (label cells not counted)


class TableRow(_Out):
    row_id: str
    label: str
    cells: Dict[str, List[CellOut]]  # requested_id -> cells (missing key = no statement)


class TableResponse(_Out):
    schema_version: str = SCHEMA_VERSION
    drugs: List[TableDrug]
    rows: List[TableRow]
    notice: str = ("Kaynak: DrugBank besin etkileşimi kayıtları ve elle doğrulanmış küçük bir ürün etiketi kataloğu. "
                   "Boş hücre 'kayıtta bilgi yok' demektir, 'güvenli' değildir. Süreler kişisel doz takvimi değildir; "
                   "uzman değerlendirmesi gerekir.")


# ----------------------------------------------------------- label catalog --
# The checked label statements as table cells, shown with their product.
_LABEL_CELLS = {
    # (canonical drug names, row, kind, text, source key, product, before (low, high, at_least), after)
    "cipro_food": (("ciprofloxacin", "ciprofloxacin hydrochloride"), "dairy_calcium", "separate",
                   "Süt ürünleri ve kalsiyumlu içecekten ayrı (öğün dışında)", "Ciproxin 250 mg/5 mL süspansiyon — Bayer (UK)",
                   (1.0, 2.0, False), (4.0, None, True)),
    "levothyroxine_food": (("levothyroxine", "levothyroxine sodium"), "meal", "take_without",
                           "Aç karnına, kahvaltıdan önce", "Levotiroksin 100 mcg tablet — Proficient Rx/Lannett (US)",
                           (0.5, 1.0, False), None),
}
# drug-drug label rule: (perpetrator names, other names, source key, product, before, after)
_LABEL_PAIRS = [
    (("ciprofloxacin", "ciprofloxacin hydrochloride"), ("sucralfate",), "cipro_dd",
     "Ciprofloxacin 500 mg tablet — Ranbaxy/Sun (UK) ve oral sukralfat", (1.0, 2.0, False), (4.0, None, True)),
]


def _label_timing(before, after, quote: str) -> food.Timing:
    sp = lambda t: food.Span(t[0], t[1], t[2]) if t else None  # noqa: E731
    return food.Timing(sp(before), sp(after), quote)


def _cell_out(c: food.Cell) -> CellOut:
    t = c.timing

    def sp(x):
        return SpanOut(low_hours=x.low, high_hours=x.high, at_least=x.at_least, at_most=x.at_most) if x else None
    return CellOut(kind=c.kind, text=c.text, timing_text=food.timing_text(t), before=sp(t.before) if t else None,
                   after=sp(t.after) if t else None, source=c.source, source_text=c.source_text,
                   timing_quote=t.quote if t else "", source_ref=c.source_ref, source_url=c.source_url,
                   product=c.product, with_drug_id=c.with_drug_id)


def read_table_data(drug_ids: Sequence[str]):
    """(rows by drug_id: (drug_id, name), food entries by drug_id, categories by drug_id). Read-only."""
    def q(session):
        rows = session.execute(select(Drug.id, Drug.drug_id, Drug.name).where(Drug.drug_id.in_(list(drug_ids)))).all()
        by_id = {r.drug_id: (r.id, r.name) for r in rows}
        pks = [v[0] for v in by_id.values()]
        foods: Dict[int, List[str]] = {}
        cats: Dict[int, List[str]] = {}
        if pks:
            for r in session.execute(select(DrugFoodInteraction.drug_pk, DrugFoodInteraction.interaction)
                                     .where(DrugFoodInteraction.drug_pk.in_(pks))
                                     .order_by(DrugFoodInteraction.drug_pk, DrugFoodInteraction.id)):
                foods.setdefault(r[0], []).append(r[1] or "")
            for r in session.execute(select(DrugCategory.drug_pk, DrugCategory.category)
                                     .where(DrugCategory.drug_pk.in_(pks))):
                cats.setdefault(r[0], []).append(r[1] or "")
        return by_id, foods, cats
    return _run(q)


def build(drug_ids: Sequence[str]) -> TableResponse:
    by_id, foods, cats = read_table_data(drug_ids)
    cells: Dict[str, List[food.Cell]] = {}
    drugs: List[TableDrug] = []
    for d in drug_ids:
        if d not in by_id:
            drugs.append(TableDrug(requested_id=d, drug_id=None, name=None, found=False, has_food_entries=False))
            continue
        pk, name = by_id[d]
        entries = [e for e in foods.get(pk, []) if e.strip()]
        cells[d] = [food.classify(e) for e in entries]
        drugs.append(TableDrug(requested_id=d, drug_id=d, name=name, found=True, has_food_entries=bool(entries)))
        # checked label statements for this ingredient, shown with their product
        canon = canonical_name(name)
        for key, (names, row, kind, text, product, before, after) in _LABEL_CELLS.items():
            if canon in names:
                src = SOURCES[key]
                cells[d].append(food.Cell(row, kind, text, _label_timing(before, after, src.excerpt), src.excerpt,
                                          "label", src.source_ref, src.url, product))

    # the other selected drugs: minerals/antacids/calcium carriers, and the label pair rule
    others = []
    for d in drug_ids:
        if d in by_id:
            pk, name = by_id[d]
            others.append((d, name, food.mineral_kind(canonical_name(name), cats.get(pk, []))))
    names_by_id = {d: canonical_name(by_id[d][1]) for d in by_id}
    for d in list(cells):
        pair = food.pair_cells(d, [c for c in cells[d] if c.source == "drugbank"], others)
        for perp, other_names, key, product, before, after in _LABEL_PAIRS:
            if names_by_id[d] in perp:
                for o in drug_ids:
                    if o != d and o in names_by_id and names_by_id[o] in other_names:
                        src = SOURCES[key]
                        pair.append(food.Cell("selected_drugs", "separate", f"{by_id[o][1]}: ayrı alın",
                                              _label_timing(before, after, src.excerpt), src.excerpt, "label",
                                              src.source_ref, src.url, product, with_drug_id=o))
        cells[d].extend(pair)

    rows: List[TableRow] = []
    for row_id, label in food.ROWS:
        row_cells: Dict[str, List[CellOut]] = {}
        for d, cs in cells.items():
            out = []
            for c in cs:
                if c.row != row_id:
                    continue
                out.append(_cell_out(c))
            if out:
                row_cells[d] = out
        if row_cells:
            rows.append(TableRow(row_id=row_id, label=label, cells=row_cells))
    return TableResponse(drugs=drugs, rows=rows)
