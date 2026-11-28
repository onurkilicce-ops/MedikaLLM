"""M-03 rules: pure functions, no database, no LLM.

1. Roles: DrugBank's free ``actions`` list of a protein entry is mapped to
   substrate / inhibitor / inducer; anything else is ``other`` (the raw text
   is always returned next to it).
2. Organs: a sentence of the elimination / metabolism / clearance text is an
   organ-route statement only when the organ word stands in a ROUTE segment
   ('excreted in urine', 'renal clearance', 'Mainly hepatic'). Lab values,
   adverse events or monitoring advice ('liver enzymes increased', 'urinary
   retention') are not routes. Each statement keeps its exact quote. No share
   or percentage is attached to an organ: free text such as 'respectively',
   '% change' or 'protein bound' cannot be attributed reliably, so the reader
   reads the numbers in the quote. Negated or minor wording, uncertainty,
   patient conditions, metabolites and possible other subjects are flagged.
3. Pairs: two drugs are explained through a protein only when BOTH record the
   same identifiable human protein, one as inhibitor/inducer and the other as
   substrate. Two substrates of one protein give a weak 'competition' note.
"""
from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass, field
from itertools import combinations
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

_HUMAN = {"humans", "human", "homo sapiens"}

# 'inactivator' (mechanism-based inactivation) slows the enzyme like an
# inhibitor; the raw DrugBank word is always shown next to the role.
_ROLE_WORDS = {"substrate": "substrate", "inhibitor": "inhibitor", "inactivator": "inhibitor", "inducer": "inducer"}


@dataclass(frozen=True)
class ProteinRow:
    kind: str              # enzyme | transporter | carrier
    protein_id: str
    name: str
    organism: str
    known_action: str
    actions: str
    inhibition_strength: str = ""
    induction_strength: str = ""


def is_human(organism: str) -> bool:
    return (organism or "").strip().lower() in _HUMAN


def roles_of(actions: str) -> List[str]:
    """'substrate, inhibitor' -> ['substrate', 'inhibitor']; unknown words -> 'other'."""
    out: List[str] = []
    for part in re.split(r"[,;/]", actions or ""):
        word = " ".join(part.strip().lower().split())
        if not word:
            continue
        role = _ROLE_WORDS.get(word, "other")
        if role not in out:
            out.append(role)
    return out


def _pid(p: ProteinRow) -> str:
    return (p.protein_id or "").strip().upper()


def _pname(p: ProteinRow) -> str:
    return " ".join((p.name or "").lower().split())


def identifiable(p: ProteinRow) -> bool:
    return bool(_pid(p) or _pname(p))


# ---------------------------------------------------------------- organs --
_ORGAN_WORDS = {
    "kidney": r"urine|urinary|renal(?:ly)?|kidneys?|glomerular|tubular",
    "liver": r"hepatic(?:ally)?|liver|hepatobiliary",
    "bile_feces": r"bile|biliary|hepatobiliary|f(?:a)?eces|f(?:a)?ecal(?:ly)?|stools?",
    "lungs": r"exhaled|exhalation|expired air|lungs?|pulmonary",
}
# 'non-renal', 'extra-hepatic', 'nonrenal': the opposite of that organ, never a route of it
_ORGAN_RE = {k: re.compile(rf"(?<![\w-])(?<!non )(?<!extra )(?:{v})\b", re.I) for k, v in _ORGAN_WORDS.items()}
_PREFIXED = re.compile(r"\b(?:non|extra|post|pre)-?\s?$", re.I)
_ROUTE_WORD = re.compile(
    r"\b(?:excret\w*|eliminat\w*|clear(?:ed|s|ance)?|recover\w*|metaboli[sz]\w*|biotransform\w*|secret\w*"
    r"|filtrat\w*|filtered|routes?|pathways?|exhaled|exhalation|expired air|extraction|first[\s-]pass"
    r"|passed|removed|appears?|found|detected|accounts?)\b", re.I)
_VERBISH = re.compile(r"\b(?:is|are|was|were|be|been|being|has|have|had|should|may|might|can|could|must|will"
                      r"|increase\w*|decrease\w*|reduce\w*|monitor\w*|caus\w*|occur\w*|report\w*|observ\w*"
                      r"|elevat\w*|rais\w*|requir\w*|need\w*|adjust\w*)\b", re.I)
# an organ word that names a lab value, an adverse event or a structure, not a route
_NOT_A_ROUTE_AFTER = re.compile(
    r"^[\s-]*(?:enzymes?|function(?:\s+tests?)?|tests?|transaminases?|retention|colic|necrosis|stones?|calculi"
    r"|pain|tumou?rs?|cancer|carcinoma|lesions?|infections?|abnormalit\w*|events?|adverse\w*|tract infection"
    r"|blood flow|perfusion|size|volume|weight|tissues?|filtration rate|salts?|acids?|sequestrant\w*)\b", re.I)
_NOT_A_ROUTE_SEGMENT = re.compile(r"\b(?:accumulat\w*|distribut\w*|concentrations?|penetrat\w*|uptake|stored"
                                  r"|dose should|dosage should)\b", re.I)
# another substance or a kidney-function measure: never this drug's route, even with a route word
_OTHER_SUBSTANCE = re.compile(r"\b(?:creatinine|gfr|crcl|egfr|creatinine clearance|inulin|bilirubin)\b", re.I)
# negation words, except where 'not'/'no' does not deny the route itself
_NEGATION = re.compile(r"\b(?:not|no|negligible|negligibly|minimal|minimally|insignificant|little|none|neither"
                       r"|nor|minor|trace|traces|barely|hardly|small (?:fraction|amount|proportion|percentage)"
                       r"|absent|absence|devoid|lacks?|lacking|nonexistent|non-existent|never|undetectable|unmeasurable"
                       r"|not detectable|below the (?:lower )?limits? of (?:detection|quantification|quantitation)"
                       r"|unlikely|unimportant|zero|nil|escapes?|escaping|bypass\w*|resistant to|free of"
                       r"|avoids?|spares?)\b", re.I)
_CHANGE = (r"(?:differ\w*|chang\w*|affect\w*|alter\w*|reduc\w*|increas\w*|decreas\w*|influenc\w*"
           r"|dose[\s-]dependent|saturat\w*|saturab\w*|var(?:y|ies|ied)|modif\w*|impair\w*|prolong\w*"
           r"|significantly (?:different|changed|altered|affected|reduced|increased|decreased))")
_NOT_A_NEGATION = re.compile(
    rf"\b(?:not|no)\s+(?:only|less than|fewer than|below|under|(?:\w+\s+){{0,2}}?{_CHANGE})\b"
    r"|\bno\s+(?:dose adjustment|adjustment|effect|data|information)\b"
    r"|\bminor\s+(?:\w+\s+)?(?:metabolites?|glucuronides?|conjugates?|sulfates?|sulphates?|pathways?)\b"
    r"|\blittle\s+is\s+known\b", re.I)
_UNCERTAIN = re.compile(r"\b(?:not\s+(?:been\s+)?(?:fully\s+|well\s+|yet\s+|clearly\s+)?(?:known|established|studied|"
                        r"determined|investigated|characteri[sz]ed|evaluated|understood|elucidated|defined|assessed)"
                        r"(?!\s+to\b)"
                        r"|unknown|unclear|not clear|uncertain|little\s+is\s+known|no\s+(?:data|information)\b)", re.I)
_MINOR_SHARE = re.compile(r"(?<![\d.,])0(?:[.,]0+)?\s?%|(?<!not )(?<!no )(?:\bless than|\bunder|\bbelow|<|≤|\bno more than|\bnot more than|\bat most)"
                          r"\s*(?:[0-4](?:[.,]\d+)?|5(?:[.,]0+)?)\s?(?:%|percent\b)", re.I)
_MINOR_WORD = re.compile(r"(?:minor|trace|traces|negligible|minimal|small)", re.I)
_CONDITION = (r"(?:impairment|impaired|insufficiency|failure|disease|dysfunction|damage|toxicity|injury|transplant\w*"
              r"|cirrhosis|cirrhotic|hepatitis|nephropathy|dialysis|haemodialysis|hemodialysis|anuri\w*)")
_CONDITION_AFTER = re.compile(rf"^[\s-]*(?:\w+\s+){{0,2}}?{_CONDITION}\b", re.I)
_CONDITION_BEFORE = re.compile(r"\b(?:patients?|subjects?|people|individuals?)\s+with\s+(?!normal\b)(?:\w+\s+){0,2}$",
                               re.I)
_ANY_CONDITION = re.compile(rf"\b{_CONDITION}\b|\bpatients?\s+with\s+(?!normal\b)", re.I)
_METABOLITE = re.compile(r"\b(?:metabolites?|glucuronides?|glucuronidated|conjugates?|conjugated|sulfates?"
                         r"|sulphates?)\b", re.I)
_METABOLITE_NOUN = r"(?:metabolites?|glucuronides?|conjugates?|sulfates?|sulphates?)"
# 'in urine as metabolites', 'renal excretion of its glucuronide': what takes this route is a metabolite
_METABOLITE_AFTER = re.compile(rf"^\W*(?:\w+\s+){{0,2}}?(?:as|of)\s+(?:(?:its|the|their|an?|inactive|active|several|major|minor"
                               rf"|\w+)\s+){{0,2}}{_METABOLITE_NOUN}\b", re.I)
_PARENT = re.compile(r"\b(?:unchanged|parent|intact|unmetabolized|as such)\b", re.I)
# a finite verb that starts a new statement after a hedge ('may be delayed by food, and 80% ... IS excreted')
_FINITE = re.compile(r"\b(?:is|are|was|were|has|have|had|does|do|did|will|can|shall|undergoes|undergo)\b", re.I)
# The sentence may be about another product ('Unlike drug X, which is renally excreted').
_OTHER_SUBJECT = re.compile(
    r"\b(?:unlike\b|in contrast to|as with|like other|other (?:drugs?|agents?|compounds?)"
    r"|(?:co-?administ\w*|combined) with|(?:given|taken) (?:together )?with (?!food|meals?|a meal|water|milk|or without))"
    r"|\b(?:drug|compound|agent)\s+(?:[a-z]|[a-z]?\d{1,4}[a-z]?)\b(?!\s*(?:h|hr|hrs|hours?|min|minutes?|days?|weeks?"
    r"|mg|g|mcg|ml|%|percent))|\bdrug[a-z]\b", re.I)
_ANIMAL = re.compile(r"\b(?:in|of|from)\s+(?:the\s+)?(?:rats?|mice|dogs?|monkeys?|rabbits?|animals?|animal studies"
                     r"|preclinical studies|non-?human primates)\b", re.I)
# hedged wording: the record does not state the route as fact ('may be excreted', 'unverified')
_HEDGE = re.compile(r"\b(?:may|might|could|possibly|possible|probably|probable|presumably|presumed|(?<!un)likely"
                    r"|thought to|believed to|suggest\w*|appears? to be|seems? to|expected to|assumed"
                    r"|not (?:been )?(?:confirmed|verified|proven)|unconfirmed|unverified|unproven|putative"
                    r"|hypothe\w*|speculat\w*|reportedly|tentative\w*)\b", re.I)
# names that are DrugBank entries but in elimination text are body substances, not another drug
GENERIC_SUBSTANCES = {
    "water", "urea", "oxygen", "glucose", "sodium", "potassium", "calcium", "magnesium", "albumin", "creatinine",
    "bile", "iron", "alcohol", "ethanol", "nitrogen", "carbon dioxide", "hydrogen", "chloride", "bicarbonate",
    "phosphate", "phosphorus", "zinc", "copper", "protein", "fat", "air", "lactose", "sucrose", "fructose",
    "uric acid", "bilirubin", "cholesterol", "carbon", "salt", "acid", "base", "sulfate", "sulphate", "glycine",
    "taurine", "glutathione", "cysteine", "acetate", "lactate", "citrate", "oxalate", "ammonia", "caffeine",
}
_NAME_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9'-]*")
MAX_NAME_CANDIDATES = 4000


def name_candidates(text: str) -> List[str]:
    """Lower-cased 1-4 word sequences that could be a drug name (looked up
    against DrugBank names and synonyms by the repository)."""
    words = [w.lower() for w in _NAME_TOKEN.findall(text or "")]
    out: List[str] = []
    seen: Set[str] = set()
    for i in range(len(words)):
        for n in range(1, 5):
            if i + n > len(words):
                break
            cand = " ".join(words[i:i + n])
            if len(cand) < 4 or cand in seen or cand in GENERIC_SUBSTANCES:
                continue
            seen.add(cand)
            out.append(cand)
            if len(out) >= MAX_NAME_CANDIDATES:
                return out
    return out


def _named_drugs(sentence: str, names: Sequence[str]) -> List[str]:
    """Other drugs' names (lower-case) that occur as whole words in the sentence,
    as written in the sentence; a name inside a longer matched name is dropped."""
    found: List[Tuple[int, int, str]] = []
    low = sentence.lower()
    for name in names:
        for m in re.finditer(rf"(?<![\w-]){re.escape(name)}(?![\w-])", low):
            found.append((m.start(), m.end(), sentence[m.start():m.end()]))
    found.sort(key=lambda t: (t[0], -(t[1] - t[0])))
    out, last_end = [], -1
    for a, b, text in found:
        if a >= last_end:
            if text not in out:
                out.append(text)
            last_end = b
    return out


# segment breaks; parentheses and subordinate clauses are their own segments
_SEGMENT_BREAK = re.compile(r",|\(|\)|\band\b|\bwhile\b|\bwhereas\b|\bbut\b|\bwith\b|\bwithout\b|\bsince\b"
                            r"|\brather than\b|\binstead of\b|\bas opposed to\b|\bin place of\b"
                            r"|\bbecause\b|\balthough\b|\bthough\b|\bwhich\b|\bas it\b|\bwhether\b", re.I)
# periods that do not end a sentence; time units such as '60 min.' DO end one
_ABBREV = re.compile(r"\b(?:approx|i\.v|i\.m|s\.c|p\.o|e\.g|i\.e|ca|vs|dr|et al|cf)\.", re.I)
_CONTRAST_BEFORE = re.compile(r"\b(?:without|rather than|instead of|as opposed to|in place of)\s*$", re.I)
_COPULA_ORGAN = re.compile(r"^\s*(?:is|are|was|were)\s+(?:\w+\s+){0,2}$", re.I)

MAX_MENTIONS_PER_FIELD = 50
MAX_QUOTE_CHARS = 1000
MAX_ANALYSED_CHARS = 5000


def _mask_abbreviations(text: str) -> str:
    """Same length as ``text``; the periods of common abbreviations are masked."""
    chars = list(text)
    for m in _ABBREV.finditer(text):
        for i in range(m.start(), m.end()):
            if chars[i] == ".":
                chars[i] = "\x01"
    return "".join(chars)


def _sentences(text: str) -> Iterable[Tuple[int, int]]:
    """(start, end) of each sentence. ';' always ends one; '.' ends one unless it
    sits BETWEEN digits ('2.5 h') or belongs to a common abbreviation. 'CYP3A4.'
    ends a sentence."""
    scan = _mask_abbreviations(text)
    pos = 0
    for m in re.finditer(r";|\.(?!\d)|(?<!\d)\.|\n+", scan):
        if m.group(0) == "." and m.start() > 0 and scan[m.start() - 1].isdigit() and \
                m.end() < len(scan) and scan[m.end()].isdigit():
            continue
        s, e = pos, m.end() if m.group(0) in ".;" else m.start()
        while s < e and text[s].isspace():
            s += 1
        if e > s:
            yield s, e
        pos = m.end()
    s = pos
    while s < len(text) and text[s].isspace():
        s += 1
    end = len(text.rstrip())
    if s < end:
        yield s, end


def _segments(sentence: str) -> List[Tuple[int, int]]:
    """(start, end) of each non-empty segment."""
    out: List[Tuple[int, int]] = []
    pos = 0
    for m in list(_SEGMENT_BREAK.finditer(sentence)) + [None]:
        end = m.start() if m else len(sentence)
        if sentence[pos:end].strip():
            out.append((pos, end))
        if m:
            pos = m.end()
    return out or [(0, len(sentence))]


def _segment_of(starts: List[int], pos: int) -> int:
    """Index of the last segment that starts at or before ``pos`` (binary search)."""
    return max(0, bisect_right(starts, pos) - 1)


def _label(seg: str) -> bool:
    """Short verbless label ('Mainly hepatic', 'Renal', 'Urine: 65% unchanged')."""
    if re.match(rf"^\W*(?:{'|'.join(_ORGAN_WORDS.values())})\s*:", seg, re.I):
        return True
    words = re.findall(r"[A-Za-z][\w-]*", re.sub(r"\[[^\]]*\]", " ", seg))
    return 0 < len(words) <= 5 and not _VERBISH.search(" ".join(words))


@dataclass(frozen=True)
class Mention:
    organ: str
    source_field: str
    quote: str
    start: int
    end: int
    notes: Tuple[str, ...]
    quote_truncated: bool = False
    cut_before: bool = False
    cut_after: bool = False
    other_drugs: Tuple[str, ...] = ()


def _is_route(sentence: str, segs, seg_text, i: int, hit_start: int, has_verb: bool) -> bool:
    seg = seg_text[i]
    if _ROUTE_WORD.search(seg):
        return True
    if _label(seg) and (i == 0 or not has_verb):
        return True
    if re.search(r"\b(?:in|into|via|through|by)\s+(?:the\s+)?$", sentence[segs[i][0]:hit_start], re.I):
        return True
    earlier_route = any(_ROUTE_WORD.search(t) for t in seg_text[:i])
    if earlier_route and _label(seg) and len(seg.split()) <= 4:
        # coordinated with an earlier route segment, also past a parenthesis or an adverb:
        # 'recovered in urine (40%) and feces (55%)', 'in urine and, to a lesser extent, feces'
        return True
    if earlier_route and _COPULA_ORGAN.match(sentence[segs[i][0]:hit_start]):
        return True  # 'Clearance, which is predominantly renal, ...'
    before = sentence[max(0, segs[i][0] - 300):segs[i][0]]
    if re.search(r"\bof\s+(?:which|this|that|these|it)\s*$", before, re.I) and _ROUTE_WORD.search(before):
        return True  # 'total body clearance is 5 L/h, 60% of which is renal'
    return False


def _metabolite_route(sentence: str, segs, seg_text, i: int, hit_end: int) -> bool:
    """True when what takes this organ route is a metabolite, not the parent drug."""
    tail = sentence[hit_end:segs[i][1]]
    m = _METABOLITE_AFTER.match(tail)
    if m and not _PARENT.search(tail[:m.end()]):
        return True
    # subject of the clause: the text before its first route word
    clause = re.split(r";|\bbut\b|\bwhereas\b|\bwhile\b", sentence[:hit_end], flags=re.I)[-1]
    rw = _ROUTE_WORD.search(clause)
    subject = clause[:rw.start()] if rw else clause
    return bool(re.search(rf"\b{_METABOLITE_NOUN}\b", subject, re.I)) and not _PARENT.search(subject)


def _qualifier_after(sentence: str, segs, i: int, hit_end: int) -> str:
    """A parenthesis right after the organ word qualifies it: 'renal (minor)', 'urinary (<5%)'."""
    if i + 1 < len(segs) and re.fullmatch(r"\s*\(\s*", sentence[hit_end:segs[i + 1][0]] or "x"):
        return sentence[segs[i + 1][0]:segs[i + 1][1]]
    return ""


def organ_mentions(source_field: str, text: str, other_drug_names: Sequence[str] = ()) -> Tuple[List[Mention], bool]:
    """(mentions in text order, truncated?). See the module docstring.

    ``other_drug_names``: lower-cased DrugBank names/synonyms of OTHER drugs that
    occur in this text (found by the repository). A sentence naming one of them
    may describe that drug, so its organ mentions are flagged ``other_drug_named``."""
    other_drug_names = [n for n in other_drug_names if n and n not in GENERIC_SUBSTANCES]
    out: List[Mention] = []
    text = text or ""
    for s, e in _sentences(text):
        full = text[s:e]
        sentence = full[:MAX_ANALYSED_CHARS]  # bounded work per sentence; the quote is capped below anyway
        segs = _segments(sentence)
        starts = [a for a, _ in segs]
        seg_text = [sentence[a:b] for a, b in segs]
        other_subject = bool(_OTHER_SUBJECT.search(sentence))
        animal = bool(_ANIMAL.search(sentence))
        named = _named_drugs(sentence, other_drug_names)
        has_verb = bool(_VERBISH.search(sentence))
        for organ, rx in _ORGAN_RE.items():
            hits = [h for h in rx.finditer(sentence) if not _PREFIXED.search(sentence[max(0, h.start() - 7):h.start()])]
            if not hits:
                continue
            route: List[Tuple[int, int]] = []   # (segment index, hit end)
            condition = False
            first_hit = None
            for h in hits:
                i = _segment_of(starts, h.start())
                seg_end = segs[i][1]
                cond_after = _CONDITION_AFTER.match(sentence[h.end():seg_end])
                if cond_after and _ROUTE_WORD.search(cond_after.group(0)):
                    # 'Renal excretion is impaired in infants': a route that a condition changes
                    condition = True
                    if all(i != j for j, _ in route):
                        route.append((i, h.end()))
                        first_hit = first_hit if first_hit is not None else h.start()
                    continue
                if cond_after or _CONDITION_BEFORE.search(sentence[max(0, h.start() - 60):h.start()]):
                    condition = True
                    first_hit = first_hit if first_hit is not None else h.start()
                elif _NOT_A_ROUTE_AFTER.match(sentence[h.end():seg_end]) or (
                        _NOT_A_ROUTE_SEGMENT.search(seg_text[i]) and not _ROUTE_WORD.search(seg_text[i])) or \
                        _OTHER_SUBSTANCE.search(seg_text[i]):
                    continue  # 'liver enzymes', 'urinary retention', 'accumulates in the liver'
                elif all(i != j for j, _ in route) and _is_route(sentence, segs, seg_text, i, h.start(), has_verb):
                    route.append((i, h.end()))
                    first_hit = first_hit if first_hit is not None and route[0][0] != i else h.start()
            if not route and not (condition and _ROUTE_WORD.search(sentence)):
                continue  # not a route statement: lab value, adverse event, monitoring advice
            notes: List[str] = []
            if not route:
                notes.append("condition_context")  # 'clearance is reduced in renal impairment'
            else:
                def negated(i, hit_end):
                    seg = seg_text[i]
                    # 'Only a small fraction (<2%) appears in urine': the subject before a
                    # parenthesis belongs to the same clause
                    if i >= 2 and re.fullmatch(r"\s*\(\s*", sentence[segs[i - 2][1]:segs[i - 1][0]]) and \
                            re.fullmatch(r"\s*\)\s*", sentence[segs[i - 1][1]:segs[i][0]]):
                        seg = seg_text[i - 2] + " " + seg_text[i - 1] + " " + seg
                    # 'not excreted in urine, feces, or bile': a short coordinated item takes
                    # the negation of the nearest earlier route segment
                    if _label(seg) and len(seg.split()) <= 4 and not _ROUTE_WORD.search(seg):
                        prev_route = next((seg_text[j] for j in range(i - 1, -1, -1) if _ROUTE_WORD.search(seg_text[j])), "")
                        seg = prev_route + " " + seg
                    if _CONTRAST_BEFORE.search(sentence[max(0, segs[i][0] - 30):segs[i][0]]):
                        return True  # 'eliminated in feces rather than urine', 'without hepatic metabolism'
                    qual = _qualifier_after(sentence, segs, i, hit_end)  # only a share marker counts there
                    return bool(_NEGATION.search(_NOT_A_NEGATION.sub(" ", seg)) or _MINOR_SHARE.search(seg)
                                or _MINOR_SHARE.search(qual) or _MINOR_WORD.fullmatch(qual.strip()))

                def uncertain(i):
                    if _UNCERTAIN.search(seg_text[i]) or _HEDGE.search(seg_text[i]):
                        return True
                    # A hedge earlier in the same clause carries over only while it governs this
                    # route's verb: 'The drug may be metabolized in the liver and excreted in urine'
                    # (shared 'may'), but not 'Absorption may be delayed by food, and 80% of the dose
                    # IS excreted in urine' (a new finite verb starts a definite statement).
                    clause = re.split(r";|\bbut\b|\bwhereas\b|\bwhile\b", sentence[:segs[i][0]], flags=re.I)[-1]
                    hedges = list(_HEDGE.finditer(clause))
                    if hedges and not _FINITE.search(clause[hedges[-1].end():] + " " + seg_text[i]):
                        return True
                    # 'It is not known whether it is excreted in urine'
                    return i > 0 and bool(re.search(r"\bwhether\s*$", sentence[:segs[i][0]], re.I)) and bool(
                        _UNCERTAIN.search(seg_text[i - 1]))
                if all(negated(i, he) and not uncertain(i) for i, he in route):
                    notes.append("negated_or_minor")
                if any(uncertain(i) for i, _ in route):
                    notes.append("uncertain_statement")
                if condition or _ANY_CONDITION.search(sentence):
                    notes.append("condition_also_mentioned")  # a route, and a patient condition in the sentence
            if _METABOLITE.search(sentence):
                # Parent drug forming metabolites ('metabolized in the liver to inactive metabolites')
                # is information; a metabolite taking the route itself ('The metabolite is excreted in
                # urine', 'recovered in urine as metabolites') is not the parent drug's route.
                notes.append("metabolite_mentioned")
                # judged on the organ's positive statements ('Renal clearance is negligible, but
                # 80% is recovered in urine as metabolites': the only positive route is a metabolite's)
                positive = [(i, he) for i, he in route if not negated(i, he)] if route else []
                if route and all(_metabolite_route(sentence, segs, seg_text, i, he) for i, he in (positive or route)):
                    notes.append("metabolite_route")
            if other_subject:
                notes.append("other_subject_possible")
            if named:
                notes.append("other_drug_named")
            if animal:
                notes.append("animal_study")
            # a long sentence is quoted as a window that contains the organ word
            q0 = 0 if len(full) <= MAX_QUOTE_CHARS else max(0, min((first_hit or 0) - 300, len(full) - MAX_QUOTE_CHARS))
            quote = full[q0:q0 + MAX_QUOTE_CHARS]
            out.append(Mention(organ, source_field, quote, s + q0, s + q0 + len(quote), tuple(notes),
                               len(full) > MAX_QUOTE_CHARS, q0 > 0, q0 + len(quote) < len(full), tuple(named)))
            if len(out) >= MAX_MENTIONS_PER_FIELD:
                return out, True
    return out, False


# ----------------------------------------------------------------- pairs --
_KNOWN_RANK = {"yes": 0, "unknown": 1, "": 1, "no": 2}


@dataclass
class _Group:
    """One protein of one drug: DrugBank entries with the same BE id (or, without
    an id, the same name) merged. For each role the evidence of ONE entry is
    kept: known_action 'yes' preferred, then an entry that states a strength."""
    ids: Set[str] = field(default_factory=set)
    names: Set[str] = field(default_factory=set)
    rows: List[ProteinRow] = field(default_factory=list)
    self_ambiguous: bool = False
    roles: Dict[str, ProteinRow] = field(default_factory=dict)

    def add(self, row: ProteinRow):
        self.rows.append(row)
        if _pid(row):
            self.ids.add(_pid(row))
        if _pname(row):
            self.names.add(_pname(row))
        for role in roles_of(row.actions):
            prev = self.roles.get(role)
            if prev is None or (_KNOWN_RANK.get(row.known_action.strip().lower(), 1),
                                not _stated(_role_strength(row, role))) < (
                    _KNOWN_RANK.get(prev.known_action.strip().lower(), 1), not _stated(_role_strength(prev, role))):
                self.roles[role] = row

    @property
    def label(self) -> str:
        return next((r.name for r in self.rows if r.name), next(iter(self.ids), ""))

    @property
    def protein_id(self) -> str:
        return next((r.protein_id for r in self.rows if r.protein_id), "")

    @property
    def raw_actions(self) -> str:
        out: List[str] = []
        for r in self.rows:
            if r.actions and r.actions not in out:
                out.append(r.actions)
        return ", ".join(out)

    def matches(self, other: "_Group") -> bool:
        if self.ids and other.ids:
            return bool(self.ids & other.ids)
        return bool(self.names & other.names)


def _stated(strength: str) -> bool:
    return bool(strength) and strength.strip().lower() != "unknown"


def _role_strength(row: ProteinRow, role: str) -> str:
    if role == "inhibitor":
        return (row.inhibition_strength or "").strip()
    if role == "inducer":
        return (row.induction_strength or "").strip()
    return ""


def _groups(rows: Sequence[ProteinRow]) -> List[_Group]:
    """Human, identifiable entries grouped. Entries with an id are grouped by
    id; an entry without an id joins a group only when exactly one group has
    its name, otherwise it is a name-only group."""
    usable = [r for r in rows if is_human(r.organism) and identifiable(r)]
    by_id: Dict[str, _Group] = {}
    for r in usable:
        if _pid(r):
            by_id.setdefault(_pid(r), _Group()).add(r)
    groups = list(by_id.values())
    name_only: Dict[str, _Group] = {}
    for r in usable:
        if _pid(r):
            continue
        same = [g for g in groups if _pname(r) in g.names]
        if len(same) == 1:
            same[0].add(r)
        else:
            g = name_only.setdefault(_pname(r), _Group())
            g.add(r)
            # the drug itself lists this name under several BE ids: which one is meant is unknown
            g.self_ambiguous = g.self_ambiguous or len(same) > 1
    return groups + list(name_only.values())


@dataclass(frozen=True)
class Explained:
    kind: str
    protein_id: str
    protein_name: str
    mechanism: str
    perpetrator: Optional[str]
    victim: Optional[str]
    effect: str
    evidence: Tuple[Tuple[str, Tuple[str, ...], str, str, str], ...]   # drug, roles, raw, known_action, strength
    caveats: Tuple[str, ...]
    directional: bool


def _effect(kind: str, mechanism: str) -> str:
    if mechanism == "shared_substrate":
        return "competition_possible_not_established"
    if kind == "enzyme":
        return "victim_exposure_may_increase" if mechanism == "inhibition" else "victim_exposure_may_decrease"
    if kind == "carrier":
        return "carrier_binding_may_change"   # plasma/binding protein: no direction of the free level
    return "victim_transport_may_decrease" if mechanism == "inhibition" else "victim_transport_may_increase"


def explain_pair(a: str, b: str, rows_a: Sequence[ProteinRow], rows_b: Sequence[ProteinRow]):
    """Returns (explanations, names of shared human proteins without any explanation)."""
    ga, gb = _groups(rows_a), _groups(rows_b)
    explained: List[Explained] = []
    undirected: List[Tuple[int, str]] = []
    explained_a: Set[int] = set()
    # A group without an id that matches several groups of the other drug by name
    # is ambiguous (which BE id is meant?) and explains nothing.
    def ambiguous(g: _Group, others: List[_Group]) -> bool:
        return not g.ids and (g.self_ambiguous or sum(1 for o in others if g.matches(o)) > 1)
    done: Set[Tuple[str, Optional[str], Optional[str], str]] = set()
    for ia, pa in enumerate(ga):
        if ambiguous(pa, gb):
            if any(pa.matches(o) for o in gb) and pa.label and (ia, pa.label) not in undirected:
                undirected.append((ia, pa.label))  # shared by name, but which protein is meant is unknown
            continue
        for pb in gb:
            if not pa.matches(pb) or ambiguous(pb, ga):
                continue
            found = False
            for perp_id, victim_id, pp, pv in ((a, b, pa, pb), (b, a, pb, pa)):
                if "substrate" not in pv.roles:
                    continue
                victim_row = pv.roles["substrate"]
                conflict = "inhibitor" in pp.roles and "inducer" in pp.roles
                for role, mechanism in (("inhibitor", "inhibition"), ("inducer", "induction")):
                    if role not in pp.roles:
                        continue
                    found = True
                    perp_row = pp.roles[role]
                    kind = victim_row.kind  # how the victim uses the protein (its substrate entry)
                    strength = _role_strength(perp_row, role)
                    caveats: List[str] = []
                    if perp_row.known_action.strip().lower() != "yes" or victim_row.known_action.strip().lower() != "yes":
                        caveats.append("known_action_not_confirmed")
                    if conflict:
                        caveats.append("perpetrator_listed_as_inhibitor_and_inducer")
                    if kind == "enzyme":
                        caveats.append("prodrug_reverses_direction")
                        if strength.lower() in ("", "unknown"):
                            caveats.append("strength_not_stated")
                    elif kind == "transporter":
                        caveats.append("transport_direction_depends_on_protein")
                    else:
                        caveats.append("carrier_binding_direction_not_established")
                    if perp_row.kind != victim_row.kind:
                        caveats.append("listed_under_different_protein_kinds")
                    caveats.append("other_pathways_may_compensate")
                    ident = (pp.protein_id or pv.protein_id or "").upper() or (pp.label or pv.label or "").lower()
                    key = (mechanism, perp_id, victim_id, ident)
                    if key in done:
                        continue  # the same protein matched twice (id group and name-only group)
                    done.add(key)
                    explained.append(Explained(
                        kind, pp.protein_id or pv.protein_id, pp.label or pv.label, mechanism, perp_id, victim_id,
                        _effect(kind, mechanism),
                        ((perp_id, tuple(pp.roles), pp.raw_actions, perp_row.known_action, strength),
                         (victim_id, tuple(pv.roles), pv.raw_actions, victim_row.known_action, "")),
                        tuple(caveats), directional=(kind != "carrier" and not conflict)))
            if not found and "substrate" in pa.roles and "substrate" in pb.roles:
                found = True
                ra, rb = pa.roles["substrate"], pb.roles["substrate"]
                caveats = ["shared_substrate_is_weak_evidence"]
                if ra.known_action.strip().lower() != "yes" or rb.known_action.strip().lower() != "yes":
                    caveats.insert(0, "known_action_not_confirmed")
                if ra.kind != rb.kind:
                    caveats.append("listed_under_different_protein_kinds")
                caveats.append("other_pathways_may_compensate")
                kinds = {ra.kind, rb.kind}
                explained.append(Explained(
                    next(k for k in ("transporter", "enzyme", "carrier") if k in kinds) if len(kinds) > 1 else ra.kind,
                    pa.protein_id or pb.protein_id, pa.label or pb.label, "shared_substrate", None, None,
                    _effect(ra.kind, "shared_substrate"),
                    ((a, tuple(pa.roles), pa.raw_actions, ra.known_action, ""),
                     (b, tuple(pb.roles), pb.raw_actions, rb.known_action, "")),
                    tuple(caveats), directional=False))
            if found:
                explained_a.add(ia)
            elif pa.label and (ia, pa.label) not in undirected:
                undirected.append((ia, pa.label))
    # one entry per protein (group), not per name: two BE ids with the same name both stay,
    # labelled with their id so they can be told apart
    kept = [(ia, label) for ia, label in dict.fromkeys(undirected) if ia not in explained_a]
    counts: Dict[str, int] = {}
    for _, label in kept:
        counts[label] = counts.get(label, 0) + 1
    names = []
    for ia, label in kept:
        shown = f"{label} ({ga[ia].protein_id})" if counts[label] > 1 and ga[ia].protein_id else label
        if shown not in names:
            names.append(shown)
    # strongest evidence first: directional before the rest, enzymes first
    explained.sort(key=lambda x: (not x.directional, x.mechanism == "shared_substrate", x.kind != "enzyme",
                                  (x.protein_name or "").lower(), x.perpetrator or ""))
    return explained, names


def pairs_of(ids: Sequence[str]):
    return list(combinations(ids, 2))
