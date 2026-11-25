"""Rule-based extraction of Tmax / half-life statements from stored text.

Pure functions only: no database, no network, no LLM. The objective rules
are documented in ``RULES.md`` next to this file; this module is their only
implementation. Anything the rules cannot structure safely is returned as a
review item with the exact text, never dropped and never turned into 0.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

PARSER_VERSION = "m02-text-parser/3"

HALF_LIFE = "half_life"
TMAX = "tmax"
FIELD_MEASURE = {"half_life": HALF_LIFE, "absorption": TMAX}

PLACEHOLDERS = {
    "not available", "n/a", "na", "none", "unknown", "not applicable", "no data",
    "not known", "not determined", "not established", "-", "--", "?",
}

# --------------------------------------------------------------------------
# Units and numbers
# --------------------------------------------------------------------------
_UNIT_HOURS: Dict[str, Optional[float]] = {}
for _names, _hours in (
    (("seconds", "second", "secs", "sec"), 1 / 3600),
    (("minutes", "minute", "mins", "min"), 1 / 60),
    (("hours", "hour", "hrs", "hr", "h"), 1.0),
    (("days", "day"), 24.0),
    (("weeks", "week", "wks", "wk"), 168.0),
    (("months", "month", "years", "year", "yrs", "yr"), None),  # not exactly convertible
):
    for _n in _names:
        _UNIT_HOURS[_n] = _hours
_AGE_UNITS = {"months", "month", "years", "year", "yrs", "yr"}

_UNIT = "(?:" + "|".join(sorted(_UNIT_HOURS, key=len, reverse=True)) + ")"
_NUM = r"\d+(?:[.,]\d+)*"
_DASH = "-‐‑‒–—−"  # - ‐ ‑ ‒ – — −
# 'h-1', 'h^-1', 'h⁻¹' are rate units (per hour), not durations.
# 'h*µM', 'ng·h/mL', 'h x ng/mL' are AUC/compound units, not durations.
_UNIT_END = (rf"(?![A-Za-z])(?!\s*(?:\^\s*)?[{_DASH}⁻]\s*[1¹](?!\d))"
             r"(?!\s*[*·×/^])(?!\s+x\s+[A-Za-zµμ])")

DURATION_RE = re.compile(
    rf"""
    (?<![\w./,:])(?<!\w[{_DASH}])         # not glued to a word: t1/2, AUC0-24, AUC0–24, 1:30
    (?P<between>\bbetween\s+)?            # 'and' is a range separator only after 'between'
    (?P<sign>[-−‐](?=\d))?
    (?P<n1>{_NUM})
    (?:\s*(?P<u1>{_UNIT}){_UNIT_END})?
    (?:
        \s*(?P<sep>[{_DASH}]|\bto\b|(?(between)\band\b|(?!)))\s*(?P<n2>{_NUM})
      |
        \s*(?P<pm>±|\+/-|\+-)\s*(?P<pmv>{_NUM})
    )?
    (?P<adj>\s*[-‐‑]\s*|\s*)
    (?P<u2>{_UNIT}){_UNIT_END}
    """,
    re.X | re.I,
)

# --------------------------------------------------------------------------
# Keywords
# --------------------------------------------------------------------------
_I = re.I
HALF_LIFE_KW = [re.compile(p, _I) for p in (
    r"half[\s-]?li(?:fe|ves)", r"\bt\s?1/2\b", r"t½", r"\bt\(1/2\)",
)]
TMAX_STRONG_KW = [re.compile(p, _I) for p in (
    r"\bt\s?max\b", r"\bt\(max\)", r"\btmax\b",
    r"\btime to (?:reach )?(?:the )?(?:peak|maximum|maximal|max)\b",
    r"\btime of (?:the )?(?:peak|maximum|maximal)\b",
)]
_PEAK_CONC = re.compile(
    r"\b(?:peak|maximum|maximal|max\.?)\s+(?:(?:mean|plasma|serum|blood|drug|systemic)\s+){0,3}"
    r"(?:concentrations?|levels?)\b", _I)
_CONC_PEAK = re.compile(r"\b(?:concentrations?|levels?)\s+(?:\w+\s+){0,2}peak(?:ed|s)?\b", _I)
_CMAX_REACHED = re.compile(r"\bc\s?max\b[^.;]{0,60}?\b(?:reach|achiev|attain|occur|observ)", _I)
TMAX_KW = TMAX_STRONG_KW + [_PEAK_CONC, _CONC_PEAK, _CMAX_REACHED]
_TEMPORAL_VERB = re.compile(r"\b(?:reach|achiev|attain|occur|observ|seen|appear)", _I)

_STEADY_STATE_EVENT = (
    r"\bsteady[\s-]state\s+(?:(?:plasma\s+)?(?:concentrations?|levels?)\s+)?"
    r"(?:is|are|was|were)?\s*(?:reached|achieved|attained)"
    r"|\breach(?:es|ed)?\s+steady[\s-]state|\btime to steady[\s-]state"
)
_COMMON_COMPETING = [re.compile(p, _I) for p in (
    r"\bonset\b", r"\bduration of (?:action|effect)\b", r"\beffects?\b", r"\bresponses?\b",
    r"\binfusions?\b", r"\bdosing\b", r"\bintervals?\b", r"\bevery\b", r"\bclearance\b",
    r"\bmean residence time\b", r"\bmrt\b", r"\bexcret\w*", r"\brecover(?:ed|y)\b",
    _STEADY_STATE_EVENT, r"\bwash[\s-]?out\b", r"\blag[\s-]time\b", r"\bdetect\w*", r"\bundetectable\b",
    r"\beliminat\w*", r"\bcomplete(?:ly|d)?\b", r"\bremain\w*", r"\belevated\b", r"\bclear(?:ed|s|ing)?\b",
    r"\bpersist\w*", r"\bremov\w*", r"\bsessions?\b",
)]
COMPETING = {
    TMAX: _COMMON_COMPETING + HALF_LIFE_KW + [
        re.compile(r"\babsorb\w*|\babsorption\b", _I),
        # '... peak at 2 hours, decreasing to X at 24 hours': later concentrations
        re.compile(r"\bdecreas\w*|\bdeclin\w*|\bfall\w*|\bfell\b|\bdrop\w*|\btrough\b", _I),
    ],
    HALF_LIFE: _COMMON_COMPETING + TMAX_KW,
}
TARGET = {TMAX: TMAX_KW, HALF_LIFE: HALF_LIFE_KW}

_SEPARATOR = re.compile(
    r";|,|\band\b|\bwhile\b|\bwhereas\b|\bbut\b|\bcompared (?:with|to)\b|\bversus\b|\bvs\.?", _I)
_TOKEN = r"[A-Za-z]{1,3}\d+"
_REF_TOKEN_GROUP = re.compile(rf"\[\s*({_TOKEN}(?:\s*,\s*{_TOKEN})*)\s*\]")
_TOKEN_BLOCK = rf"\[\s*{_TOKEN}(?:\s*,\s*{_TOKEN})*\s*\]"
# A sentence ends at . ! ? followed by whitespace + capital letter, or at
# . ! ? + inline reference token(s) followed by a capital letter (DrugBank
# often writes 'hours.[A1]The next ...' without a space).
# Any short bracket block after the period ('[Label]', '[FDA Label]') also
# belongs to the sentence before it for splitting purposes.
_SENT_END = re.compile(r"[.!?](?:(?:\s*\[[^\[\]]{1,40}\])+(?=\s*[A-Z])|(?=\s+[A-Z]))")
_TRAILING_TOKENS = re.compile(rf"[.!?]?\s*((?:{_TOKEN_BLOCK}\s*)+)$")
# Only abbreviations that do not end a sentence in practice; route
# abbreviations ('... 10 mg i.v. Following ...') can end one.
_ABBREVIATIONS = {"approx", "ca", "e.g", "i.e", "vs", "al", "fig", "eg", "ie", "cf", "viz"}

# Qualifiers immediately before a duration.
_APPROX_TAIL = re.compile(
    r"(?:~|≈|∼|\b(?:approximately|approx\.?|about|around|roughly|nearly|almost|circa|ca\.))\s*$", _I)
_UPPER_TAIL = [
    (re.compile(r"(?:<=|=<|≤)\s*$"), True),
    (re.compile(r"<\s*$"), False),
    (re.compile(r"\b(?:up to|at most|no more than|not more than)\s*$", _I), True),
    (re.compile(r"\b(?:less than|under|below|shorter than)\s*$", _I), False),
]
_LOWER_TAIL = [
    (re.compile(r"(?:>=|=>|≥)\s*$"), True),
    (re.compile(r">\s*$"), False),
    (re.compile(r"\b(?:at least|no less than|not less than)\s*$", _I), True),
    (re.compile(r"\b(?:more than|greater than|longer than|exceeding|in excess of)\s*$", _I), False),
]
_NEGATED_TAIL = [  # checked first: 'not less than' is a LOWER bound
    (re.compile(r"\b(?:no|not)\s+(?:less|shorter|fewer)\s+than\s*$", _I), "lower_bound", True),
    (re.compile(r"\b(?:no|not)\s+(?:more|longer|greater)\s+than\s*$", _I), "upper_bound", True),
    (re.compile(r"(?:\bnot|n['’]t)\s+(?:exceed(?:ing)?|above|over)\s*$", _I), "upper_bound", True),
    (re.compile(r"(?:\bnot|n['’]t)\s+(?:below|under)\s*$", _I), "lower_bound", True),
]
_WITHIN_TAIL = re.compile(r"\bwithin\s*$", _I)
# A change verb right before the value: 'delayed Tmax approximately 1.5 hours',
# 'was prolonged 3 hours', 'increased to 30 hours'.
_CHANGE_VERB_TAIL = re.compile(
    r"\b(?:delay|prolong|increas|decreas|reduc|shorten|lengthen|extend|doubl|tripl|rais|lower|rose|rise|fell)"
    r"\w*\s+(?:(?![\d(])\S+\s+){0,2}$", _I)
_TO_TAIL = re.compile(r"\bto\s*$", _I)
_CONTRAST = re.compile(
    r"\b(?:versus|vs\.?|compared|whereas|while|but|in contrast|younger|young|controls?|healthy|normal|otherwise"
    r"|humans?|other|non-?\w+)\b", _I)
_STOPWORDS = {
    "in", "for", "with", "without", "the", "a", "an", "and", "or", "of", "at", "after", "following", "is", "was",
    "were", "are", "be", "been", "it", "its", "their", "respectively", "on", "average", "mean", "median",
    "approximately", "approx", "about", "around", "roughly", "nearly", "almost", "range", "ranging", "ranges",
    "ranged", "from", "to", "between", "by", "than", "those", "that", "this", "these", "value", "values",
    "reported", "observed", "estimated", "calculated", "determined", "measured", "h", "hr", "hrs", "hour", "hours",
    "min", "mins", "minute", "minutes", "sec", "secs", "second", "seconds", "day", "days", "week", "weeks", "wk",
    "wks", "also", "all", "both", "each", "up", "less", "more", "least", "most", "under", "below", "within", "as",
    "has", "have", "had", "apparent", "geometric", "arithmetic", "half", "life", "half-life", "half-lives",
    "sd", "se", "cv", "n", "ca", "circa", "generally", "typically", "usually", "overall", "patients", "patient",
    "subjects", "subject", "volunteers", "individuals", "people", "group", "groups", "studies", "study", "dose",
    "doses", "administration", "administered", "given", "reached", "achieved", "attained", "occurred", "occurs",
    "occur", "seen", "noted", "found", "shown", "terminal", "elimination", "plasma", "serum", "blood", "mg",
    "kg", "ml", "l", "single", "multiple", "oral", "orally", "x", "times", "where", "when", "which", "then",
    "whereas", "while", "but", "versus", "vs", "compared", "respective", "corresponding",
}
_OVER_TAIL = re.compile(r"\bover\s*$", _I)
_NUMBER_LIST_TAIL = re.compile(
    r"\d\s*(?:,\s*(?:and\s+|or\s+)?|\band\s+|\bor\s+|/\s*|\bversus\s+|\bvs\.?\s+|\bcompared (?:with|to)\s+)$", _I)
_FROM_TAIL = re.compile(r"\bfrom\s*$", _I)
_RANGING_FROM_TAIL = re.compile(r"\brang\w*\s+from\s*$", _I)
_CHANGE_VERB = re.compile(
    r"\b(?:increas|decreas|prolong|shorten|reduc|extend|lengthen|rose|rise|rising|fell|fall|drop|declin|chang"
    r"|delay|accelerat|went|shift)\w*", _I)
_COPULA_TAIL = re.compile(r"(?:\bis|\bwas|\bare|\bwere|\bbe|\bof|:|=)\s*$", _I)

_EXCLUDE_PREFIX = [
    (re.compile(r"\b(?:every|each)\s*$", _I), "dosing_interval"),
    (re.compile(r"\bq\s*$", _I), "dosing_interval"),
    (re.compile(r"\b(?:delay(?:ed)?|prolong\w*|increase[sd]?|decrease[sd]?|reduction|reduced|shift(?:ed)?"
                r"|lengthen\w*|shorten\w*|lag)\s+(?:of|by|for)\s*$", _I), "change_amount"),
    (re.compile(r"\bfor\s*$", _I), "duration_of_other_event"),
    (re.compile(r"\bby\s*$", _I), "change_amount"),
    (re.compile(r"\b(?:aged|age[sd]?|ages of|age of|older than|younger than|over the age of)\s*$", _I),
     "age_context"),
    (re.compile(r"\bauc\w*\s*[(\[]?\s*$", _I), "auc_interval"),
]
_AGE_NOUN_TAIL = re.compile(
    r"\b(?:children|child|adolescents?|infants?|neonates?|patients?|adults?|subjects?|volunteers?|aged?|ages"
    r"|men|women|boys|girls)\s*(?:(?:from|between|of)\s+)?$", _I)
_EXCLUDE_SUFFIX = [
    (re.compile(r"^\s*(?:old|of age)\b", _I), "age_context"),
    (re.compile(r"^\s*(?:dosing|dose|doses|interval|infusion|period|course|regimen|treatment|urine|"
                r"collection|fast|washout|therapy|exposure|incubation|session)\b", _I), "context_excluded"),
    (re.compile(r"^\s*of (?:treatment|therapy|dosing|administration|exposure|infusion)\b", _I),
     "context_excluded"),
    (re.compile(r"^\s*later\b", _I), "time_point_not_duration"),
    # '3 hour delay in Tmax', '2-hour increase' - a change amount
    (re.compile(r"^\s*(?:delay|lag|increase|decrease|reduction|prolongation|shift|longer|shorter)\b", _I),
     "change_amount"),
    # 'Mean Tmax (1 h): 1.7' - a unit label in a table-like layout
    (re.compile(r"^\s*\)\s*[:=]"), "table_layout"),
]
_RESPECTIVELY = re.compile(r"\brespectively\b", _I)

# M02-D1: a negated value ('is not 4 hours') or an undetermined statement
# ('... has not been established'). 'not less than' / 'no more than' /
# 'does not exceed' are bounds (qualifier rules), not negations of the value.
_NOT = r"(?:not|n['’]t|never|cannot|no)"
_BOUND_AFTER_NOT = (r"(?:less|more|longer|shorter|greater|fewer|later|earlier|sooner|exceed\w*|above|below|under"
                    r"|over)\b")
_NEGATION = re.compile(rf"(?:\b(?:not|never|cannot|no)\b|n['’]t\b)(?!\s+{_BOUND_AFTER_NOT})", _I)
_UNDETERMINED = re.compile(
    r"(?:\b(?:not|never)|n['’]t)\s+(?:yet\s+)?(?:be(?:en)?\s+)?(?:well[\s-]|fully\s+|clearly\s+|reliably\s+"
    r"|adequately\s+)?(?:established|determined|known|characteri[sz]ed|reported|measured|studied|available"
    r"|confirmed|defined|elucidated|quantified|observed|demonstrated|seen|verified|proven|shown|validated"
    r"|replicated)\b"
    r"|\byet to be\s+\w+|\b(?:unknown|undetermined|unclear|uncertain|unproven|unconfirmed|unverified|refuted)\b"
    r"|\bnot applicable\b", _I)
# Hedged value: kept, but flagged (no 5x).
_HEDGE = re.compile(
    r"\b(?:may|might|could)\s+be\b|\bpossibly\b|\bpresumably\b|\bpurportedly\b"
    r"|\b(?:thought|believed|assumed|speculated|suggested|hypothesi[sz]ed|presumed)\s+to\s+be\b", _I)
# Subordinating words start the value's own clause: in 'No dose adjustment is
# required as the half-life is 4 hours' the negation belongs to another predicate.
_CLAUSE_START = re.compile(
    r",|;|\b(?:and|but|while|whereas|as|since|because|so|although|though|which|that|when|where|if|whether)\b", _I)
# 'X has not been established' right after the value, or a following
# 'This/It/The value ... not established' clause or sentence.
_PREDICATE_CONTINUES = re.compile(
    r"^\s*(?:\([^)]*\)\s*)?,?\s*(?:has|have|had|was|were|is|are|could|can|may|might|remains?)\b", _I)
_ANAPHORIC_START = re.compile(
    r"^\s*(?:\[[^\]]*\]\s*)?(?:however,?\s*)?(?:this|these|that|such|it|the (?:value|values|estimate|figure"
    r"|result|half-life|tmax))\b", _I)
# A condition term preceded by a negation keeps the negation in its text
# ('without renal impairment', 'lacking renal impairment') and is flagged.
_NEG_COND_TAIL = re.compile(
    r"(?:\bwithout|\blacking|\bnot(?:\s+(?:in|with|for|on|receiving|undergoing|having))?"
    r"|\bwho\s+(?:do|does|did)\s+not\s+have|\bno|\bexcept(?:\s+(?:for|in))?|\bexcluding|\bother than"
    r"|\bfree (?:of|from)|\babsence of|\bunless)\s*(?:(?!(?:and|or|but)\b)[\w-]+\s+){0,2}$", _I)
# M02-D3: the value may belong to another subject.
_COMPARISON = re.compile(
    r"\b(?:unlike|like|similar to|compared (?:with|to)|in contrast to|as with|relative to"
    r"|than (?:that|those) of)\b", _I)
_RELATIVE_START = re.compile(r"\s*,?\s*(?:which|that)\b", _I)
_RELATIVE_TO_COMPARAND = re.compile(r"\b(?:which|who|whose|with)\b|\(", _I)
_NAME = r"[A-Z][\w-]*(?:\s+[A-Z0-9][\w-]*){0,2}"
_KW_I = r"(?i:half[\s-]?li(?:fe|ves)|t\s?1/2|t½|t\s?max|time to peak(?:\s+\w+){0,2})"
_NAMED_SUBJECT_BEFORE = [re.compile(p) for p in (
    rf"{_KW_I}\s+(?:of|for)\s+({_NAME})",
    rf"\b({_NAME})['’]s\s+(?:\w+\s+){{0,2}}{_KW_I}",
    rf"\b({_NAME})\s+(?:has|have|had|exhibits?|shows?|displays?|possess(?:es)?)\s+(?:an?\s+|the\s+)?(?:\w+\s+){{0,2}}"
    rf"{_KW_I}",
    rf"(?:^|[.;]\s*)(?:\[[^\]]*\]\s*)?(?:For|In)\s+({_NAME}),",
    rf"^\s*(?:\[[^\]]*\]\s*)?({_NAME}):",
    rf"{_KW_I}\s*\(({_NAME})\)",
)]
_NAMED_SUBJECT_AFTER = re.compile(rf"^\s*(?:\([^)]*\)\s*)?(?:for|of|with)\s+({_NAME})")
_GROUP_NOUN = re.compile(r"\b(?:subjects?|patients?|volunteers?|individuals?|people|adults?|children|infants"
                         r"|populations?|tablets?|capsules?|formulations?|solutions?|injections?|groups?)\b", _I)
_METABOLITE_CODE = re.compile(r"^[A-Z]{1,3}-?\d+[a-z]?$")
_MEASURE_WORD = re.compile(r"^(?:half[\s-]?li(?:fe|ves)|t\s?max|t1/2|tmax|absorption|elimination|distribution"
                           r"|mean|median|terminal|plasma|serum|the|this|these|its|it|peak|maximum)$", _I)
# M02-D5: a spread written after the value/unit or named as a statistic.
_SPREAD_PREFIX = re.compile(
    r"(?:±|\+\s*/?\s*-|∓|\bplus or minus\b|(?<![\w)])\+|\b(?:SD|SEM|SE|CV|IQR)\b|standard deviation(?:\s+of)?"
    r"|standard error(?:\s+of)?|\bCI\b|confidence interval|interquartile range|coefficient of variation)\s*[:=]?\s*$",
    _I)
_SPREAD_SUFFIX = re.compile(
    r"^\s*[,(]?\s*(?:±|\+\s*/?\s*-|∓|plus or minus|(?:with\s+an?\s+)?(?:SD|SEM|SE|CV|IQR|standard deviation"
    r"|standard error|coefficient of variation|interquartile range|\d+\s*%\s*(?:CI|confidence interval)|CI)\b)", _I)
_RANGE_TAIL = re.compile(r"\d\s*(?:to|[-–])\s*$", _I)
# M02-D2: a value-less sentence sets the scope of the values only when it says
# so ('These measurements were obtained in dogs.', 'These data apply to the
# extended-release formulation.', 'The study enrolled septic patients.').
_SCOPE_SIGNAL = re.compile(
    r"\b(?:these|this|the above|the following|such|all)\s+(?:pharmacokinetic\s+)?(?:data|values?|measurements?"
    r"|results?|parameters?|findings|estimates|observations)\b"
    r"|\b(?:data|values?|measurements?|results?|parameters?)\s+(?:were|was|are|is|come|came)\s+(?:obtained|derived"
    r"|measured|determined|collected|generated|reported|from)\b"
    r"|\bappl(?:y|ies)\s+(?:only\s+)?to\b|\brefers?\s+to\b"
    r"|\b(?:the|this)\s+study\s+(?:enrolled|included|was conducted|was performed)\b"
    r"|\bstudies\s+were\s+(?:done|conducted|performed|carried out)\b", _I)
_GOVERNING_DOUBT = re.compile(
    r"\b(?:no|little|insufficient|limited|weak|conflicting)\s+(?:\w+\s+)?(?:evidence|data|proof|support)\b"
    r"|\b(?:doubt\w*|questionable|unlikely|disputed|contradict\w*)\b", re.I)
_GOVERNING_HEDGE = re.compile(
    r"\b(?:hypothesi[sz]\w*|speculat\w*|assum\w*|suggest\w*|propos\w*|claim\w*|believ\w*|thought|possib\w*"
    r"|may|might|could|predict\w*|model(?:ed|led|ing)?|simulat\w*)\b", re.I)
# R2 (M02-D3): explicit subject phrases in any letter case. The words that
# follow 'half-life of/for' or precede 'has a half-life' are compared with the
# record name; generic, determiner, measure, condition and metabolite words
# do not form a subject.
_SUBJECT_OF = re.compile(
    r"(?i:half[\s-]?li(?:fe|ves)|t\s?1/2|t½|t\s?max|time to peak(?:\s+\w+){0,2})\s+(?:of|for)\s+"
    r"((?:[\w-]+\s+){0,3}?[\w-]+)(?=\s*(?:is|was|are|were|has|had|ranges?|ranged|varies|varied|averages?|in|at"
    r"|after|following|of|for|with|when|on|was|[,;:(]|$))", re.I)
_SUBJECT_HAS = re.compile(
    r"(?:^\s*(?:\[[^\]]*\]\s*)?|[,;(]\s*|\b(?:and|but|while|whereas)\s+)((?:[\w-]+\s+){0,2}[\w-]+)\s+"
    r"(?:has|have|had|exhibits?|shows?"
    r"|displays?|possess(?:es)?)\s+(?:an?\s+|the\s+)?(?:[\w-]+\s+){0,2}(?i:half[\s-]?li(?:fe|ves)|t\s?1/2|t\s?max)",
    re.I)
_GENERIC_SUBJECT = {
    "the", "a", "an", "this", "that", "these", "those", "its", "their", "it", "they", "which", "who", "each", "both",
    "all", "drug", "drugs", "compound", "compounds", "agent", "agents", "medication", "medicine", "product",
    "substance", "molecule", "parent", "unchanged", "total", "free", "unbound", "bound", "active", "elimination",
    "distribution", "absorption", "terminal", "apparent", "mean", "median", "average", "geometric", "arithmetic",
    "approximately", "about", "around", "roughly", "nearly", "between", "from", "up", "less", "more", "than",
    "plasma", "serum", "blood", "biological", "effective", "initial", "final", "overall", "estimated", "reported",
    "calculated", "observed", "measured", "only", "also", "following", "after", "phase", "dose", "doses", "single",
    "multiple", "oral", "intravenous", "radioactivity", "radiolabel", "label", "labeled", "labelled", "approx",
    "elimination-phase", "half", "life", "half-life", "half-lives", "and", "or", "of", "for", "in", "with",
}


def _explicit_subject_unresolved(names: Sequence[str], before: str, after: str) -> bool:
    """True when the value's own phrase names a subject that is neither the
    record drug nor a generic/measure/condition/metabolite word."""
    candidates: List[str] = [x.group(1) for x in _SUBJECT_OF.finditer(before)]
    candidates += [x.group(1) for x in _SUBJECT_HAS.finditer(before)]
    m = re.match(r"^\s*(?:\([^)]*\)\s*)?(?:for|of)\s+((?:[\w-]+\s+){0,2}[\w-]+)", after, re.I)
    if m:
        candidates.append(m.group(1))
    known = [n for n in (_strip_tags(x) for x in names) if n]
    for cand in candidates:
        words = [w for w in re.findall(r"[\w-]+", cand.lower())]
        while words and words[0] in _GENERIC_SUBJECT:
            words = words[1:]
        if not words or any(w[0].isdigit() for w in words):
            continue
        phrase = " ".join(words)
        if any(phrase == n or phrase.startswith(n + " ") or n.startswith(phrase + " ") or
               any(" ".join(words[i:]) == n for i in range(len(words))) for n in known):
            continue
        if all(w in _GENERIC_SUBJECT for w in words):
            continue
        if (_condition_spans(phrase) or _METABOLITE.search(phrase) or _PARENT.search(phrase)
                or _GROUP_NOUN.search(phrase) or _HUMAN.search(phrase) or NON_HUMAN_TERM.search(phrase)
                or _METABOLITE_CODE.match(cand.strip())):
            continue
        return True
    return False


_PK_WORD = re.compile(
    r"\b(?:eliminat\w*|half[\s-]?li(?:fe|ves)|pharmacokinetic\w*|clearance|cleared|absorption|absorbed|plasma"
    r"|serum|exposure|t\s?max|c\s?max|auc|kinetics|disposition|excret\w*|metaboli[sz]\w*|studied|measured"
    r"|data|values?|results?|parameters?)\b", re.I)
_SCOPE_NOUN = re.compile(r"\b(?:patients|subjects|volunteers|individuals|animals|species|population|formulations?"
                         r"|forms?|preparations?|products?)\b", _I)
# M02-D2: categories whose context in another (value-less) sentence of the
# same field makes a value's scope uncertain.
# Route and food are excluded: value-less sentences such as 'Oral
# bioavailability is low.' or 'Food delays absorption.' are frequent and do
# not set the scope of a value.
_CONTEXT_CATEGORIES = ("formulation", "population", "other")
_HUMAN = re.compile(r"\bhumans?\b|\bin man\b", _I)
_HALF_LIFE_TIME_POINT_PREFIX = re.compile(r"\b(?:after|at|post)\s*$", _I)
_TIME_POINT_SUFFIX = re.compile(
    r"^\s*(?:post[\s-]?dose|postdose|(?:after|following) (?:(?:the|last|first|a|an|single|oral|intravenous"
    r"|iv|initial|daily|\d+(?:\.\d+)?\s*(?:mg|g|mcg|µg))\s+){0,3}"
    r"(?:dose|dosing|administration|injection|infusion|ingestion|intake))", _I)

# Reasons that mean "a value of THIS measure was seen but could not be
# structured" (as opposed to a context exclusion such as an age).
UNRESOLVED_TARGET_REASONS = {
    "number_list_shared_unit", "ambiguous_number_format", "compound_duration", "change_amount",
    "value_below_precision",
    "ambiguous_qualifier", "change_statement", "inverted_range", "degenerate_range", "invalid_value",
    "unit_not_exactly_convertible",
}

# --------------------------------------------------------------------------
# Conditions
# --------------------------------------------------------------------------
_CS = 0  # case-sensitive flag
# Non-human / in-vitro words, matched as WORDS (never as substrings:
# 'administration' must not match 'rat').
_NON_HUMAN_RE = (
    r"\b(?:rats?|mice|mouse|murine|rodents?|dogs?|beagles?|canines?|monkeys?|macaques?|cynomolgus|marmosets?"
    r"|baboons?|primates?|rabbits?|pigs?|minipigs?|porcine|swine|animals?|in vitro|ex vivo|preclinical"
    r"|non-?clinical|cattle|cows?|bovine|sheep|ovine|horses?|equine|cats?|feline|goats?|poultry|chickens?"
    r"|guinea pigs?|hamsters?|ferrets?|veterinary|hepatocytes?|microsomes?|cell lines?|cultured cells)\b")
NON_HUMAN_TERM = re.compile(_NON_HUMAN_RE, re.I)
_COND_PATTERNS: Dict[str, List[Tuple[str, int]]] = {
    "route": [
        (r"\boral(?:ly)?\b|\bby mouth\b|\bper os\b|\bp\.o\.?", _I), (r"\bPO\b", _CS),
        (r"\bintravenous(?:ly)?\b|\bi\.v\.?", _I), (r"\bIV\b", _CS),
        (r"\bintramuscular(?:ly)?\b|\bi\.m\.", _I), (r"\bIM\b", _CS),
        (r"\bsubcutaneous(?:ly)?\b|\bs\.c\.", _I), (r"\bSC\b", _CS),
        (r"\bsublingual(?:ly)?\b|\bbuccal(?:ly)?\b|\brectal(?:ly)?\b|\btopical(?:ly)?\b"
         r"|\btransdermal(?:ly)?\b|\binhal(?:ed|ation)\b|\bintranasal(?:ly)?\b|\bnasal spray\b"
         r"|\bophthalmic\b|\bintrathecal(?:ly)?\b|\bintravitreal(?:ly)?\b", _I),
    ],
    "formulation": [
        (r"\b(?:immediate|extended|sustained|controlled|modified|delayed|prolonged)[\s-]release\b", _I),
        (r"\b(?:IR|ER|XR|XL|SR|CR|MR|DR|ODT)\b", _CS),
        (r"\b(?:tablets?|capsules?|(?:oral )?solutions?|suspensions?|injections?|injectables?"
         r"|patch(?:es)?|liposomal|depot|syrup|orally disintegrating|chewable|enteric[\s-]coated)\b", _I),
    ],
    "population": [
        (r"\bhealthy (?:adult |young |elderly |male |female )?(?:volunteers?|subjects?|adults?|individuals?"
         r"|males?|men|women|participants?)\b", _I),
        (r"\b(?:end[\s-]stage renal disease|ESRD|(?:hemo|haemo)dialysis|cirrhosis|cirrhotic)\b", _I),
        (r"\b(?:mild|moderate|severe)?\s*(?:renal|kidney|hepatic|liver) (?:function )?(?:impairment|failure"
         r"|disease|insufficiency|dysfunction)\b|\bimpaired (?:renal|kidney|hepatic|liver) function\b", _I),
        # 'patients with COPD', 'subjects with normal renal function' (up to 4 words)
        (r"\b(?:patients|subjects|individuals|people|adults|children|volunteers) (?:with|having) "
         r"[A-Za-z0-9][\w-]*(?:\s+(?!(?:and|or|is|was|were|are|in|of|had|has|have|the|a|an|than|at|after"
         r"|following|compared|versus|vs)\b)[A-Za-z][\w-]*){0,3}", _I),
        (r"\b(?:[A-Z0-9]+\s+)?(?:poor|extensive|intermediate|ultra[\s-]?rapid|normal) metabo(?:li[sz]ers?)\b", _I),
        (r"\baged\s+\d+(?:\s*(?:-|–|to)\s*\d+)?\s*(?:years?|months?|weeks?|days?)\b", _I),
        (r"\b(?:older|younger) than \d+ years?\b", _I),
        # 'children 2 to 6 years', 'infants 1-6 months' (age band after a group noun)
        (r"\b(?:children|infants|adolescents|neonates|patients|subjects|boys|girls)\s+(?:aged\s+)?\d+(?:\.\d+)?"
         r"\s*(?:-|–|to)\s*\d+(?:\.\d+)?\s*(?:years?|months?|weeks?|days?)\b", _I),
        (r"\b\d+(?:\s*(?:-|–|to)\s*\d+)?\s*years?\s+(?:old|of age)\b", _I),
        # M02-D2: a group named with 'in/among <1-2 words> patients' that is not
        # in the vocabulary is still a condition ('in burn patients')
        (r"(?:(?<=\bin\s)|(?<=\bamong\s))(?!(?:all|most|some|these|those|the|many|few|both|such|other)\b)"
         r"(?:[A-Za-z][\w-]*\s+){1,2}(?:patients|subjects|volunteers|individuals|people|recipients|users)\b", _I),
        (r"\b(?:young(?:er)?|middle-aged)\s+(?:adults|patients|subjects|people|volunteers|individuals)\b"
         r"|\b(?:healthy\s+)?controls?\b", _I),
        (r"\b(?:elderly|geriatric|older (?:adults|patients|subjects)|children|child|pediatric|paediatric"
         r"|adolescents?|infants?|neonates?|newborns?|premature|preterm|pregnan(?:t|cy)|smokers?|obese"
         r"|critically ill|adults?|volunteers?|men|women|males?|females?|non-?smokers?)\b", _I),
    ],
    "food_state": [
        (r"\bfast(?:ed|ing)\b|\bfed\b|\bwith(?:out)? (?:a )?(?:food|meals?)\b"
         r"|\bhigh[\s-]fat\b(?:,?\s*high[\s-]calorie)?(?:\s+(?:meal|breakfast|diet))?"
         r"|\bempty stomach\b|\bafter (?:a )?meals?\b|\bpost[\s-]?prandial\b", _I),
    ],
    "dosing": [
        (r"\bsingle[\s-](?:oral |intravenous |iv )?dos(?:e|es|ing)\b|\bmultiple[\s-]dos(?:e|es|ing)\b"
         r"|\brepeated[\s-]dos(?:e|es|ing)\b|\bsteady[\s-]state\b|\bloading dose\b", _I),
    ],
    "matrix": [
        (r"\b(?:plasma|serum|whole blood|intracellular(?:ly)?|cerebrospinal fluid|CSF|tissues?"
         r"|red blood cells?|erythrocytes?|bone)\b", _I),
    ],
    "kinetics": [
        (r"\bnon[\s-]?linear\b|\bdose[\s-]dependent\b|\bsaturable\b|\bmichaelis[\s-]menten\b"
         r"|\bzero[\s-]order\b|\bcapacity[\s-]limited\b|\bconcentration[\s-]dependent\b", _I),
    ],
    # Phase words count only in a phase context ('initial dose', 'beta-lactam'
    # and 'volume of distribution' are not phases).
    "phase": [
        (r"\bterminal\b|\belimination\b|\bbi-?phasic\b|\btri-?phasic\b|\bmulti-?phasic\b", _I),
        (r"\b(?:distribution(?:al)?|absorption|initial|alpha|beta|gamma)[\s-]*(?:phase|half[\s-]?li(?:fe|ves)"
         r"|t\s?1/2|t½|disposition)\b|[αβγ][\s-]*(?:phase|half[\s-]?life)|\bt\s?1/2\s*[αβγ]|t½\s*[αβγ]"
         r"|\bphase of distribution\b", _I),
    ],
    "other": [
        (_NON_HUMAN_RE, _I),
        (r"\bhumans?\b", _I),
        # radioactive decay, not elimination from the body
        (r"\bphysical half[\s-]?life\b|\bradioactive (?:half[\s-]?life|decay)\b|\bdecays?\b", _I),
        (r"\bco-?administ\w*(?:\s+with\s+[\w-]+)?|\bconcomitant(?:ly)?(?:\s+with\s+[\w-]+)?"
         r"|\bin combination with\s+[\w-]+|\b(?:when\s+)?(?:given|taken|administered|used)\s+alone\b", _I),
    ],
}
_COMPILED_COND = {k: [re.compile(p, f) for p, f in v] for k, v in _COND_PATTERNS.items()}
_LIST_CATEGORIES = ("route", "formulation", "population", "food_state", "dosing", "matrix", "kinetics",
                    "phase", "other")
_METABOLITE = re.compile(r"(?:\b(?:active|major|main|primary|inactive|principal|pharmacologically active)\s+)?"
                         r"\bmetabolites?\b", _I)
_PARENT = re.compile(r"\bparent(?:\s+(?:drug|compound|molecule))?\b|\bunchanged (?:drug|form|compound)\b", _I)
_ADMIN_REF = re.compile(
    r"\b(?:after|following)\s+(?:(?:a|an|the|single|multiple|oral|intravenous|iv|im|sc|subcutaneous"
    r"|intramuscular|sublingual|rectal|topical|\d+(?:\.\d+)?\s*(?:mg|g|mcg|µg)|[\w-]+)\s+){0,5}"
    r"(?:administration|dose|doses|dosing|ingestion|intake|injection|application)\b"
    r"|\bpost[\s-]?dose\b|\bpostdose\b", _I)

MULTIPHASE_WORDS = re.compile(
    r"\bterminal\b|\bbi-?phasic\b|\btri-?phasic\b|\bmulti-?phasic\b"
    r"|\b(?:distribution(?:al)?|initial|alpha|beta|gamma)[\s-]*(?:phase|half[\s-]?li(?:fe|ves)|t\s?1/2)"
    r"|[αβγ][\s-]*(?:phase|half[\s-]?life)|\bt\s?1/2\s*[αβγ]"
    r"|\b(?:two|three|2|3)[\s-](?:compartment|phase|exponential)",
    _I,
)
ELIMINATION_PHASES = {"terminal", "elimination"}
NON_ELIMINATION_PHASES = {"distribution", "alpha", "initial", "absorption"}
NON_PLASMA_MATRIX = ("intracellular", "cerebrospinal", "csf", "tissue", "red blood", "erythrocyte", "bone")
NON_HUMAN_OTHER = ("rat", "mice", "mouse", "dog", "monkey", "rabbit", "pig", "animal", "in vitro", "preclinical",
                   "cattle", "cow", "sheep", "horse", "cat", "goat", "swine", "poultry", "chicken", "hamster",
                   "ferret", "primate", "veterinary")
PHYSICAL_DECAY_OTHER = ("physical", "radioactive", "decay")

_CANON = {
    "orally": "oral", "by mouth": "oral", "per os": "oral", "p.o.": "oral", "p.o": "oral", "po": "oral",
    "intravenously": "intravenous", "i.v.": "intravenous", "i.v": "intravenous", "iv": "intravenous",
    "intramuscularly": "intramuscular", "i.m.": "intramuscular", "im": "intramuscular",
    "subcutaneously": "subcutaneous", "s.c.": "subcutaneous", "sc": "subcutaneous",
    "children": "child", "paediatric": "child", "pediatric": "child", "geriatric": "elderly",
    "older adults": "elderly", "older patients": "elderly", "older subjects": "elderly", "men": "male", "women": "female", "males": "male",
    "females": "female", "fasting": "fasted", "haemodialysis": "hemodialysis",
}


def canonical_term(term: str) -> str:
    t = term.lower().strip()
    if t in _CANON:
        return _CANON[t]
    if t.endswith("ly") and t[:-2] in ("sublingual", "buccal", "rectal", "topical", "transdermal",
                                       "intranasal", "intrathecal", "intravitreal"):
        return t[:-2]
    words = t.split()
    # 'pediatric patients' -> 'pediatric' -> 'child'; 'adult patients' -> 'adult'
    if len(words) > 1 and words[-1] in ("patients", "patient", "subjects", "subject", "volunteers",
                                        "volunteer", "individuals", "people"):
        return canonical_term(" ".join(words[:-1]))
    if words and len(words[-1]) > 3 and words[-1].endswith("s") and not words[-1].endswith(("ss", "is", "us")):
        words[-1] = words[-1][:-1]
    joined = " ".join(words)
    return _CANON.get(joined, joined)


# --------------------------------------------------------------------------
# Data classes
# --------------------------------------------------------------------------
@dataclass
class Span:
    start: int
    end: int


@dataclass
class ParsedQuantity:
    kind: str  # point | range | upper_bound | lower_bound
    value: Optional[float] = None
    lower: Optional[float] = None
    upper: Optional[float] = None
    inclusive: Optional[bool] = None


@dataclass
class ParsedValue:
    measure_type: str
    basis: str
    source_field: str
    sentence: Span
    value_span: Span
    original: ParsedQuantity
    unit: str
    lower_unit: Optional[str]
    hours: ParsedQuantity
    approximate: bool
    dispersion: Optional[Tuple[float, float, str]]  # (original, hours, unit)
    conditions: Dict[str, object]
    time_reference: str
    review_reasons: List[str]
    reference_tokens: List[str]
    # value_window | sentence_single_value | sentence_shared | sentence_other_clause | none
    reference_scope: str = "none"
    nearby_reference_tokens: List[str] = field(default_factory=list)
    conflict_group: Optional[str] = None


@dataclass
class ReviewEntry:
    source_field: str
    sentence: Span
    value_span: Optional[Span]
    reason: str


@dataclass
class FieldParse:
    source_field: str
    measure_type: str
    status: str
    text: Optional[str]
    length: int
    possibly_truncated: bool
    values: List[ParsedValue] = field(default_factory=list)
    reviews: List[ReviewEntry] = field(default_factory=list)
    flags: List[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def is_placeholder(text: str) -> bool:
    core = re.sub(r"[\s.;:!]+$", "", text.strip()).strip().lower()
    return core in PLACEHOLDERS


def split_sentences(text: str) -> List[Span]:
    """Sentence spans over ``text`` (exact offsets, outer whitespace trimmed).
    Trailing inline reference tokens belong to the sentence they follow. No
    split after a known abbreviation ('approx.', 'pts.', 'i.e.')."""
    cuts: List[int] = []
    for m in _SENT_END.finditer(text):
        word = re.search(r"([A-Za-z][A-Za-z.]*)$", text[:m.start()])
        if word and word.group(1).lower().rstrip(".") in _ABBREVIATIONS:
            continue
        cuts.append(m.end())
    for m in re.finditer(r"\n+", text):
        cuts.append(m.start())
    cuts = sorted(set(c for c in cuts if 0 < c < len(text)))
    spans: List[Span] = []
    start = 0
    for c in cuts + [len(text)]:
        seg = text[start:c]
        lead = len(seg) - len(seg.lstrip())
        trail = len(seg) - len(seg.rstrip())
        s, e = start + lead, c - trail
        if e > s:
            spans.append(Span(s, e))
        start = c
    return spans


def reference_tokens(text: str) -> List[str]:
    out: List[str] = []
    for m in _REF_TOKEN_GROUP.finditer(text or ""):
        for tok in m.group(1).split(","):
            tok = tok.strip()
            if tok and tok not in out:
                out.append(tok)
    return out


def _to_number(raw: str) -> Optional[float]:
    """Plain decimal with '.' only; anything else is ambiguous (None)."""
    if "," in raw or raw.count(".") > 1:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _unit_hours(unit: Optional[str]) -> Optional[float]:
    return _UNIT_HOURS.get((unit or "").lower())


def _kw_spans(patterns, text: str) -> List[Span]:
    spans = []
    for p in patterns:
        for m in p.finditer(text):
            spans.append(Span(m.start(), m.end()))
    return spans


def _distance(a: Span, b: Span) -> int:
    if a.end <= b.start:
        return b.start - a.end
    if b.end <= a.start:
        return a.start - b.end
    return 0


def _closing_paren(sentence: str, open_at: int) -> int:
    depth = 0
    for i in range(open_at, len(sentence)):
        if sentence[i] == "(":
            depth += 1
        elif sentence[i] == ")":
            depth -= 1
            if depth == 0:
                return i + 1
    return len(sentence)


def _paren_depths(sentence: str) -> List[int]:
    depth, out = 0, []
    for ch in sentence:
        if ch == "(":
            depth += 1
        out.append(depth)
        if ch == ")" and depth > 0:
            depth -= 1
    return out


def _condition_spans(text: str) -> List[Span]:
    spans = []
    for key, patterns in _COMPILED_COND.items():
        for p in patterns:
            spans.extend(Span(m.start(), m.end()) for m in p.finditer(text) if m.group(0).strip())
    spans.extend(Span(m.start(), m.end()) for m in _METABOLITE.finditer(text))
    return spans


def _residue_words(text: str) -> List[str]:
    """Content words left after removing condition terms, reference brackets,
    numbers/units and function words. Empty = the text only states a value."""
    chars = list(text)
    for s in _condition_spans(text) + [Span(m.start(), m.end()) for m in _PARENT.finditer(text)]:
        for i in range(s.start, s.end):
            chars[i] = " "
    rest = re.sub(r"\[[^\]]*\]", " ", "".join(chars))
    words = re.findall(r"\b[A-Za-z][A-Za-z-]*\b", rest)
    return [w for w in words if w.lower() not in _STOPWORDS]


def _windows(sentence: str, durations: List[Span], all_durations: List[Span]) -> Tuple[List[Span], List[bool]]:
    """Split a sentence into one window per (cutting) duration.

    Boundary between durations a and b: a parenthesis right after a belongs to
    a (unless b is inside it - then the '(' starts b's window); otherwise the
    FIRST separator after a (and its parenthesis); without a separator the
    midpoint, flagged as an uncertain boundary. Separators inside any duration
    expression ('between 12 and 18 years') do not count. A single duration
    gets the ';'-delimited clause it stands in.
    """
    depth = _paren_depths(sentence)
    if len(durations) <= 1:
        if not durations:
            return [Span(0, len(sentence))], [False]
        d = durations[0]
        top_semis = [i for i, ch in enumerate(sentence) if ch == ";" and depth[i] == 0]
        start = max([i + 1 for i in top_semis if i < d.start], default=0)
        end = min([i for i in top_semis if i >= d.end], default=len(sentence))
        return [Span(start, end)], [False]
    seps = [Span(m.start(), m.end()) for m in _SEPARATOR.finditer(sentence)
            if not any(x.start <= m.start() and m.end() <= x.end for x in all_durations)]
    cond_spans = _condition_spans(sentence)
    bounds: List[Tuple[int, int, bool]] = []
    for a, b in zip(durations, durations[1:]):
        search_from = a.end
        after = sentence[a.end:b.start]
        stripped = after.lstrip()
        if stripped.startswith("("):
            open_at = a.end + (len(after) - len(stripped))
            close_at = _closing_paren(sentence, open_at)
            if b.start < close_at:
                bounds.append((open_at, open_at + 1, False))
                continue
            search_from = close_at
        between = [s for s in seps if s.start >= search_from and s.end <= b.start]
        if between:
            s = between[0]
            # Several separators with a condition term among them ('in patients
            # with renal and hepatic impairment, and 8 h ...'): where one value's
            # conditions end is not certain.
            unsure = len(between) > 1 and any(
                between[0].end <= c.start and c.end <= between[-1].start for c in cond_spans)
            bounds.append((s.start, s.end, unsure))
        else:
            # no separator: midpoint snapped to a space; always uncertain
            mid = (a.end + b.start) // 2
            sp = sentence.rfind(" ", a.end, mid + 1)
            mid = sp if sp > a.end else mid
            bounds.append((mid, mid, True))
    windows, uncertain = [], []
    start = 0
    for end, nxt, unc in bounds:
        windows.append(Span(start, end))
        uncertain.append(unc)
        start = nxt
    windows.append(Span(start, len(sentence)))
    uncertain.append(False)
    # an uncertain boundary affects the windows on both sides
    flags = [uncertain[i] or (i > 0 and uncertain[i - 1]) for i in range(len(windows))]
    return windows, flags


def _dedupe_contained(matches: List[Tuple[int, int, str]]) -> List[str]:
    keep = []
    for s, e, t in matches:
        if any((s2 <= s and e <= e2) and (s2, e2) != (s, e) for s2, e2, _ in matches):
            continue
        keep.append((s, t))
    out: List[str] = []
    for _, t in sorted(keep):
        if t not in out:
            out.append(t)
    return out


def _norm(term: str) -> str:
    return re.sub(r"\s+", " ", term.strip()).lower()


def extract_conditions(window_text: str, measure_type: str) -> Dict[str, object]:
    cond: Dict[str, object] = {}
    for key, patterns in _COMPILED_COND.items():
        if key == "phase" and measure_type != HALF_LIFE:
            cond[key] = []
            continue
        matches = []
        for p in patterns:
            for m in p.finditer(window_text):
                start = m.start()
                neg = _NEG_COND_TAIL.search(window_text[:start])
                if neg and key not in ("phase", "kinetics", "matrix"):
                    start = neg.start()  # keep the negation inside the term text
                    negated = True
                else:
                    negated = False
                term = _norm(window_text[start:m.end()])
                if term:
                    matches.append((start, m.end(), term))
                    if negated:
                        cond["_negated"] = True
        cond[key] = _dedupe_contained(matches)
    met = [_norm(m.group(0)) for m in _METABOLITE.finditer(window_text)]
    par = [_norm(m.group(0)) for m in _PARENT.finditer(window_text)]
    if met and par:
        cond["analyte"] = "not_stated"
    elif met:
        cond["analyte"] = "metabolite"
    elif par:
        cond["analyte"] = "parent"
    else:
        cond["analyte"] = "not_stated"
    cond["analyte_terms"] = list(dict.fromkeys(met + par))
    cond["_analyte_ambiguous"] = bool(met and par)
    return cond


def _merge_leading(cond: Dict[str, object], lead: Dict[str, object]) -> None:
    """Sentence-leading clause ('In children, ...') applies to a window that
    states nothing of its own in that category."""
    for key in _LIST_CATEGORIES:
        if not cond[key] and lead[key]:
            cond[key] = list(lead[key])
    if cond["analyte"] == "not_stated" and not cond["_analyte_ambiguous"] and lead["analyte"] != "not_stated":
        cond["analyte"] = lead["analyte"]
        cond["analyte_terms"] = list(lead["analyte_terms"])


def _qualifiers(prefix: str):
    """Return (approximate, bound_kind, inclusive, ambiguous_reason, within)."""
    approx = False
    bound = None
    inclusive = None
    within = False
    p = prefix
    for _ in range(3):
        m = _APPROX_TAIL.search(p)
        if m:
            approx = True
            p = p[: m.start()]
            continue
        hit = False
        for rx, kind, inc in _NEGATED_TAIL:
            m = rx.search(p)
            if m and bound is None:
                bound, inclusive, p, hit = kind, inc, p[: m.start()], True
                break
        if hit:
            continue
        for rx, inc in _UPPER_TAIL:
            m = rx.search(p)
            if m and bound is None:
                bound, inclusive, p, hit = "upper_bound", inc, p[: m.start()], True
                break
        if hit:
            continue
        for rx, inc in _LOWER_TAIL:
            m = rx.search(p)
            if m and bound is None:
                bound, inclusive, p, hit = "lower_bound", inc, p[: m.start()], True
                break
        if hit:
            continue
        m = _WITHIN_TAIL.search(p)
        if m and bound is None:
            within = True
            p = p[: m.start()]
            continue
        break
    ambiguous = "ambiguous_qualifier" if _OVER_TAIL.search(p) else None
    return approx, bound, inclusive, ambiguous, within


def _measure_decision(measure: str, sentence: str, window: Span, dur: Span,
                      field_only_ok: bool) -> Optional[str]:
    wtext = sentence[window.start:window.end]
    rel = Span(dur.start - window.start, dur.end - window.start)
    targets = _kw_spans(TARGET[measure], wtext)
    competing = _kw_spans(COMPETING[measure], wtext)
    # 'absorption' inside 'absorption half-life', 'elimination' next to
    # 'half-life' as in 'elimination half-life': part of the target phrase.
    # 'half-life of elimination' is also the target phrase.
    competing = [c for c in competing
                 if not any(t.start <= c.start and c.end <= t.end for t in targets)
                 and not any(0 <= t.start - c.end <= 1 for t in targets)
                 and not any(re.fullmatch(r"\s+of\s+", wtext[t.end:c.start]) for t in targets if t.end <= c.start)]
    # 'after oral dosing' / 'following administration' is the time reference.
    admin = [Span(m.start(), m.end()) for m in _ADMIN_REF.finditer(wtext)]
    competing = [c for c in competing if not any(a.start <= c.start and c.end <= a.end for a in admin)]
    if targets:
        best_t = min(_distance(t, rel) for t in targets)
        best_c = min((_distance(c, rel) for c in competing), default=None)
        if best_c is None or best_t <= best_c:
            return "value_keyword"
        return None
    sentence_targets = [t for t in _kw_spans(TARGET[measure], sentence) if t.end <= dur.start]
    # Inherit the measure from an earlier clause only when this clause states
    # nothing but the value and its conditions ('..., and 12 hours in the
    # elderly'), not another event ('... but platelet inhibition lasts 7 days').
    clause = wtext[:rel.start] + " " + wtext[rel.end:]
    if sentence_targets and not competing and not _residue_words(clause):
        return "sentence_keyword"
    if field_only_ok and not _kw_spans(TARGET[measure], sentence) and not _kw_spans(COMPETING[measure], sentence):
        return "field_only"
    return None


def _field_only_allowed(raw: str, sentences: List[Span], matches: List[re.Match]) -> bool:
    """Bare half_life field such as '4-6 hours' or 'Approximately 2 hours in
    adults': one sentence, one duration, nothing else but conditions and
    function words."""
    if len(sentences) != 1 or len(matches) != 1:
        return False
    s = sentences[0]
    stext = raw[s.start:s.end]
    m = matches[0]
    rest = stext[:m.start()] + " " + stext[m.end():]
    return not _residue_words(rest)


def _exclusion(measure: str, prefix: str, suffix: str, unit: str, basis: str) -> Optional[str]:
    # also look behind an approximation word: 'delayed for about 1 to 2 hours'
    bare_prefix = _APPROX_TAIL.sub("", prefix)
    for rx, reason in _EXCLUDE_PREFIX:
        if rx.search(prefix) or rx.search(bare_prefix):
            return reason
    if unit.lower() in _AGE_UNITS and _AGE_NOUN_TAIL.search(prefix):
        return "age_context"
    for rx, reason in _EXCLUDE_SUFFIX:
        if rx.search(suffix):
            return reason
    if measure == HALF_LIFE:
        if _HALF_LIFE_TIME_POINT_PREFIX.search(prefix):
            return "time_point_not_duration"
        if _TIME_POINT_SUFFIX.search(suffix):
            # 'The half-life is 4 hours after oral administration': the value is
            # the predicate of the half-life; the suffix is its route context.
            bare = _APPROX_TAIL.sub("", prefix).rstrip()
            if not (basis == "value_keyword" and _COPULA_TAIL.search(bare)):
                return "time_point_not_duration"
    return None


def _strong_keyword(measure: str, sentence: str) -> bool:
    if measure == HALF_LIFE:
        return bool(_kw_spans(HALF_LIFE_KW, sentence))
    if _kw_spans(TMAX_STRONG_KW, sentence) or _CMAX_REACHED.search(sentence):
        return True
    return bool((_PEAK_CONC.search(sentence) or _CONC_PEAK.search(sentence)) and _TEMPORAL_VERB.search(sentence))


def _is_cutting(m: re.Match, stext: str) -> bool:
    """Age expressions ('aged 65 years', 'children 2 to 12 years') do not split
    a sentence into windows; they are conditions of the surrounding value."""
    unit = (m.group("u2") or "").lower()
    prefix = stext[max(0, m.start() - 40):m.start()]
    if unit in _AGE_UNITS:
        return False
    if any(rx.search(prefix) for rx, reason in _EXCLUDE_PREFIX if reason == "age_context"):
        return False
    if re.match(r"^\s*(?:old|of age)\b", stext[m.end():], _I):
        return False
    return True


# --------------------------------------------------------------------------
# Field parsing
# --------------------------------------------------------------------------
def _strip_tags(name: str) -> str:
    return re.sub(r"\[[^\]]*\]", " ", name or "").strip().lower()


_FORM_NOUN = re.compile(r"\s+(?:tablets?|capsules?|formulations?|solutions?|injections?)\b.*$", _I)


def _subject_verdict(names: Optional[Sequence[str]], candidate: str, following: str = "") -> str:
    """'record' | 'foreign' | 'code' | 'ignore' for a capitalised name found as
    the subject of the measure. Group phrases ('Japanese subjects'), condition,
    measure and species words are ignored; metabolite-like codes ('M1') are
    flagged, not refused. A product word is stripped ('Zorvix tablets' is judged
    as 'Zorvix'). A different spelling of the record name ('Synthazol-N-oxide')
    is foreign. Without record names nothing is judged; there is no general
    drug-name recognition (lower-case names are not detected)."""
    head = candidate.strip()
    if not names or not head:
        return "ignore"
    nxt = following.split()[0] if following.split() else ""
    if _GROUP_NOUN.fullmatch(nxt or "-") and not _FORM_NOUN.match(" " + nxt):
        return "ignore"  # 'Japanese subjects', 'Adult patients': a population, not a drug
    if (not head or _MEASURE_WORD.match(head) or _condition_spans(head) or _METABOLITE.search(head)
            or _PARENT.search(head) or _HUMAN.search(head) or NON_HUMAN_TERM.search(head)):
        return "ignore"
    if _METABOLITE_CODE.match(head):
        return "code"
    low = head.lower()
    known = [n for n in (_strip_tags(x) for x in names) if n]
    if any(low == n or low.startswith(n + " ") or n.startswith(low + " ") for n in known):
        return "record"
    return "foreign"


def _field_context(raw: str, sentences: List[Span], all_matches, measure: str) -> Tuple[Dict[str, bool], bool]:
    """(categories, non_human). Categories: condition categories stated in a
    value-less sentence of the field that explicitly sets a scope ('These
    measurements were obtained in dogs.', 'These data apply to the
    extended-release formulation.', 'The study enrolled septic patients.');
    'unrecognized' when such a sentence names a group/form outside the
    vocabulary. non_human: a non-human/in-vitro word in such a scope sentence
    or in a sentence that states a duration. Ordinary value-less sentences
    ('It is available as tablets.', 'No dose adjustment is needed in the
    elderly.') do not set a scope."""
    cats: Dict[str, bool] = {}
    non_human = False
    for s, ms in zip(sentences, all_matches):
        stext = raw[s.start:s.end]
        if ms:
            non_human = non_human or bool(NON_HUMAN_TERM.search(stext))
            continue
        words = re.findall(r"[A-Za-z][\w-]*", re.sub(r"\[[^\]]*\]", " ", stext))
        heading = stext.rstrip().endswith(":") or (len(words) <= 4 and not stext.rstrip().endswith("."))
        # R2 (M02-D2): a known species/in-vitro word together with a
        # pharmacokinetic word ('In dogs, elimination was studied.') also sets
        # the scope; a species sentence about something else ('In vitro studies
        # indicate that X is a P-gp substrate.') does not.
        pk_species = bool(NON_HUMAN_TERM.search(stext) and _PK_WORD.search(stext))
        if not (_SCOPE_SIGNAL.search(stext) or heading or pk_species):
            continue
        non_human = non_human or bool(NON_HUMAN_TERM.search(stext))
        cond = extract_conditions(stext, measure)
        found = [k for k in _CONTEXT_CATEGORIES if cond[k]]
        for k in found:
            cats[k] = True
        if not found and _SCOPE_NOUN.search(stext):
            cats["unrecognized"] = True
    return cats, non_human


def parse_field(source_field: str, text: Optional[str], stored_max_length: Optional[int] = None,
                subject_names: Optional[Sequence[str]] = None) -> FieldParse:
    """``subject_names``: names of the record drug (used only to notice a value
    stated for another, capitalised subject; no name recognition otherwise)."""
    measure = FIELD_MEASURE[source_field]
    raw = text if text is not None else None
    length = len(raw) if raw else 0
    truncated = bool(raw) and stored_max_length is not None and length >= stored_max_length
    fp = FieldParse(source_field=source_field, measure_type=measure, status="empty", text=raw,
                    length=length, possibly_truncated=truncated)
    if raw is None or not raw.strip():
        fp.status = "empty"
        return fp
    if is_placeholder(raw):
        fp.status = "placeholder"
        return fp
    if truncated:
        fp.flags.append("stored_text_possibly_truncated")

    sentences = split_sentences(raw)
    if any(p.search(raw) for p in _COMPILED_COND["kinetics"]):
        fp.flags.append("nonlinear_or_dose_dependent_kinetics_mentioned")
    if measure == HALF_LIFE and MULTIPHASE_WORDS.search(raw):
        fp.flags.append("multiphasic_description")
    if measure == HALF_LIFE and _METABOLITE.search(raw):
        fp.flags.append("metabolite_mentioned")
    all_matches = [list(DURATION_RE.finditer(raw[s.start:s.end])) for s in sentences]
    field_only_ok = (measure == HALF_LIFE and _field_only_allowed(
        raw, sentences, [m for ms in all_matches for m in ms]))
    context_cats, non_human_in_field = _field_context(raw, sentences, all_matches, measure)
    if context_cats:
        fp.flags.append("context_in_valueless_sentence:" + ",".join(sorted(context_cats)))
    if non_human_in_field:
        fp.flags.append("non_human_species_mentioned")

    for idx, (sent, matches) in enumerate(zip(sentences, all_matches)):
        stext = raw[sent.start:sent.end]
        is_last = idx == len(sentences) - 1
        if truncated and is_last and not re.search(r"[.!?](?:\s*\[[^\]]*\])*\s*$", stext):
            fp.reviews.append(ReviewEntry(source_field, sent, None, "sentence_possibly_truncated"))
            continue
        if not matches:
            if _strong_keyword(measure, stext):
                fp.reviews.append(ReviewEntry(source_field, sent, None, "keyword_without_parsable_value"))
            continue

        cutting = [m for m in matches if _is_cutting(m, stext)] or matches[:1]
        windows, uncertain = _windows(stext, [Span(m.start(), m.end()) for m in cutting],
                                      [Span(m.start(), m.end()) for m in matches])

        def window_of(m: re.Match) -> int:
            for i, w in enumerate(windows):
                if w.start <= m.start() < w.end or (i == len(windows) - 1 and m.start() >= w.start):
                    return i
            return 0

        trailing = _TRAILING_TOKENS.search(stext)
        trailing_start = trailing.start(1) if trailing else len(stext)
        trailing_tokens = reference_tokens(trailing.group(1)) if trailing else []
        # Framing clause: text before the first comma ('In children, ...'), or
        # the text before a '(' that encloses the values ('... increase in
        # half life (9 to 30 hours iv, 15.7 to 18.2 hours orally)').
        lead_end = stext.find(",")
        if not (0 < lead_end < cutting[0].start()):
            paren = stext.rfind("(", 0, cutting[0].start())
            lead_end = paren if paren > 0 and _closing_paren(stext, paren) >= cutting[-1].end() else -1
        lead_cond = None
        if len(windows) > 1 and 0 < lead_end < cutting[0].start():
            lead_cond = extract_conditions(stext[:lead_end], measure)

        # Adjacent values: '1 h 30 min' (only whitespace between) is one
        # compound duration; '4 h and 8 h' / '4 h, 8 h' is a positional list.
        compound, parallel = set(), set()
        for i in range(len(matches) - 1):
            gap = stext[matches[i].end():matches[i + 1].start()]
            if re.fullmatch(r"\s*", gap):
                compound.update((i, i + 1))
            elif re.fullmatch(r"\s*(?:,|,?\s*\b(?:and|or)\b)\s*", gap, _I):
                parallel.update((i, i + 1))

        sentence_values: List[ParsedValue] = []
        sentence_unresolved = False
        for mi, m in enumerate(matches):
            wi = window_of(m)
            win = windows[wi]
            abs_span = Span(sent.start + m.start(), sent.start + m.end())
            prefix = stext[max(0, m.start() - 40):m.start()]
            suffix = stext[m.end():m.end() + 50]

            def review(reason: str) -> None:
                nonlocal sentence_unresolved
                fp.reviews.append(ReviewEntry(source_field, sent, abs_span, reason))
                if reason in UNRESOLVED_TARGET_REASONS:
                    sentence_unresolved = True

            # RULES.md 5: first which measure (if any) the duration states,
            # then context exclusions, then qualifiers.
            basis = _measure_decision(measure, stext, win, Span(m.start(), m.end()), field_only_ok)
            if basis is None:
                review(f"duration_not_identified_as_{measure}")
                continue
            sep = m.group("sep")
            n1, n2, u1, u2 = m.group("n1"), m.group("n2"), m.group("u1"), m.group("u2")
            excl = _exclusion(measure, prefix, suffix, u2, basis)
            if excl:
                review(excl)
                continue
            # M02-D1: a negated or undetermined value is not a measurement. Only
            # the value's own clause counts ('No dose adjustment is required as
            # the half-life is 4 hours' is a clear value); a negation that governs
            # a condition ('in patients with no hepatic impairment') is a negated
            # condition, not a negated value.
            before = stext[win.start:m.start()]
            starts = list(_CLAUSE_START.finditer(before))
            own_clause = before[starts[-1].end():] if starts else before
            cond_spans = _condition_spans(own_clause)
            value_negations = [
                n for n in _NEGATION.finditer(own_clause)
                if not any(0 <= c.start - n.end() <= 30 for c in cond_spans)]
            if value_negations:
                review("negated_value")
                continue
            # R2 (M02-D1): a value in a 'whether' / 'if' clause is not asserted;
            # a value in a 'that' clause takes the meaning of the clause that
            # governs it ('There is no evidence that ...', 'It has not been
            # established that ...'). 'as/since/because' clauses are asserted.
            if starts:
                opener = starts[-1].group(0).lower()
                governing = before[starts[-2].end():starts[-1].start()] if len(starts) > 1 \
                    else before[:starts[-1].start()]
                if opener in ("whether", "if"):
                    review("hypothetical_or_open_question")
                    continue
                if opener == "that" and (_NEGATION.search(governing) or _UNDETERMINED.search(governing)
                                         or _GOVERNING_DOUBT.search(governing)):
                    review("undetermined_statement")
                    continue
                governed_hedge = opener == "that" and bool(_GOVERNING_HEDGE.search(governing))
            else:
                governed_hedge = False
            after = stext[m.end():win.end]
            after_starts = list(_CLAUSE_START.finditer(after))
            first_after = after[:after_starts[0].start()] if after_starts else after
            relative_after = ""
            rel = _RELATIVE_START.match(after[after_starts[0].start():]) if after_starts else None
            if rel:
                rel_end = after_starts[0].start() + rel.end()
                nxt = min([x.start() for x in after_starts if x.start() >= rel_end], default=len(after))
                relative_after = after[after_starts[0].start():nxt]
            if (_UNDETERMINED.search(own_clause) or _UNDETERMINED.search(first_after)
                    or _UNDETERMINED.search(relative_after)):
                review("undetermined_statement")
                continue
            hedged = bool(_HEDGE.search(own_clause) or _HEDGE.search(first_after) or governed_hedge)
            # M02-D5: a spread or range written in a form the value rules do not read
            if _SPREAD_PREFIX.search(prefix) or _RANGE_TAIL.search(prefix):
                review("dispersion_or_range_form_not_structured")
                continue
            approx, bound, inclusive, ambiguous, within = _qualifiers(prefix)
            if ambiguous:
                review(ambiguous)
                continue
            if within and measure == HALF_LIFE:
                review("ambiguous_qualifier")
                continue
            if mi in compound:
                review("compound_duration")
                continue
            if _NUMBER_LIST_TAIL.search(prefix):
                review("number_list_shared_unit")
                continue
            if sep and _FROM_TAIL.search(prefix) and not _RANGING_FROM_TAIL.search(prefix) \
                    and _CHANGE_VERB.search(stext[:m.start()]):
                review("change_statement")
                continue
            bare = _APPROX_TAIL.sub("", prefix)
            if _CHANGE_VERB_TAIL.search(prefix) or _CHANGE_VERB_TAIL.search(bare):
                review("change_statement" if _TO_TAIL.search(bare) else "change_amount")
                continue
            # M02-D3: the value may describe another subject. A value inside the
            # comparand's relative clause ('Unlike Drug B, which has a half-life of
            # 10 hours, ...') is not the record drug's; a comparison earlier in
            # the clause only flags the value.
            comparison_flag = False
            cmp_before = list(_COMPARISON.finditer(before))
            if cmp_before:
                if _RELATIVE_TO_COMPARAND.search(before[cmp_before[-1].end():]):
                    review("subject_unresolved_comparison")
                    continue
                comparison_flag = True
            # each candidate is judged with the two words that follow it
            # ('Japanese subjects', 'Zorvix tablets')
            named = [(x.group(1), " ".join(stext[x.end(1):x.end(1) + 30].split()[:2]))
                     for rx in _NAMED_SUBJECT_BEFORE for x in rx.finditer(stext[:m.start()])]
            after_subject = _NAMED_SUBJECT_AFTER.match(stext[m.end():win.end])
            if after_subject:
                tail = stext[m.end() + after_subject.end(1):m.end() + after_subject.end(1) + 30].split()[:2]
                named.append((after_subject.group(1), " ".join(tail)))
            verdicts = [_subject_verdict(subject_names, n, nxt) for n, nxt in named]
            if "foreign" in verdicts:
                review("subject_not_record_drug")
                continue
            # R2 (M02-D3): the same subject positions in any letter case
            # ('The half-life of drug b ...', 'drug b has a half-life ...').
            if subject_names and _explicit_subject_unresolved(
                    subject_names, stext[win.start:m.start()], stext[m.end():win.end]):
                review("subject_unresolved")
                continue
            subject_code = "code" in verdicts
            if m.group("sign"):
                review("invalid_value")
                continue
            v1 = _to_number(n1)
            v2 = _to_number(n2) if n2 else None
            pmv = _to_number(m.group("pmv")) if m.group("pmv") else None
            if v1 is None or (n2 and v2 is None) or (m.group("pmv") and pmv is None):
                review("ambiguous_number_format")
                continue
            f1 = _unit_hours(u1 or u2)
            f2 = _unit_hours(u2)
            if f1 is None or f2 is None:
                review("unit_not_exactly_convertible")
                continue
            values = [v for v in (v1, v2) if v is not None]
            if any((not math.isfinite(v)) or v <= 0 for v in values):
                review("invalid_value")
                continue
            if pmv is not None and (not math.isfinite(pmv) or pmv < 0):
                review("invalid_value")
                continue

            reasons: List[str] = []
            if v2 is not None:
                lo_h, hi_h = v1 * f1, v2 * f2
                if lo_h > hi_h:
                    review("inverted_range")
                    continue
                if lo_h == hi_h:
                    review("degenerate_range")
                    continue
                if bound is not None:
                    review("ambiguous_qualifier")
                    continue
                original = ParsedQuantity("range", lower=v1, upper=v2)
                hours = ParsedQuantity("range", lower=round(lo_h, 6), upper=round(hi_h, 6))
                unit, lower_unit = u2, (u1 if (u1 and u1.lower() != u2.lower()) else None)
            elif bound == "upper_bound" or (within and measure == TMAX):
                inc = True if within and bound is None else inclusive
                original = ParsedQuantity("upper_bound", upper=v1, inclusive=inc)
                hours = ParsedQuantity("upper_bound", upper=round(v1 * f1, 6), inclusive=inc)
                unit, lower_unit = (u1 or u2), None
            elif bound == "lower_bound":
                original = ParsedQuantity("lower_bound", lower=v1, inclusive=inclusive)
                hours = ParsedQuantity("lower_bound", lower=round(v1 * f1, 6), inclusive=inclusive)
                unit, lower_unit = (u1 or u2), None
            else:
                original = ParsedQuantity("point", value=v1)
                hours = ParsedQuantity("point", value=round(v1 * f1, 6))
                unit, lower_unit = (u1 or u2), None
            members = [x for x in (hours.value, hours.lower, hours.upper) if x is not None]
            if any(not math.isfinite(x) for x in members):
                review("invalid_value")
                continue
            if any(x == 0 for x in members):
                review("value_below_precision")  # never published as 0 h
                continue
            dispersion = None
            if pmv is not None:
                # '1.5 h ± 20 min': the value has u1, the spread has u2.
                spread_h = pmv * f2
                if not math.isfinite(spread_h):
                    review("invalid_value")  # M02-D5: never a silent null spread
                    continue
                if pmv > 0 and round(spread_h, 6) == 0:
                    review("value_below_precision")
                    continue
                dispersion = (pmv, round(spread_h, 6), u2)

            wtext = stext[win.start:win.end]
            cond = extract_conditions(wtext, measure)
            if lead_cond is not None and wi > 0:
                if _CONTRAST.search(wtext):
                    # 'In the elderly, ... 3 h, compared with 1 h in young people':
                    # the later value names another group; do not inherit.
                    if any(lead_cond[k] for k in _LIST_CATEGORIES):
                        reasons.append("condition_attribution_ambiguous")
                else:
                    _merge_leading(cond, lead_cond)
            if cond.pop("_analyte_ambiguous"):
                reasons.append("analyte_ambiguous")
            if hedged:
                reasons.append("hedged_value")
            if comparison_flag:
                reasons.append("comparison_in_clause")
            if subject_code:
                reasons.append("subject_code_unresolved")
            if _SPREAD_SUFFIX.match(stext[m.end():]):
                reasons.append("dispersion_not_structured")
            if cond.pop("_negated", False):
                reasons.append("negated_condition")  # e.g. 'without renal impairment'
            # M02-D2: context stated in a value-less sentence of the field
            if context_cats.get("unrecognized"):
                missing = not (cond["population"] or cond["formulation"] or cond["other"])
            else:
                missing = any(not cond[k] for k in context_cats)
            if missing:
                reasons.append("field_context_unattributed")
            own_species = any(NON_HUMAN_TERM.search(o) or _HUMAN.search(o) for o in cond["other"])
            if non_human_in_field and not own_species:
                reasons.append("non_human_context_in_field")
            if uncertain[wi] and _condition_spans(stext) and "condition_attribution_ambiguous" not in reasons:
                reasons.append("condition_attribution_ambiguous")
            if mi in parallel:
                reasons.append("parallel_value_list")
            if measure == TMAX:
                time_ref = "after_administration" if (_ADMIN_REF.search(wtext) or _ADMIN_REF.search(suffix)) \
                    else "not_stated"
            else:
                time_ref = "not_applicable_duration"
            if truncated:
                reasons.append("stored_text_possibly_truncated")

            # M02-D4 / R2: a token is attributed to the value only when it stands in
            # the value's OWN claim: from the clause start before the value to the
            # next clause start after it ('4 hours [A1], while adverse events are
            # described elsewhere [A2]' -> A1 only). A sentence-end token is the
            # value's only if no other claim follows the value; several values in
            # one sentence share it (not exclusive). Everything else is 'nearby'.
            claim_end_limit = min(win.end, trailing_start)
            own_starts = list(_CLAUSE_START.finditer(stext[win.start:m.start()]))
            claim_start = win.start + own_starts[-1].end() if own_starts else win.start
            next_start = _CLAUSE_START.search(stext, m.end(), claim_end_limit) if m.end() < claim_end_limit else None
            claim_end = next_start.start() if next_start else claim_end_limit
            claim_tokens = reference_tokens(stext[claim_start:claim_end])
            nearby: List[str] = []
            if claim_tokens:
                tokens, scope = claim_tokens, "value_window"
            elif trailing_tokens:
                depth = _paren_depths(stext)
                top_semis = [i for i, ch in enumerate(stext[:trailing_start]) if ch == ";" and depth[i] == 0]
                after_value = stext[m.end():trailing_start]
                other_claim_after = any(
                    _residue_words(after_value[x.end():]) for x in _CLAUSE_START.finditer(after_value))
                if any(i >= m.end() for i in top_semis):
                    tokens, scope, nearby = [], "sentence_other_clause", list(trailing_tokens)
                elif len(matches) > 1:
                    tokens, scope = trailing_tokens, "sentence_shared"
                elif other_claim_after:
                    tokens, scope, nearby = [], "sentence_other_clause", list(trailing_tokens)
                elif _residue_words(after_value):
                    tokens, scope = trailing_tokens, "sentence_shared"
                else:
                    tokens, scope = trailing_tokens, "sentence_single_value"
            else:
                tokens, scope = [], "none"
            other_tokens = [t for t in reference_tokens(stext) if t not in tokens and t not in nearby]
            nearby += other_tokens
            pv = ParsedValue(
                measure_type=measure, basis=basis, source_field=source_field, sentence=sent,
                value_span=abs_span, original=original, unit=unit, lower_unit=lower_unit, hours=hours,
                approximate=approx, dispersion=dispersion, conditions=cond, time_reference=time_ref,
                review_reasons=reasons, reference_tokens=tokens, reference_scope=scope,
                nearby_reference_tokens=nearby,
            )
            sentence_values.append(pv)

        # '... X and Y, respectively': which value belongs to which subject is
        # positional, not stated next to the value.
        respectively = len(matches) > 1 and bool(_RESPECTIVELY.search(stext))
        # M02-D1: a following clause or sentence that says the value is not
        # established ('...; however, this has not been established.' /
        # 'This has not been established.') flags the values it refers to.
        depth = _paren_depths(stext)
        semis = [i for i, ch in enumerate(stext) if ch == ";" and depth[i] == 0]
        next_text = raw[sentences[idx + 1].start:sentences[idx + 1].end] if idx + 1 < len(sentences) else ""
        denied_next = bool(_ANAPHORIC_START.match(next_text) and _UNDETERMINED.search(next_text))
        for pv in sentence_values:
            rel_end = pv.value_span.end - sent.start
            later = [stext[i + 1:(min([j for j in semis if j > i], default=len(stext)))]
                     for i in semis if i >= rel_end]
            denied_clause = any(_ANAPHORIC_START.match(c) and _UNDETERMINED.search(c) for c in later)
            if (denied_clause or denied_next) and "undetermined_statement" not in pv.review_reasons:
                pv.review_reasons.append("undetermined_statement")
            if respectively and "respectively_construct" not in pv.review_reasons:
                pv.review_reasons.append("respectively_construct")
            if pv.reference_scope == "sentence_single_value" and len(sentence_values) > 1:
                pv.reference_scope = "sentence_shared"
            if sentence_unresolved and "other_value_in_sentence_unresolved" not in pv.review_reasons:
                pv.review_reasons.append("other_value_in_sentence_unresolved")
        fp.values.extend(sentence_values)

    _mark_conflicts(fp)
    if fp.values:
        fp.status = "parsed" if any(not v.review_reasons for v in fp.values) else "parsed_needs_review"
    elif fp.reviews:
        fp.status = "unparsed_needs_review"
    elif measure == HALF_LIFE:
        fp.reviews.append(ReviewEntry(source_field, Span(0, len(raw)), None, "no_parsable_value"))
        fp.status = "unparsed_needs_review"
    else:
        fp.status = "no_statement_found"
    return fp


def condition_key(v: ParsedValue) -> tuple:
    c = v.conditions
    return (v.measure_type,) + tuple(
        tuple(sorted({canonical_term(t) for t in c[k]})) for k in _LIST_CATEGORIES
    ) + (c["analyte"],)


def _value_key(v: ParsedValue) -> tuple:
    h = v.hours
    return (h.kind, h.value, h.lower, h.upper, h.inclusive)


def _mark_conflicts(fp: FieldParse) -> None:
    groups: Dict[tuple, List[ParsedValue]] = {}
    for v in fp.values:
        groups.setdefault(condition_key(v), []).append(v)
    n = 0
    for members in groups.values():
        if len({_value_key(v) for v in members}) > 1:
            n += 1
            gid = f"{fp.source_field}:conflict{n}"
            for v in members:
                v.conflict_group = gid
                if "conflicting_values_same_conditions" not in v.review_reasons:
                    v.review_reasons.append("conflicting_values_same_conditions")
