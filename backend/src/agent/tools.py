import threading
import time
from contextvars import ContextVar
from typing import Annotated, Literal, Optional
from langchain_core.tools import tool

from dataclasses import dataclass, field

from ..drugs import service as drug_service
from ..drugs.models import (
    DrugSearchRequest,
    CheckDrugInteractionRequest,
    DrugSearchByIndicationRequest,
    DrugSearchByCategoryRequest,
    AnalyzePatientRequest,
    SEVERITY_NOT_RATED,
)
from ..pubmed import service as pubmed_service
from ..pubmed.models import PubMedSearchResult
from ..pubmed.service import extract_relevant_snippet
from ..pubmed.scoring import get_quality_warnings
from ..config import settings

from logging import getLogger

logger = getLogger(__name__)

# ============================================================================
# Cross-thread source & debug propagation
# ============================================================================

# ContextVar writes inside LangChain tool functions do NOT propagate back to
# the caller when LangChain runs synchronous tools in a thread-pool (which is
# the default for ``agent.astream()``).  The child thread receives a *copy* of
# the parent context, so reads work but writes are isolated.

# Fix: tools READ a ``_request_id_var`` (copied to the thread) and WRITE
# results into a plain thread-safe dict keyed by that request ID.  After the
# agent call the caller pops the results from the dict.

_request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# Shared stores — dict operations are atomic under CPython's GIL; we add a
# lock for belt-and-suspenders safety on pop-with-default.
_store_lock = threading.Lock()
_source_store: dict[str, list] = {}
_debug_store: dict[str, dict] = {}
# Per-request monotonic REF counter. Must NOT be derived from len(_source_store)
# because ref ids are allocated before the source is appended (e.g. inside a
# loop that builds many sources in one tool call). Using len() would give every
# entry in the loop the same id.
_ref_counter: dict[str, int] = {}

# Counter for the ContextVar-only (non-streaming) path. Tracked per-coroutine
# via a ContextVar so cross-request contamination is impossible. Audit A6:
# the previous fallback used `len(existing) + 1`, which produced duplicate
# REF ids when the same source list was extended in multiple passes.
_legacy_ref_counter_var: ContextVar[int] = ContextVar(
    "legacy_ref_counter", default=0
)

# Legacy ContextVar kept for backward-compatibility with ``handle_user_query``
# (non-streaming path) where tool and caller share the same context.
_last_search_sources_var: ContextVar[list | None] = ContextVar(
    "last_search_sources", default=None
)
_last_tool_debug_var: ContextVar[dict | None] = ContextVar(
    "last_tool_debug", default=None
)

# Stores the authenticated user's ID so agent tools can perform
# user-scoped lookups without exposing the ID to the LLM.
_current_user_id_var: ContextVar[str | None] = ContextVar(
    "current_user_id", default=None
)

# Stores the current patient ID for patient-scoped operations
_current_patient_id_var: ContextVar[str | None] = ContextVar(
    "current_patient_id", default=None
)


def set_request_id(request_id: str) -> None:
    """Set a unique request ID for the current coroutine.

    Must be called before each agent invocation so that tools (which may run in
    a thread-pool) can read it and write results into the shared stores.

    Audit A7: also reaps stale entries from the per-request stores. Without
    this sweep, requests that error out before `get_last_search_sources` is
    called would leak their REF counter, source list, and debug dict forever.
    """
    _request_id_var.set(request_id)
    # Reset the legacy ContextVar counter at the start of each request so a
    # fresh non-streaming call doesn't inherit the previous coroutine's count.
    _legacy_ref_counter_var.set(0)
    _gc_request_stores()


# Each request stores its creation time so we can reap stale entries even
# when no one ever calls `get_last_search_sources` (e.g. exception before
# the read). Audit A7.
_REQUEST_STORE_TTL_SECONDS = 30 * 60  # 30 minutes — generous; agent calls finish in seconds
_REQUEST_STORE_MAX_ENTRIES = 1000     # hard cap — prevents pathological growth
_request_birth: dict[str, float] = {}


def _gc_request_stores() -> None:
    """Drop stale entries from per-request stores. Called from set_request_id."""
    now = time.time()
    with _store_lock:
        # Mark current request alive
        rid = _request_id_var.get()
        if rid is not None:
            _request_birth[rid] = now

        # Reap by TTL
        stale = [k for k, born in _request_birth.items() if now - born > _REQUEST_STORE_TTL_SECONDS]
        for k in stale:
            _request_birth.pop(k, None)
            _source_store.pop(k, None)
            _debug_store.pop(k, None)
            _ref_counter.pop(k, None)

        # Hard cap on entry count — drop oldest first if we're over the limit
        if len(_request_birth) > _REQUEST_STORE_MAX_ENTRIES:
            # Sort by creation time ascending; drop oldest
            extra = len(_request_birth) - _REQUEST_STORE_MAX_ENTRIES
            for k in sorted(_request_birth, key=lambda x: _request_birth[x])[:extra]:
                _request_birth.pop(k, None)
                _source_store.pop(k, None)
                _debug_store.pop(k, None)
                _ref_counter.pop(k, None)


def _store_sources(sources: Optional[list], tool_name: str = "unknown") -> None:
    """Append sources into both the shared dict (for streaming) and the
    ContextVar (for the non-streaming path).  Multiple tool calls in the
    same request accumulate sources instead of overwriting."""
    if sources is None:
        return
    # Tag each source with the originating tool
    for s in sources:
        s.setdefault("tool", tool_name)
    # ContextVar path (non-streaming)
    existing_cv = _last_search_sources_var.get()
    if existing_cv is None:
        _last_search_sources_var.set(list(sources))
    else:
        existing_cv.extend(sources)
    # Shared-dict path (streaming)
    rid = _request_id_var.get()
    if rid is not None:
        with _store_lock:
            existing = _source_store.get(rid)
            if existing is None:
                _source_store[rid] = list(sources)
            else:
                existing.extend(sources)


def _store_debug(debug: Optional[dict]) -> None:
    """Write debug info into both the shared dict and the ContextVar."""
    _last_tool_debug_var.set(debug)
    rid = _request_id_var.get()
    if rid is not None:
        with _store_lock:
            _debug_store[rid] = debug # type: ignore


def get_last_search_sources(request_id: Optional[str] = None):
    """
    Return and clear the search sources for the given request.

    When *request_id* is provided (streaming path) the shared dict is used,
    falling back to the ContextVar for the non-streaming path.
    """
    if request_id is not None:
        with _store_lock:
            sources = _source_store.pop(request_id, None)
            # Clean up per-request counter and birth time too (audit A7).
            _ref_counter.pop(request_id, None)
            _request_birth.pop(request_id, None)
        if sources is not None:
            return sources
    # Fallback: non-streaming path where tool and caller share context
    sources = _last_search_sources_var.get()
    _last_search_sources_var.set(None)
    return sources or []


def peek_search_sources(request_id: str) -> list:
    """Copy of the sources collected so far for a request (does not clear).

    Used by the streaming path to forward sources while the answer is still
    being generated, so citations in partial text can already be resolved.
    """
    with _store_lock:
        return list(_source_store.get(request_id) or [])


def get_last_tool_debug(request_id: Optional[str] = None) -> Optional[dict]:
    """Return and clear debug info for the given request."""
    if request_id is not None:
        with _store_lock:
            debug = _debug_store.pop(request_id, None)
            # Even if there's no debug data, clear the birth marker once the
            # caller is done with the request (audit A7).
            _request_birth.pop(request_id, None)
        if debug is not None:
            return debug
    debug = _last_tool_debug_var.get()
    _last_tool_debug_var.set(None)
    return debug


def set_current_user_id(user_id: str) -> None:
    """Store the authenticated user ID in the current coroutine context."""
    _current_user_id_var.set(user_id)


def get_current_user_id() -> Optional[str]:
    """Return the authenticated user ID stored for the current coroutine."""
    return _current_user_id_var.get()


def set_current_patient_id(patient_id: str | None) -> None:
    """Store the current patient ID in the current coroutine context."""
    _current_patient_id_var.set(patient_id)


def get_current_patient_id() -> Optional[str]:
    """Return the current patient ID stored for the current coroutine."""
    return _current_patient_id_var.get()


# ============================================================================
# REF ID allocator — shared counter across all tools in one request.
# Every source (DB drug record, PubMed article, interaction edge, etc.) gets a
# unique REF# so the LLM can cite it inline (e.g., "Warfarin anticoagulates [REF3]").
# ============================================================================

def _next_ref_id() -> str:
    """Return the next REF id (REF1, REF2, ...) for the current request.

    Uses a dedicated monotonic counter per request_id instead of len(store)
    because callers allocate ids before appending the source to the store
    (e.g. in a loop that builds multiple sources in one tool call). Relying on
    len() would hand out the same id to every entry in such a loop.
    """
    rid = _request_id_var.get()
    with _store_lock:
        if rid is not None:
            count = _ref_counter.get(rid, 0) + 1
            _ref_counter[rid] = count
        else:
            # Non-streaming fallback path: also a real monotonic counter so
            # repeated calls don't produce duplicate ids (audit A6).
            count = _legacy_ref_counter_var.get() + 1
            _legacy_ref_counter_var.set(count)
    return f"REF{count}"


def _ref_num(ref_id: str) -> str:
    """Strip the 'REF' prefix so tool outputs show clean numeric citations [3] not [REF3]."""
    import re
    m = re.match(r"REF(\d+)", str(ref_id))
    return m.group(1) if m else str(ref_id)


def _make_drugbank_source(
    tool_name: str,
    drug,
    snippet: str = "",
    extra_metadata: dict | None = None,
) -> dict:
    """
    Build a source dict for a DrugBank record, with a freshly minted REF id.

    Used by every drug tool so the LLM can cite: "Warfarin inhibits VKORC1 [REF1]"
    and the UI can link REF1 → DrugBank record.
    """
    drug_id = getattr(drug, "drug_id", "") or (drug.get("drug_id", "") if isinstance(drug, dict) else "")
    drug_name = getattr(drug, "name", "") or (drug.get("name", "") if isinstance(drug, dict) else "")
    ref_id = _next_ref_id()
    return {
        "ref": ref_id,
        "source": "DrugBank",
        "source_type": "database",
        "tool": tool_name,
        "title": f"DrugBank: {drug_name}",
        "drug_id": drug_id,
        "drug_name": drug_name,
        "url": f"https://go.drugbank.com/drugs/{drug_id}" if drug_id else "",
        "content": snippet[:400] if snippet else f"DrugBank record for {drug_name}",
        "metadata": {
            "database": "DrugBank",
            "drug_id": drug_id,
            "drug_name": drug_name,
            **(extra_metadata or {}),
        },
    }


def _make_interaction_source(
    tool_name: str,
    drug_a: str,
    drug_b: str,
    description: str = "",
    url: str = "",
    extra_metadata: dict | None = None,
) -> dict:
    """Build a source dict for one documented DrugBank interaction record.

    The record carries no severity: DrugBank's interaction table has no
    severity field and no expert has labelled it (see SEVERITY_NOT_RATED).
    """
    ref_id = _next_ref_id()
    return {
        "ref": ref_id,
        "source": "DrugBank Interaction",
        "source_type": "database",
        "tool": tool_name,
        "title": f"Interaction record: {drug_a} ↔ {drug_b} (DrugBank)",
        "url": url,
        "content": description[:400] if description else f"DrugBank interaction record for {drug_a} and {drug_b}",
        "metadata": {
            "database": "DrugBank",
            "drug_a": drug_a,
            "drug_b": drug_b,
            "severity": SEVERITY_NOT_RATED,
            **(extra_metadata or {}),
        },
    }


# ============================================================================
# Status vocabulary shared with the drug service (models.LookupStatus).
# Every drug tool starts its output with "STATUS: <X>" so the model cannot
# confuse a failed or partial lookup with "no interaction".
# ============================================================================

_STATUS_GUIDANCE = {
    "found": "Documented record(s) found. Cite each record you use.",
    "no_record": (
        "The query succeeded and the database holds NO record for the checked "
        "items. This is NOT evidence of safety: say 'no documented record in "
        "DrugBank', never 'safe'."
    ),
    "incomplete": (
        "Only part of the request was checked. Name every unchecked input and "
        "do not generalise the result to it."
    ),
    "unresolved": (
        "No check was performed because the input(s) could not be matched to a "
        "database drug. Ask for the correct name; do not answer from general knowledge."
    ),
    "error": (
        "The lookup FAILED; the result is UNKNOWN. Tell the user the check could "
        "not be completed and suggest retrying. Do NOT state or imply that there "
        "is no interaction or no risk."
    ),
}


def _status_header(status: str) -> str:
    guidance = _STATUS_GUIDANCE.get(status, _STATUS_GUIDANCE["error"])
    return f"STATUS: {status.upper()}\n{guidance}"


def _clip(text: str, limit: int, ref_num: str) -> str:
    """Bound a DrugBank text field sent to the LLM (provider token limits).

    The cut is marked so the model knows the text is partial; the full record
    stays available through the cited DrugBank source.
    """
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return f"{cut} … [truncated; full text in DrugBank record [{ref_num}]]"


# Per-field character budgets for get_drug_info. Every later model call of the
# turn re-sends this output on top of the system prompt and tool schemas
# (~2.7k tokens), and Groq's free tier rejects single requests above its 8k
# tokens-per-minute limit (HTTP 413).
_FIELD_LIMIT_MODERATE = 600
_FIELD_LIMIT_HIGH = 350


_SEVERITY_LINE_LIST = (
    "Severity: not rated — DrugBank provides no severity label for these records "
    "and no expert review exists. Do not assign MAJOR/MODERATE/MINOR yourself."
)

# Interaction records written out for the model per check. Every record is
# still registered as a source (the user sees all of them as source cards);
# the model sees the first ones plus an explicit count of the rest, so a long
# medication list cannot push the request over the provider's per-request
# token limit and nothing is dropped silently.
_MAX_RECORDS_SHOWN = 15


def _interaction_record_lines(interactions, tool_name: str, metadata_for) -> tuple[list[str], list[dict]]:
    """Numbered record lines for the model, plus one source per record."""
    lines = [_SEVERITY_LINE_LIST, ""]
    sources: list[dict] = []
    for i, interaction in enumerate(interactions, 1):
        src = _make_interaction_source(
            tool_name=tool_name,
            drug_a=interaction.drug1_name,
            drug_b=interaction.drug2_name,
            description=interaction.description or "",
            url=interaction.source_url,
            extra_metadata=metadata_for(interaction),
        )
        sources.append(src)
        if i <= _MAX_RECORDS_SHOWN:
            lines.append(
                f"{i}. **{interaction.drug1_name}** + **{interaction.drug2_name}** [{_ref_num(src['ref'])}]"
            )
            lines.append(f"   DrugBank text: {interaction.description}")
    hidden = len(interactions) - _MAX_RECORDS_SHOWN
    if hidden > 0:
        lines.append(
            f"{hidden} more documented record(s) are not shown here (provider size limit); the user "
            f"sees all {len(interactions)} as source cards. Say that the list is longer than shown "
            "and do not describe records you were not shown."
        )
    return lines, sources


# ============================================================================
# Helper: build a safe error message for the LLM
# ============================================================================

def _safe_error_response(action: str, exc: Exception) -> str:
    """
    Return a sanitized, status-tagged error string for the LLM/tool result.

    Audit A10: returning `str(e)` to the LLM can leak DB URLs, file paths,
    SQL fragments, or internal stack details. The caller logs the full
    exception (with traceback); the model only learns that the step failed,
    so it cannot present a failed lookup as a negative finding.
    """
    return (
        f"{_status_header('error')}\n"
        f"Internal error while {action} ({type(exc).__name__}); no data was retrieved."
    )


# ============================================================================
# Helper: detect non-English queries for PubMed tools (audit P10)
# ============================================================================

# PubMed indexes English literature primarily and accepts English MeSH terms.
# We reject queries that look like they're written in another script. The
# previous check only flagged Turkish characters, missing French diacritics,
# Arabic, Cyrillic, etc., AND false-positively rejecting valid English terms
# like "Ménière's disease" because of the bare é.
#
# Strategy:
#   - Accept Latin-1 with diacritics (medical eponyms commonly contain them).
#   - Reject if the query contains any character outside the basic Unicode
#     ranges used by clinical English: ASCII + Latin-1 supplement + a few
#     punctuation marks. CJK / Cyrillic / Arabic / Devanagari ranges trigger
#     a rejection.
#   - Don't enforce ASCII-only — that would block "naïve", "café-au-lait",
#     "Ménière", "Sjögren", etc.

_NON_ENGLISH_BLOCK_RANGES = (
    (0x0400, 0x04FF),   # Cyrillic
    (0x0500, 0x052F),   # Cyrillic Supplement
    (0x0530, 0x058F),   # Armenian
    (0x0590, 0x05FF),   # Hebrew
    (0x0600, 0x06FF),   # Arabic
    (0x0700, 0x074F),   # Syriac
    (0x0900, 0x097F),   # Devanagari
    (0x0980, 0x09FF),   # Bengali
    (0x0E00, 0x0E7F),   # Thai
    (0x3040, 0x309F),   # Hiragana
    (0x30A0, 0x30FF),   # Katakana
    (0x3400, 0x4DBF),   # CJK Extension A
    (0x4E00, 0x9FFF),   # CJK Unified Ideographs
    (0xAC00, 0xD7AF),   # Hangul Syllables
)


def _looks_non_english(query: str) -> bool:
    """Return True if `query` contains characters from non-Latin scripts."""
    for ch in query:
        cp = ord(ch)
        for lo, hi in _NON_ENGLISH_BLOCK_RANGES:
            if lo <= cp <= hi:
                return True
    return False




def _resolve_drug_name_to_id(drug_name: str, semantic_search: bool = False) -> Optional[str]:
    """
    Resolve a drug name (or synonym/brand) to a DrugBank ID using search.
    Returns the best match drug_id or None if not found.
    """
    try:
        request = DrugSearchRequest(
            query=drug_name,
            limit=1,
            min_similarity=0.3,
            include_synonyms=True,
            include_products=True,
            include_brands=True,
            include_semantic_search=semantic_search
        )
        response = drug_service.search_drugs(request)
        
        if response.success and response.results:
            drug_id = response.results[0].drug_id
            logger.info(f"Resolved '{drug_name}' to drug_id: {drug_id}")
            return drug_id
        else:
            logger.warning(f"Could not resolve drug name: {drug_name}")
            return None
    except Exception as e:
        logger.error(f"Error resolving drug name '{drug_name}': {e}")
        return None


def _resolve_drug_names_to_ids(drug_names: list[str], semantic_search: bool = False) -> list[str]:
    """
    Resolve multiple drug names to drug IDs.
    Returns list of resolved drug_ids (skips unresolved names).

    Legacy helper: it cannot tell "not found" from "lookup failed". Tools that
    report clinical results use ``_resolve_drug_names`` instead.
    """
    drug_ids = []
    for name in drug_names:
        drug_id = _resolve_drug_name_to_id(name, semantic_search=semantic_search)
        if drug_id:
            drug_ids.append(drug_id)
    return drug_ids


@dataclass
class _NameResolution:
    """Outcome of matching user-supplied drug names to database drugs."""
    resolved: list = field(default_factory=list)    # dicts: input, drug_id, name, exact, similarity
    unresolved: list = field(default_factory=list)  # names with no matching drug
    failed: list = field(default_factory=list)      # names whose lookup errored

    @property
    def ids(self) -> list[str]:
        return list(dict.fromkeys(r["drug_id"] for r in self.resolved))

    @property
    def partial(self) -> list:
        """Combination-product name matches: only ONE ingredient is represented."""
        return [r for r in self.resolved if r.get("match_type") == "mixture"]

    @property
    def duplicates(self) -> list:
        """Groups of different inputs that resolved to the same drug."""
        groups: dict = {}
        for r in self.resolved:
            groups.setdefault(r["drug_id"], []).append(r)
        return [g for g in groups.values() if len({x["input"].lower() for x in g}) > 1]

    def name_for(self, drug_id: str) -> str:
        for r in self.resolved:
            if r["drug_id"] == drug_id:
                return r["name"]
        return drug_id


def _resolve_drug_names(drug_names: list[str], semantic_search: bool = False) -> _NameResolution:
    """Match names to drugs, keeping unmatched and failed lookups visible."""
    result = _NameResolution()
    seen: set[str] = set()
    for raw in drug_names or []:
        name = (raw or "").strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        try:
            response = drug_service.search_drugs(DrugSearchRequest(
                query=name[:500],
                limit=1,
                min_similarity=0.3,
                include_synonyms=True,
                include_products=True,
                include_brands=True,
                include_semantic_search=semantic_search,
            ))
        except Exception as e:  # pragma: no cover - search_drugs catches its own errors
            logger.error(f"Drug name lookup failed for '{name}': {e}", exc_info=True)
            result.failed.append(name)
            continue
        if not response.success:
            result.failed.append(name)
        elif response.results:
            top = response.results[0]
            score = top.similarity_score
            match_type = top.match_type or (
                "name" if score is not None and score >= 0.999 else "approximate"
            )
            result.resolved.append({
                "input": name,
                "drug_id": top.drug_id,
                "name": top.name,
                # A combination-product (mixture) name maps to ONE ingredient,
                # so it is never reported as an exact match.
                "exact": match_type in ("name", "brand", "synonym"),
                "similarity": score,
                "match_type": match_type,
            })
        else:
            result.unresolved.append(name)
    return result


def _format_resolution(res: _NameResolution) -> list[str]:
    """Human/LLM-readable account of how each input name was matched."""
    lines: list[str] = []
    if res.resolved:
        lines.append("Inputs matched to database drugs:")
        for r in res.resolved:
            if r.get("match_type") == "mixture":
                how = (
                    "COMBINATION-PRODUCT name — only this one ingredient was used; the product's "
                    "other ingredients were NOT checked"
                )
            elif r["exact"]:
                how = "exact name/brand/synonym match"
            else:
                sim = r["similarity"]
                sim_txt = f"{sim:.2f}" if isinstance(sim, (int, float)) else "n/a"
                how = (
                    f"APPROXIMATE match (similarity {sim_txt}) — tell the user which drug "
                    "was used and ask them to confirm it is the intended one"
                )
            lines.append(f'- "{r["input"]}" → {r["name"]} ({r["drug_id"]}) [{how}]')
    if res.unresolved:
        lines.append(
            "Not found in the database (NOT checked): "
            + ", ".join(f'"{n}"' for n in res.unresolved)
        )
    if res.failed:
        lines.append(
            "Name lookup FAILED (database error, NOT checked): "
            + ", ".join(f'"{n}"' for n in res.failed)
        )
    for group in res.duplicates:
        names = ", ".join(f'"{x["input"]}"' for x in group)
        lines.append(
            f"SAME DRUG: {names} all refer to {group[0]['name']} ({group[0]['drug_id']}) "
            "— duplicate therapy (same active ingredient)."
        )
    return lines

# ============================================================================
# TOOL 1: Get Drug Information
# ============================================================================

@tool
def get_drug_info(
    drug_name: Annotated[str, 'Drug name, e.g. Warfarin.'],
    detail: Annotated[
        Literal["low", "moderate", "high"],
        "'low' basic; 'moderate' standard clinical; 'high' comprehensive, adds side effects/toxicity, pharmacokinetics (ADME) and targets/enzymes/carriers (needed for these)."
    ] = "moderate",
    semantic_search: Annotated[bool, 'Semantic name matching; use if the exact drug name is not given.'] = False,
) -> str:
    """
    Get a drug's DrugBank record: what it is/does, indications, mechanism, side effects/toxicity, pharmacokinetics, properties.
    """
    try:
        logger.debug(f"[TOOL] get_drug_info called with drug_name='{drug_name}', detail='{detail}'")
        logger.info(f"get_drug_info: drug_name='{drug_name}', detail='{detail}'")
        
        # Resolve drug name to ID (a failed lookup is not "not found")
        resolution = _resolve_drug_names([drug_name], semantic_search=semantic_search)
        if resolution.failed:
            return "\n".join([_status_header("error"), *_format_resolution(resolution)])
        if not resolution.ids:
            logger.warning(f"[TOOL] Drug not found: {drug_name}")
            return (
                f"{_status_header('unresolved')}\n"
                f'No drug named "{drug_name}" was found in the database. Try a different name or spelling.'
            )
        drug_id = resolution.ids[0]
        logger.debug(f"[TOOL] Resolved '{drug_name}' to drug_id: {drug_id}")

        # Get drug information with specified detail level
        logger.debug(f"[TOOL] Fetching drug information for {drug_id} with detail level: {detail}")
        drug = drug_service.get_drug(drug_id, detail=detail)
        if not drug:
            logger.warning(f"[TOOL] Drug information not available for: {drug_name} ({drug_id})")
            return (
                f"{_status_header('error')}\n"
                f"The record for {resolution.name_for(drug_id)} ({drug_id}) could not be retrieved; no data is available."
            )

        # Build response based on detail level
        logger.debug(f"[TOOL] Building response for {drug.name} with detail level: {detail}")
        parts = [_status_header("found"), *_format_resolution(resolution), "", f"**{drug.name}** ({drug.drug_id})"]

        # Allocate the citation source up-front so it's used regardless of
        # detail level — the system prompt requires every clinical claim to
        # carry a citation, including for low/moderate-detail responses
        # (audit A3). Previously only the "high" branch registered a source.
        source = _make_drugbank_source(
            tool_name="get_drug_info",
            drug=drug,
            snippet=(getattr(drug, "description", None) or "")[:400],
            extra_metadata={"detail_level": detail},
        )
        _store_sources([source], tool_name="get_drug_info")
        ref_num = _ref_num(source["ref"])
        
        # Low detail: DrugDescription (drug_id, name, description)
        if detail == "low":
            if drug.description:
                desc = drug.description[:300]
                if len(drug.description) > 300:
                    desc += "..."
                parts.append(f"\nDescription: {desc}")
            parts.append(
                f"\n[Source [{ref_num}] — DrugBank record for {drug.name} ({drug.drug_id})]"
            )
            return "\n".join(parts)
        
        # Moderate detail: DrugBase (+ drug_type, indication, mechanism, pharmacodynamics, synonyms)
        if detail == "moderate":
            #if hasattr(drug, 'synonyms') and drug.synonyms:
            synonyms = getattr(drug, 'synonyms', None)
            if synonyms:
                parts.append(f"Also known as: {', '.join(synonyms[:5])}")
            
            drug_type = getattr(drug, 'drug_type', None)
            if drug_type:
                parts.append(f"Type: {drug_type}")

            description = getattr(drug, 'description', None)
            if description:
                parts.append(f"\nDescription: {_clip(description, _FIELD_LIMIT_MODERATE, ref_num)}")
            
            indication = getattr(drug, 'indication', None)
            if indication:
                parts.append(f"\nIndication: {_clip(indication, _FIELD_LIMIT_MODERATE, ref_num)}")
            
            mechanism_of_action = getattr(drug, 'mechanism_of_action', None)
            if mechanism_of_action:
                parts.append(f"\nMechanism of Action: {_clip(mechanism_of_action, _FIELD_LIMIT_MODERATE, ref_num)}")
            
            pharmacodynamics = getattr(drug, 'pharmacodynamics', None)
            if pharmacodynamics:
                parts.append(f"\nPharmacodynamics: {_clip(pharmacodynamics, _FIELD_LIMIT_MODERATE, ref_num)}")

            parts.append(
                f"\n[Source [{ref_num}] — DrugBank record for {drug.name} ({drug.drug_id})]"
            )
            return "\n".join(parts)
        
        # High detail: Full Drug model with all relationships
        synonyms = getattr(drug, 'synonyms', None)
        if synonyms:
            parts.append(f"Also known as: {', '.join(synonyms[:5])}")
        
        drug_type = getattr(drug, 'drug_type', None)
        if drug_type:
            parts.append(f"Type: {drug_type}")
        
        groups = getattr(drug, 'groups', None)
        if groups:
            parts.append(f"Status: {', '.join(groups)}")
        
        description = getattr(drug, 'description', None)
        if description:
            parts.append(f"\nDescription: {_clip(description, _FIELD_LIMIT_HIGH, ref_num)}")
        
        indication = getattr(drug, 'indication', None)
        if indication:
            parts.append(f"\nIndication: {_clip(indication, _FIELD_LIMIT_HIGH, ref_num)}")
        
        mechanism_of_action = getattr(drug, 'mechanism_of_action', None)
        if mechanism_of_action:
            parts.append(f"\nMechanism of Action: {_clip(mechanism_of_action, _FIELD_LIMIT_HIGH, ref_num)}")
        
        pharmacodynamics = getattr(drug, 'pharmacodynamics', None)
        if pharmacodynamics:
            parts.append(f"\nPharmacodynamics: {_clip(pharmacodynamics, _FIELD_LIMIT_HIGH, ref_num)}")
        
        toxicity = getattr(drug, 'toxicity', None)
        if toxicity:
            parts.append(f"\nToxicity/Side Effects: {_clip(toxicity, _FIELD_LIMIT_HIGH, ref_num)}")
        
        metabolism = getattr(drug, 'metabolism', None)
        if metabolism:
            parts.append(f"\nMetabolism: {_clip(metabolism, _FIELD_LIMIT_HIGH, ref_num)}")
        
        absorption = getattr(drug, 'absorption', None)
        if absorption:
            parts.append(f"\nAbsorption: {_clip(absorption, _FIELD_LIMIT_HIGH, ref_num)}")
        
        half_life = getattr(drug, 'half_life', None)
        if half_life:
            parts.append(f"\nHalf-life: {_clip(half_life, _FIELD_LIMIT_HIGH, ref_num)}")
        
        protein_binding = getattr(drug, 'protein_binding', None)
        if protein_binding:
            parts.append(f"\nProtein Binding: {_clip(protein_binding, _FIELD_LIMIT_HIGH, ref_num)}")
        
        route_of_elimination = getattr(drug, 'route_of_elimination', None)
        if route_of_elimination:
            parts.append(f"\nRoute of Elimination: {_clip(route_of_elimination, _FIELD_LIMIT_HIGH, ref_num)}")
        
        volume_of_distribution = getattr(drug, 'volume_of_distribution', None)
        if volume_of_distribution:
            parts.append(f"\nVolume of Distribution: {_clip(volume_of_distribution, _FIELD_LIMIT_HIGH, ref_num)}")
        
        clearance = getattr(drug, 'clearance', None)
        if clearance:
            parts.append(f"\nClearance: {_clip(clearance, _FIELD_LIMIT_HIGH, ref_num)}")
        
        categories = getattr(drug, 'categories', None)
        if categories:
            parts.append(f"\nCategories: {', '.join(categories[:10])}")
        
        food_interactions = getattr(drug, 'food_interactions', None)
        if food_interactions:
            parts.append(f"\nFood Interactions ({len(food_interactions)}): {'; '.join(food_interactions[:5])}")
        
        targets = getattr(drug, 'targets', None)
        if targets:
            parts.append(f"\nTargets ({len(targets)}): {', '.join([t.get('name', 'Unknown') for t in targets[:5]])}") # type: ignore
        
        enzymes = getattr(drug, 'enzymes', None)
        if enzymes:
            parts.append(f"\nEnzymes ({len(enzymes)}): {', '.join([e.get('name', 'Unknown') for e in enzymes[:5]])}") # type: ignore
        
        carriers = getattr(drug, 'carriers', None)
        if carriers:
            parts.append(f"\nCarriers ({len(carriers)}): {', '.join([c.get('name', 'Unknown') for c in carriers[:5]])}") # type: ignore
        
        transporters = getattr(drug, 'transporters', None)
        if transporters:
            parts.append(f"\nTransporters ({len(transporters)}): {', '.join([t.get('name', 'Unknown') for t in transporters[:5]])}") # type: ignore
        
        # Source already registered above (for all detail levels — audit A3).
        parts.append(
            f"\n[Source [{ref_num}] — DrugBank record for {drug.name} ({drug.drug_id})]"
        )
        return "\n".join(parts)
        
    except Exception as e:
        logger.error(f"Error in get_drug_info for '{drug_name}': {e}", exc_info=True)
        return _safe_error_response("retrieving drug information", e)


# ============================================================================
# TOOL 2: Check Drug Interactions
# ============================================================================

@tool
def check_drug_interactions(
    drug_names: Annotated[list[str], '2+ drug names.'],
    semantic_search: Annotated[bool, 'Semantic name matching; use if the exact drug name is not given.'] = False
) -> str:
    """
    Check DrugBank for documented interaction records between 2+ drugs (drug-drug interactions; whether they can be taken together).
    """
    try:
        logger.info(f"check_drug_interactions: drug_names={drug_names}")

        if len(drug_names) < 2:
            return (
                f"{_status_header('unresolved')}\n"
                "At least 2 drugs are needed to check for interactions."
            )

        resolution = _resolve_drug_names(drug_names, semantic_search=semantic_search)
        resolution_lines = _format_resolution(resolution)
        if resolution.failed:
            return "\n".join([_status_header("error"), *resolution_lines])

        ids = resolution.ids
        if len(ids) < 2:
            if resolution.duplicates:
                group = resolution.duplicates[0]
                src = _make_drugbank_source(
                    tool_name="check_drug_interactions",
                    drug={"drug_id": group[0]["drug_id"], "name": group[0]["name"]},
                    snippet=f"Names resolved to the same DrugBank record: {', '.join(x['input'] for x in group)}",
                )
                _store_sources([src], tool_name="check_drug_interactions")
                return "\n".join([
                    _status_header("found"),
                    *resolution_lines,
                    f"The inputs are the same drug [{_ref_num(src['ref'])}]: a drug–drug interaction check "
                    "does not apply. Taking them together means taking the same active ingredient twice "
                    "(duplicate therapy).",
                ])
            return "\n".join([
                _status_header("unresolved"),
                *resolution_lines,
                "No interaction check was performed (fewer than 2 drugs could be matched).",
            ])

        # The service checks at most 10 drugs; extra ones are reported, not hidden.
        to_check, not_checked = ids[:10], ids[10:]
        response = drug_service.check_drug_interactions(CheckDrugInteractionRequest(drug_ids=to_check))
        logger.debug(f"[TOOL] Interaction check status={response.status}, records={response.count}")

        if response.status == "error":
            return "\n".join([_status_header("error"), *resolution_lines])

        status = response.status
        unchecked_names = (
            list(resolution.unresolved)
            + [resolution.name_for(d) for d in not_checked]
            + [resolution.name_for(d) for d in response.unresolved_drug_ids]
        )
        if (unchecked_names or resolution.partial) and status in ("found", "no_record"):
            status = "incomplete"

        parts = [_status_header(status), *resolution_lines]
        if not_checked:
            parts.append(
                "Only the first 10 matched drugs were checked; NOT checked: "
                + ", ".join(resolution.name_for(d) for d in not_checked)
            )
        # Coverage against everything the user asked about (unmatched inputs
        # included), not only the ids that reached the database query.
        requested = len(ids) + len(resolution.unresolved)
        parts.append(
            f"Pairs checked: {response.pairs_checked} of {requested * (requested - 1) // 2} requested."
        )

        interaction_sources: list = []
        if response.pairs_checked == 0:
            # Nothing was actually checked (e.g. the ids vanished between
            # name resolution and the lookup): never phrase this as "no record".
            parts.append("No interaction check was performed.")
            return "\n".join(parts)
        if response.interactions:
            parts.append(f"\nDocumented DrugBank interaction record(s): {response.count}")
            record_lines, record_sources = _interaction_record_lines(
                response.interactions,
                tool_name="check_drug_interactions",
                metadata_for=lambda it: {"drug1_id": it.drug1_id, "drug2_id": it.drug2_id},
            )
            interaction_sources.extend(record_sources)
            parts.extend(record_lines)
        else:
            checked = ", ".join(d.name for d in response.checked_drugs)
            src = {
                "ref": _next_ref_id(),
                "source": "DrugBank Interaction",
                "source_type": "database",
                "tool": "check_drug_interactions",
                "title": f"DrugBank interaction table: no record for {checked}",
                "url": drug_service.drugbank_url(response.checked_drugs[0].drug_id) if response.checked_drugs else "",
                "content": (
                    f"No DrugBank interaction record was found for the checked pairs among: {checked}. "
                    "Absence of a record is not evidence of safety."
                ),
                "metadata": {"database": "DrugBank", "finding": "no_record", "checked": checked},
            }
            interaction_sources.append(src)
            parts.append(
                f"\nNo DrugBank interaction record for the checked pairs [{_ref_num(src['ref'])}]. "
                "This is NOT evidence that the combination is safe."
            )

        if unchecked_names:
            parts.append(
                "\nPairs involving these inputs were NOT checked: " + ", ".join(dict.fromkeys(unchecked_names))
            )

        _store_sources(interaction_sources, tool_name="check_drug_interactions")
        shown_sources = interaction_sources[:_MAX_RECORDS_SHOWN]
        parts.append(
            f"\n[Sources: {', '.join('[' + _ref_num(s['ref']) + ']' for s in shown_sources)} — DrugBank interaction table]"
        )
        return "\n".join(parts)

    except Exception as e:
        logger.error(f"Error in check_drug_interactions: {e}", exc_info=True)
        return _safe_error_response("checking drug interactions", e)


# ============================================================================
# TOOL 3: Check Drug-Food Interactions
# ============================================================================

@tool
def check_drug_food_interaction(
    drug_name: Annotated[str, 'Drug name.'],
    food_items: Annotated[Optional[list[str]], 'Optional foods to look for; empty returns all food interactions.'] = None,
    semantic_search: Annotated[bool, 'Semantic name matching; use if the exact drug name is not given.'] = False
) -> str:
    """
    Get a drug's DrugBank food interactions and dietary restrictions (what to eat or avoid; with or without food).
    """
    try:
        # `food_items` is None by default to avoid the mutable-default-argument
        # antipattern (audit A12). Normalise to an empty list here.
        if food_items is None:
            food_items = []
        logger.info(f"check_drug_food_interaction: drug_name='{drug_name}', food_items={food_items}")

        resolution = _resolve_drug_names([drug_name], semantic_search=semantic_search)
        resolution_lines = _format_resolution(resolution)
        if resolution.failed:
            return "\n".join([_status_header("error"), *resolution_lines])
        if not resolution.ids:
            return (
                f"{_status_header('unresolved')}\n"
                f'No drug named "{drug_name}" was found in the database. Try a different name or spelling.'
            )
        drug_id = resolution.ids[0]

        result = drug_service.lookup_drug_food_interactions(drug_id)
        if result.status in ("error", "unresolved"):
            return "\n".join([_status_header(result.status), *resolution_lines])

        name = result.drug.name if result.drug else resolution.name_for(drug_id)
        interactions = result.interactions
        status = result.status
        if resolution.partial and status in ("found", "no_record"):
            status = "incomplete"
        ref_id = _next_ref_id()
        src = {
            "ref": ref_id,
            "source": "DrugBank",
            "source_type": "database",
            "tool": "check_drug_food_interaction",
            "title": f"DrugBank food interactions for {name}",
            "drug_id": drug_id,
            "drug_name": name,
            "url": result.source_url,
            "content": (
                "; ".join(i.interaction for i in interactions[:3])[:400]
                if interactions
                else f"DrugBank lists no food-interaction record for {name}."
            ),
            "metadata": {
                "database": "DrugBank",
                "drug_id": drug_id,
                "drug_name": name,
                "food_items_checked": food_items,
                "interactions_found": len(interactions),
                "finding": result.status,
            },
        }
        _store_sources([src], tool_name="check_drug_food_interaction")

        parts = [_status_header(status), *resolution_lines, ""]
        if not interactions:
            parts.append(
                f"DrugBank lists no food-interaction record for {name} [{_ref_num(ref_id)}]. "
                "This is NOT evidence that there are no food interactions."
            )
            return "\n".join(parts)

        parts.append(f"DrugBank food-interaction records for **{name}** ({len(interactions)}) [{_ref_num(ref_id)}]:\n")
        mentioned: set[str] = set()
        for i, interaction in enumerate(interactions, 1):
            interaction_text = interaction.interaction
            hits = [f for f in food_items if f and f.lower() in interaction_text.lower()]
            mentioned.update(h.lower() for h in hits)
            if hits:
                parts.append(f"{i}. ⚠️ **{interaction_text}** (mentions: {', '.join(hits)})")
            else:
                parts.append(f"{i}. {interaction_text}")

        not_mentioned = [f for f in food_items if f and f.lower() not in mentioned]
        if not_mentioned:
            parts.append(
                "\nNo record mentions: " + ", ".join(not_mentioned)
                + ". Absence of a mention is NOT evidence that the food is safe with this drug."
            )
        parts.append(f"\n[Source [{_ref_num(ref_id)}] — DrugBank food-interaction table for {name}]")
        return "\n".join(parts)
        
    except Exception as e:
        logger.error(f"Error in check_drug_food_interaction for '{drug_name}': {e}", exc_info=True)
        return _safe_error_response("checking food interactions", e)


# ============================================================================
# TOOL 4: Search Drugs by Indication
# ============================================================================

@tool
def search_drugs_by_indication(
    condition: Annotated[str, 'Condition, e.g. diabetes, hypertension.'],
    semantic_search: Annotated[bool, "True for conceptual wording, e.g. 'high blood pressure' -> hypertension."] = False,
) -> str:
    """
    Find drugs that treat a medical condition (treatment options). Call first for any treatment question.
    """
    try:
        logger.info(f"search_drugs_by_indication: condition='{condition}', semantic_search={semantic_search}")
        
        request = DrugSearchByIndicationRequest(
            indication=condition, 
            limit=20,
            include_semantic_search=semantic_search
        )
        response = drug_service.search_drugs_by_indication(request)

        if not response.success:
            return f"{_status_header('error')}\nThe indication search failed; no drugs were retrieved."
        if response.count == 0:
            return (
                f"{_status_header('no_record')}\n"
                f"No drugs found for indication '{condition}'. "
                "Try different keywords or check the spelling."
            )

        parts = [_status_header("found"), f"Found {response.count} drug(s) for **{condition}**:\n"]
        
        indication_sources: list = []
        for i, drug in enumerate(response.results[:10], 1):
            src = _make_drugbank_source(
                tool_name="search_drugs_by_indication",
                drug=drug,
                snippet=(drug.description or "")[:300],
                extra_metadata={"indication_query": condition},
            )
            indication_sources.append(src)
            parts.append(f"{i}. **{drug.name}** ({drug.drug_id}) [{_ref_num(src['ref'])}]")
            if drug.description:
                desc_snippet = drug.description[:150]
                if len(drug.description) > 150:
                    desc_snippet += "..."
                parts.append(f"   {desc_snippet}")
            parts.append("")
        
        if response.count > 10:
            parts.append(f"... and {response.count - 10} more drugs.")
        
        parts.append("Consult your healthcare provider before starting any medication.")
        
        if indication_sources:
            _store_sources(indication_sources, tool_name="search_drugs_by_indication")
            parts.append(f"\n[Sources: DrugBank indication-to-drug mapping, {len(indication_sources)} drugs cited]")
        
        return "\n".join(parts)
        
    except Exception as e:
        logger.error(f"Error in search_drugs_by_indication for '{condition}': {e}", exc_info=True)
        return _safe_error_response("searching drugs by indication", e)


# ============================================================================
# TOOL 5: Search Drugs by Category
# ============================================================================

@tool
def search_drugs_by_category(
    category: Annotated[str, 'Category, e.g. antibiotic, antidepressant.'],
    semantic_search: Annotated[bool, 'True to match related categories conceptually.'] = False,
) -> str:
    """
    List drugs in a therapeutic category or class (types of medications).
    """
    try:
        logger.info(f"search_drugs_by_category: category='{category}', semantic_search={semantic_search}")
        
        request = DrugSearchByCategoryRequest(
            category=category, 
            limit=20,
            include_semantic_search=semantic_search
        )
        response = drug_service.search_drugs_by_category(request)

        if not response.success:
            return f"{_status_header('error')}\nThe category search failed; no drugs were retrieved."
        if response.count == 0:
            return (
                f"{_status_header('no_record')}\n"
                f"No drugs found in category '{category}'. "
                "Try different keywords like 'antibiotic', 'antidepressant', or 'analgesic'."
            )

        parts = [_status_header("found"), f"Found {response.count} drug(s) in category **{category}**:\n"]
        
        category_sources: list = []
        for i, drug in enumerate(response.results[:10], 1):
            src = _make_drugbank_source(
                tool_name="search_drugs_by_category",
                drug=drug,
                snippet=(drug.description or "")[:300],
                extra_metadata={"category_query": category},
            )
            category_sources.append(src)
            parts.append(f"{i}. **{drug.name}** ({drug.drug_id}) [{_ref_num(src['ref'])}]")
            if drug.description:
                desc_snippet = drug.description[:150]
                if len(drug.description) > 150:
                    desc_snippet += "..."
                parts.append(f"   {desc_snippet}")
            parts.append("")
        
        if response.count > 10:
            parts.append(f"... and {response.count - 10} more drugs.")
        
        if category_sources:
            _store_sources(category_sources, tool_name="search_drugs_by_category")
            parts.append(f"\n[Sources: DrugBank category-to-drug mapping, {len(category_sources)} drugs cited]")
        
        return "\n".join(parts)
        
    except Exception as e:
        logger.error(f"Error in search_drugs_by_category for '{category}': {e}", exc_info=True)
        return _safe_error_response("searching drugs by category", e)


# ============================================================================
# TOOL 6: Recommend Alternative Drug
# ============================================================================

@tool
def recommend_alternative_drug(
    current_drug_names: Annotated[list[str], "Patient's other current medications."],
    for_drug_name: Annotated[str, 'Drug to replace.'],
    semantic_search: Annotated[bool, 'Semantic name matching; use if the exact drug name is not given.'] = False,
) -> str:
    """
    Only when the user explicitly asks for alternatives: lists UNVERIFIED replacement candidates that share a DrugBank category with the drug to replace and have no interaction record with the current drugs. Equivalence, indication, contraindications, allergies, conditions and dosing are NOT checked; never present them as safe.
    """
    try:
        logger.info(f"recommend_alternative_drug: current_drugs={current_drug_names}, for_drug='{for_drug_name}', semantic_search={semantic_search}")

        target_res = _resolve_drug_names([for_drug_name], semantic_search=semantic_search)
        current_res = _resolve_drug_names(current_drug_names or [], semantic_search=semantic_search)
        resolution_lines = _format_resolution(target_res) + _format_resolution(current_res)
        if target_res.failed or current_res.failed:
            return "\n".join([_status_header("error"), *resolution_lines])
        if not target_res.ids:
            return "\n".join([
                _status_header("unresolved"),
                f'No drug named "{for_drug_name}" was found in the database; no candidates were searched.',
            ])
        for_drug_id = target_res.ids[0]

        result = drug_service.find_alternative_candidates(current_res.ids, for_drug_id)
        if result.status in ("error", "unresolved"):
            return "\n".join([_status_header(result.status), *resolution_lines])

        status = result.status
        if current_res.unresolved and status in ("found", "no_record"):
            status = "incomplete"
        alternatives = result.candidates

        parts = [_status_header(status), *resolution_lines, "", f"NOTE: {result.note}"]
        if result.excluded_with_interaction_record:
            parts.append(
                f"{result.excluded_with_interaction_record} same-category drug(s) were excluded because "
                "DrugBank records an interaction with a checked medication."
            )
        if current_res.unresolved:
            parts.append(
                "Candidates were NOT checked against: " + ", ".join(f'"{n}"' for n in current_res.unresolved)
            )
        if not alternatives:
            parts.append(
                f"\nNo unverified candidate was found for {target_res.name_for(for_drug_id)} with the current method."
            )
            return "\n".join(parts)

        parts.append(f"\nUnverified candidates for **{target_res.name_for(for_drug_id)}** ({len(alternatives)}):\n")

        alt_sources: list = []
        for i, alt in enumerate(alternatives, 1):
            ref_id = _next_ref_id()
            src = {
                "ref": ref_id,
                "source": "DrugBank",
                "source_type": "database",
                "tool": "recommend_alternative_drug",
                "title": f"Unverified candidate: {alt.new_drug_name} (instead of {alt.old_drug_name})",
                "drug_id": alt.new_drug_id,
                "drug_name": alt.new_drug_name,
                "url": drug_service.drugbank_url(alt.new_drug_id),
                "content": (alt.reason or "")[:400],
                "metadata": {
                    "database": "DrugBank",
                    "replacing": alt.old_drug_name,
                    "replacing_drug_id": for_drug_id,
                    "new_drug_id": alt.new_drug_id,
                    "new_drug_name": alt.new_drug_name,
                    "reason": alt.reason,
                    "concurrent_drugs": current_drug_names,
                    "verified": False,
                },
            }
            alt_sources.append(src)
            parts.append(f"{i}. {alt.new_drug_name} ({alt.new_drug_id}) [{_ref_num(ref_id)}]")
            parts.append(f"   Basis: {alt.reason}")
            parts.append("")

        parts.append(
            "Present these only as unverified candidates for clinician review; "
            "do not call them safe or recommend switching."
        )
        _store_sources(alt_sources, tool_name="recommend_alternative_drug")
        parts.append(f"\n[Sources: DrugBank category and interaction tables, {len(alt_sources)} candidates cited]")
        return "\n".join(parts)
        
    except Exception as e:
        logger.error(f"Error in recommend_alternative_drug: {e}", exc_info=True)
        return _safe_error_response("finding alternative drugs", e)


# ============================================================================
# TOOL 7: Check for Overdose Risk (Same Active Ingredient)
# ============================================================================

@tool
def check_for_overdose_interaction(
    drug_names: Annotated[list[str], '2+ drug names.'],
    semantic_search: Annotated[bool, 'Semantic name matching; use if the exact drug name is not given.'] = False
) -> str:
    """
    Check whether 2+ drugs share an active ingredient (risk of taking them together, duplicate therapy, overdose risk), e.g. Tylenol + paracetamol (both acetaminophen).
    """
    try:
        logger.debug(f"[TOOL] check_for_overdose_interaction called with {len(drug_names)} drugs: {drug_names}")
        logger.info(f"check_for_overdose_interaction: drug_names={drug_names}")
        
        if len(drug_names) < 2:
            return f"{_status_header('unresolved')}\nAt least 2 drugs are needed to check for a shared active ingredient."

        resolution = _resolve_drug_names(drug_names, semantic_search=semantic_search)
        resolution_lines = _format_resolution(resolution)
        if resolution.failed:
            return "\n".join([_status_header("error"), *resolution_lines])
        drug_ids = resolution.ids
        if len(drug_ids) < 2 and not resolution.duplicates:
            return "\n".join([
                _status_header("unresolved"),
                *resolution_lines,
                "No shared-ingredient check was performed (fewer than 2 drugs could be matched).",
            ])

        # Keep repeated ids: two names for the same drug are the clearest
        # duplicate-ingredient case and the service reports them as a risk.
        response = drug_service.check_overdose_risk([r["drug_id"] for r in resolution.resolved])
        if response.status in ("error", "unresolved"):
            return "\n".join([_status_header(response.status), *resolution_lines])

        status = response.status
        if (resolution.unresolved or resolution.partial) and status in ("found", "no_record"):
            status = "incomplete"

        if not response.has_risk:
            return "\n".join([
                _status_header(status),
                *resolution_lines,
                "No shared active ingredient was found in DrugBank names, synonyms or mixture "
                "ingredient lists for the matched drugs. This does not rule out duplicate therapy "
                "(e.g. same class, different ingredient).",
            ])

        # Build response
        parts = [
            _status_header(status),
            *resolution_lines,
            "",
            "⚠️ Shared active ingredient found (DrugBank name/synonym/mixture overlap; not a severity rating):\n",
        ]
        parts.append(f"Found {len(response.risks)} potential overdose risk(s):\n")
        
        overdose_sources: list = []
        for i, risk in enumerate(response.risks, 1):
            ref_id = _next_ref_id()
            src = {
                "ref": ref_id,
                "source": "DrugBank",
                "source_type": "database",
                "tool": "check_for_overdose_interaction",
                "title": f"Shared ingredient: {risk.drug1_name} ↔ {risk.drug2_name}",
                "content": (risk.reason or "")[:400],
                "metadata": {
                    "database": "DrugBank",
                    "drug1_name": risk.drug1_name,
                    "drug2_name": risk.drug2_name,
                    "shared_ingredients": list(risk.shared_ingredients or []),
                    "risk_type": "duplicate_active_ingredient",
                },
            }
            overdose_sources.append(src)
            parts.append(f"{i}. **{risk.drug1_name}** and **{risk.drug2_name}** [{_ref_num(ref_id)}]")
            parts.append(f"   Reason: {risk.reason}")
            if risk.shared_ingredients:
                parts.append(f"   Shared ingredients: {', '.join(risk.shared_ingredients)}")
            parts.append("")
        
        parts.append(
            "Taking these together means taking the same active ingredient more than once "
            "(duplicate therapy); the clinician should review the combined dose."
        )
        
        if overdose_sources:
            _store_sources(overdose_sources, tool_name="check_for_overdose_interaction")
            parts.append(f"\n[Sources: DrugBank active-ingredient table, {len(overdose_sources)} risks cited]")
        
        return "\n".join(parts)
        
    except Exception as e:
        logger.error(f"Error in check_for_overdose_interaction: {e}", exc_info=True)
        return _safe_error_response("checking overdose risk", e)


# ============================================================================
# TOOL 8: Analyze Patient Medications
# ============================================================================

@tool
def analyze_patient_medications(
    additional_drugs: Annotated[Optional[list[str]], "Additional drugs to check with the patient's current medications; [] if none."] = None,
    semantic_search: Annotated[bool, 'Semantic name matching; use if the exact drug name is not given.'] = False,
) -> str:
    """
    Active patient only: checks the patient's recorded medications (read automatically) plus additional_drugs for documented DrugBank interaction records, without severity rating or automatic alternatives; unmatched medications are listed as NOT checked. With an active patient, call it whenever drugs are mentioned or the user asks to analyze, review or add medications.
    """
    try:
        # Normalise mutable default to an empty list (audit A12).
        if additional_drugs is None:
            additional_drugs = []
        # Get patient ID from context
        patient_id = get_current_patient_id()
        if not patient_id:
            return (
                f"{_status_header('unresolved')}\n"
                "No patient context is available (no patient selected, or no access to it); nothing was checked."
            )
        
        logger.info(f"analyze_patient_medications: patient_id='{patient_id}', additional_drugs={additional_drugs}, semantic_search={semantic_search}")

        resolution = _resolve_drug_names(additional_drugs, semantic_search=semantic_search)
        resolution_lines = _format_resolution(resolution)
        if resolution.failed:
            return "\n".join([_status_header("error"), *resolution_lines])

        request = AnalyzePatientRequest(
            patient_id=patient_id,
            additional_drug_ids=resolution.ids,
        )
        response = drug_service.analyze_patient(request)
        if response.status == "error":
            return "\n".join([_status_header("error"), *resolution_lines])

        status = response.status
        not_checked = list(resolution.unresolved) + list(response.unresolved_medications)
        combination = resolution.partial or [m for m in response.medication_matches if m.match_type == "mixture"]
        if (not_checked or response.not_checked_over_limit or combination) and status in ("found", "no_record"):
            status = "incomplete"

        parts = [
            _status_header(status),
            *resolution_lines,
            "",
            f"**Medication interaction check for patient {response.patient_id}**\n",
        ]
        # How the recorded medication names were matched (approximate and
        # combination-product matches must be confirmed by the clinician).
        for m in response.medication_matches:
            if m.match_type == "mixture":
                parts.append(
                    f'- Recorded "{m.input}" → {m.name} ({m.drug_id}) [COMBINATION-PRODUCT name — only this '
                    "ingredient was checked]"
                )
            elif m.match_type not in ("name", "brand", "synonym"):
                sim = f"{m.similarity:.2f}" if isinstance(m.similarity, (int, float)) else "n/a"
                parts.append(
                    f'- Recorded "{m.input}" → {m.name} ({m.drug_id}) [APPROXIMATE match, similarity {sim} — '
                    "confirm with the user]"
                )
        recorded_ids = {m.drug_id: m for m in response.medication_matches}
        for r in resolution.resolved:
            if r["drug_id"] in recorded_ids:
                parts.append(
                    f'- "{r["input"]}" is the same drug as the recorded medication '
                    f'"{recorded_ids[r["drug_id"]].input}" ({r["name"]}) — duplicate therapy.'
                )
        if not_checked:
            parts.append(
                "Medications NOT checked (no matching database drug): "
                + ", ".join(f'"{n}"' for n in dict.fromkeys(not_checked))
            )
        if response.not_checked_over_limit:
            parts.append(
                "NOT checked (one check covers at most 10 drugs): "
                + ", ".join(d.name for d in response.not_checked_over_limit)
            )
        patient_sources: list = []

        if response.current_drugs:
            parts.append(f"Current Medications ({len(response.current_drugs)}):")
            for drug in response.current_drugs:
                src = _make_drugbank_source(
                    tool_name="analyze_patient_medications",
                    drug=drug,
                    snippet=f"Currently prescribed to patient {response.patient_id}",
                    extra_metadata={"role": "current_medication", "patient_id": response.patient_id},
                )
                patient_sources.append(src)
                parts.append(f"  - {drug.name} ({drug.drug_id}) [{_ref_num(src['ref'])}]")
            parts.append("")
        
        if response.status == "unresolved":
            if response.error is not None:
                parts.append(f"{response.error.message} Nothing was checked.")
            else:
                parts.append(
                    "An interaction check needs at least two medications matched to the database; "
                    "fewer were available, so no check was performed."
                )
        elif response.count == 0:
            parts.append(
                f"No DrugBank interaction record among the checked medications "
                f"({response.pairs_checked} pair(s) checked). This is NOT evidence of safety."
            )
        else:
            parts.append(
                f"Documented DrugBank interaction record(s): {response.count} "
                f"({response.pairs_checked} pair(s) checked)\n"
            )
            record_lines, record_sources = _interaction_record_lines(
                response.interactions,
                tool_name="analyze_patient_medications",
                metadata_for=lambda _it: {"patient_id": response.patient_id},
            )
            patient_sources.extend(record_sources)
            parts.extend(record_lines)

        parts.append(f"\nAlternatives: {response.alternatives_note}")

        if patient_sources:
            _store_sources(patient_sources, tool_name="analyze_patient_medications")
            parts.append(
                f"\n[Sources: DrugBank — {len(patient_sources)} records cited. "
                f"Patient record from MedicaLLM database (patient_id={response.patient_id}).]"
            )
        
        return "\n".join(parts)
        
    except Exception as e:
        logger.error(f"Error in analyze_patient_medications: {e}", exc_info=True)
        return _safe_error_response("analyzing patient medications", e)


# ============================================================================
# PubMed output size (provider token budget)
# ============================================================================
# Every later model call of the turn re-sends this output, and Groq's free
# tier allows 8,000 tokens per request and per minute. Full abstracts plus
# full-text sections for 10 articles alone exceeded that, so each article is
# shown compactly: key metadata, one quality line and the abstract's
# beginning. The full abstract, open-access full text and detailed metrics
# stay in the article's source entry (the source card the user sees), and the
# text says so.
_PUBMED_DEFAULT_ARTICLES = 5
_PUBMED_MAX_ARTICLES = 10
_PUBMED_ABSTRACT_CHARS = 900

# How to synthesise PubMed results. These rules used to be in the system
# prompt, sent with every model call; they only matter once articles are in
# front of the model, so they travel with the results.
_PUBMED_USAGE_RULES = (
    "HOW TO USE THESE RESULTS:",
    "- Cite only articles listed here, inline as [N]; cite only those that directly address the "
    "question, and no more articles than the user asked for (choose the most relevant).",
    "- Keep therapy subtypes, populations and follow-up durations apart (e.g. estrogen-only vs "
    "combined HRT; family vs personal history) and state which one each finding refers to; say "
    "when an article's population differs from the user's subgroup, and do not apply "
    "general-population figures to a subgroup.",
    "- Articles marked \u26a0 LOW RELEVANCE are tangential: no strong claims from them; at most "
    "mention the adjacent finding with an explicit caveat.",
    "- Present conflicting findings side by side with their own citations; do not merge them "
    "into one conclusion.",
    "- Near-duplicates (same or overlapping author group; same journal and topic in consecutive "
    "years; the same study population with a minor update): cite only the newest or most "
    "comprehensive one, do not cite back-to-back meta-analyses of the same outcome, prefer "
    "articles with a different angle (mechanism, subgroup analyses, real-world "
    "pharmacovigilance, guidelines, the subgroup sub-query), and say when the evidence is "
    "concentrated in one group.",
    "- End with a short 'Limitations' note on what these articles do not cover.",
)


def _pubmed_header(title: str, requested: int, shown_cap: int) -> list[str]:
    lines = [title, *_PUBMED_USAGE_RULES]
    if requested > shown_cap:
        lines.append(
            f"NOTE: {requested} articles were requested; at most {shown_cap} are retrieved per "
            "search to stay within the language model provider's limits. Tell the user."
        )
    lines.append("")
    return lines


def _pubmed_article_lines(article, ref_num: str, warnings: list) -> list[str]:
    """Compact LLM-facing block for one article (details stay in its source)."""
    lines = [f"[Article {ref_num} \u2014 citation tag [{ref_num}]]", f"Title: {article.title}"]
    meta = []
    if article.journal:
        meta.append(f"Journal: {article.journal}")
    if article.publication_date:
        meta.append(f"Published: {article.publication_date}")
    if article.pmid:
        meta.append(f"PMID: {article.pmid}")
    if meta:
        lines.append(" | ".join(meta))
    breakdown = article.confidence_breakdown or {}
    scores = ", ".join(
        f"{label} {breakdown.get(key, 0)}"
        for key, label in (
            ("citations", "citations"), ("fwci", "FWCI"), ("journal_quality", "journal"),
            ("recency", "recency"), ("evidence_level", "evidence"), ("relevance", "relevance"),
        )
    )
    study = ", ".join(article.publication_types) if article.publication_types else "Unknown"
    lines.append(f"Study type: {study} | Confidence: {article.confidence_score}/100 ({scores})")
    if warnings:
        lines.append("WARNINGS: " + "; ".join(warnings))
    abstract = article.abstract or ""
    if len(abstract) > _PUBMED_ABSTRACT_CHARS:
        cut = abstract[:_PUBMED_ABSTRACT_CHARS].rsplit(" ", 1)[0].rstrip()
        abstract = f"{cut} \u2026 [abstract shortened; full abstract in source [{ref_num}]]"
    lines.append(f"Abstract: {abstract}" if abstract else "Abstract: (none)")
    if article.full_text_available and article.full_text_sections:
        lines.append(
            f"[Open-access full text (Europe PMC) is attached to source [{ref_num}]; "
            "not included here.]"
        )
    lines.append("")
    return lines


@tool
def search_pubmed(
    query: Annotated[
        str,
        "Specific query, MUST be in English (e.g. 'heart failure', not a Turkish term); MeSH terms when possible; AND/OR for precision.",
    ],
    num_articles: Annotated[
        int, "Articles to retrieve: the user's number if given, else the default 5 (never ask); max 10."
    ] = _PUBMED_DEFAULT_ARTICLES,
) -> str:
    """
    Search PubMed for published research on one well-defined topic (studies, clinical trials, evidence, what the research says).
    """
    # Validate and cap num_articles (see _PUBMED_MAX_ARTICLES)
    requested_articles = int(num_articles)
    num_articles = max(1, min(requested_articles, _PUBMED_MAX_ARTICLES))
    logger.debug(f"[TOOL] search_pubmed called with query='{query}', num_articles={num_articles}")

    # Reject queries written in non-Latin scripts (audit P10). Latin-1
    # diacritics are accepted so legitimate eponyms like "Ménière's disease"
    # or "Sjögren's syndrome" are not rejected.
    if _looks_non_english(query):
        logger.warning(f"[TOOL] Non-English query rejected: {query}")
        return (
            "ERROR: PubMed query must be written in English (Latin script). "
            "Please rephrase your search in English using medical terminology."
        )

    debug_info = {
        "cache_hit": False,
        "articles_fetched": 0,
        "num_articles_requested": num_articles,
    }

    try:
        logger.info(f"PubMed search for: {query}")
        logger.debug(f"[TOOL] Calling pubmed_service.search_pubmed with max_results={num_articles}")

        # Use new PubMed service that returns PubMedSearchResult.
        # We fetch a small over-shoot (+5 or 1.5x, whichever is larger, capped
        # at 20) so the relevance gate has a buffer to discard low-quality
        # candidates. The previous `max(num_articles, 15)` always fetched 15
        # even when the user only wanted 3 (audit P1).
        fetch_count = min(20, max(num_articles + 5, int(num_articles * 1.5)))
        # `min_confidence` comes from settings so the tool, the REST endpoint,
        # and the service share a single tunable value (audit P3).
        result: PubMedSearchResult = pubmed_service.search_pubmed(
            query=query,
            max_results=fetch_count,
            min_confidence=settings.pubmed_min_confidence,
        )
        
        logger.debug(f"[TOOL] PubMed search completed: {len(result.articles)} articles, search_time={result.search_time_ms}ms")
        
        debug_info["articles_fetched"] = len(result.articles)
        debug_info["avg_confidence"] = result.avg_confidence
        debug_info["filtered_count"] = result.filtered_count
        debug_info["search_time_ms"] = result.search_time_ms

        if not result.articles:
            logger.warning(f"[TOOL] No PubMed articles found for query: {query}")
            _store_sources(None, tool_name="search_pubmed")
            _store_debug(debug_info)
            return "No PubMed articles found for your query. Try different or broader search terms."

        # Hard relevance gate: drop articles whose relevance_score < 0.45
        # (relevance_score is stored as 0-1 float derived from the 0-100 breakdown)
        MIN_RELEVANCE = 0.45
        high_relevance = [a for a in result.articles if a.relevance_score >= MIN_RELEVANCE]
        if not high_relevance:
            # Fall back to top article by confidence when nothing clears the gate
            high_relevance = result.articles[:1]
            logger.warning(
                f"[TOOL] No articles cleared relevance gate ({MIN_RELEVANCE}) for '{query}'; "
                f"using top confidence article as fallback"
            )

        # Cap the number of articles passed to the LLM context.
        # Allow up to the requested number so the agent can read ALL search results.
        MAX_CONTEXT_ARTICLES = num_articles
        context_articles = high_relevance[:MAX_CONTEXT_ARTICLES]

        # If the only surviving article is weak, tell the LLM explicitly
        all_weak = all(a.relevance_score < MIN_RELEVANCE for a in context_articles)
        if all_weak:
            logger.warning(f"[TOOL] All surviving articles have low relevance for query: {query}")
            _store_sources(None, tool_name="search_pubmed")
            _store_debug(debug_info)
            return (
                "No high-quality directly relevant evidence was found on PubMed for this specific query. "
                "The available articles address adjacent topics but do not directly answer the question. "
                "Please acknowledge this limitation in your response and avoid making claims from "
                "non-specific sources."
            )

        # Articles are already scored and sorted by the service
        logger.info(
            f"Retrieved {len(result.articles)} articles, {len(high_relevance)} passed relevance gate, "
            f"using {len(context_articles)} in context (avg confidence: {result.avg_confidence:.1f})"
        )
        logger.debug(f"[TOOL] Context article PMIDs: {[a.pmid for a in context_articles]}")

        # Build response for LLM
        search_sources: list = []
        result_parts = _pubmed_header(
            "RETRIEVED PUBMED ARTICLES (sorted by confidence score, highest first):",
            requested=requested_articles,
            shown_cap=_PUBMED_MAX_ARTICLES,
        )

        for article in context_articles:
            # Get quality warnings using new scoring module
            warnings = get_quality_warnings(
                confidence_score=article.confidence_score,
                relevance_score=article.relevance_score,
                publication_date=article.publication_date,
                abstract=article.abstract,
                fwci=article.fwci,
            )
            
            ref_id = _next_ref_id()
            ref_num = _ref_num(ref_id)
            result_parts.extend(_pubmed_article_lines(article, ref_num, warnings))

            source_entry = {
                "ref": ref_id,
                "source": f"PubMed — {article.journal}" if article.journal else "PubMed",
                "pmid": article.pmid,
                "pmc_id": article.pmc_id,
                "title": article.title,
                "url": article.get_url(),
                "citations": article.citation_count,
                "citation_count": article.citation_count,  # Add both for compatibility
                "confidence_score": article.confidence_score,
                "confidence_breakdown": article.confidence_breakdown,
                "study_type": ", ".join(article.publication_types) if article.publication_types else "Unknown",
                "content": extract_relevant_snippet(query, article.abstract),
                "tool": "search_pubmed",
                "warnings": warnings,
                "doi": article.doi,
                # Add full article data for abstract viewer fallback
                "abstract": article.abstract,
                "authors": article.authors,
                "journal": article.journal,
                "publication_date": article.publication_date,
                "publication_types": article.publication_types,
                "pubmed_url": article.get_url(),
                "doi_url": article.get_doi_url() if article.doi else "",
                # Add raw metrics for frontend display
                "fwci": article.fwci,
                "fwci_source": article.fwci_source,
                "citation_normalized_percentile": article.citation_normalized_percentile,
                "cite_score": article.cite_score,
                "sjr": article.sjr,
                "snip": article.snip,
                "journal_percentile": article.journal_percentile,
                "citation_source": article.citation_source,
                "relevance_score": article.relevance_score,
                "open_access": article.open_access,
                "subject_areas": article.subject_areas,
                "query_type": article.query_type,
                "full_text_available": article.full_text_available,
                "full_text_sections": article.full_text_sections,
            }
            search_sources.append(source_entry)

        _store_sources(search_sources, tool_name="search_pubmed")
        _store_debug(debug_info)
        return "\n".join(result_parts)

    except Exception as e:
        logger.error(f"Error searching PubMed for '{query}': {str(e)}")
        _store_debug(debug_info)
        return _safe_error_response("searching PubMed", e)


# ============================================================================
# TOOL 9: Multi-Query PubMed Search
# ============================================================================

def _build_pubmed_response(
    queries: list[str],
    articles,
    avg_confidence: float,
    sources_tool_name: str = "search_pubmed_multi",
    max_articles: int = _PUBMED_DEFAULT_ARTICLES,
    requested: int | None = None,
) -> str:
    """Shared helper to format a list of PubMedArticle objects into LLM context.

    `max_articles` lets the caller cap the LLM context to the number the user
    actually asked for. Previously this was hardcoded to 15 even if the user
    requested fewer (audit A9).
    """
    MIN_RELEVANCE = 0.45
    high_relevance = [a for a in articles if a.relevance_score >= MIN_RELEVANCE]
    if not high_relevance:
        high_relevance = articles[:1] if articles else []

    MAX_CONTEXT = max(1, min(int(max_articles), _PUBMED_MAX_ARTICLES))
    context_articles = high_relevance[:MAX_CONTEXT]

    if not context_articles:
        return (
            "No high-quality directly relevant evidence was found on PubMed for these queries. "
            "Please acknowledge this limitation in your response."
        )

    search_sources: list = []
    result_parts = _pubmed_header(
        f"RETRIEVED PUBMED ARTICLES for queries: {' | '.join(queries)}",
        requested=requested if requested is not None else int(max_articles),
        shown_cap=_PUBMED_MAX_ARTICLES,
    )

    combined_query = " ".join(queries)
    for article in context_articles:
        warnings = get_quality_warnings(
            confidence_score=article.confidence_score,
            relevance_score=article.relevance_score,
            publication_date=article.publication_date,
            abstract=article.abstract,
            fwci=article.fwci,
        )
        ref_id = _next_ref_id()
        ref_num = _ref_num(ref_id)
        result_parts.extend(_pubmed_article_lines(article, ref_num, warnings))

        search_sources.append({
            "ref": ref_id,
            "source": f"PubMed — {article.journal}" if article.journal else "PubMed",
            "pmid": article.pmid,
            "pmc_id": article.pmc_id,
            "title": article.title,
            "url": article.get_url(),
            "citations": article.citation_count,
            "citation_count": article.citation_count,
            "confidence_score": article.confidence_score,
            "confidence_breakdown": article.confidence_breakdown,
            "study_type": ", ".join(article.publication_types) if article.publication_types else "Unknown",
            "content": extract_relevant_snippet(combined_query, article.abstract),
            "tool": sources_tool_name,
            "warnings": warnings,
            "doi": article.doi,
            "abstract": article.abstract,
            "authors": article.authors,
            "journal": article.journal,
            "publication_date": article.publication_date,
            "publication_types": article.publication_types,
            "pubmed_url": article.get_url(),
            "doi_url": article.get_doi_url() if article.doi else "",
            # Add raw metrics for frontend display
            "fwci": article.fwci,
            "fwci_source": article.fwci_source,
            "citation_normalized_percentile": article.citation_normalized_percentile,
            "cite_score": article.cite_score,
            "sjr": article.sjr,
            "snip": article.snip,
            "journal_percentile": article.journal_percentile,
            "citation_source": article.citation_source,
            "relevance_score": article.relevance_score,
            "open_access": article.open_access,
            "subject_areas": article.subject_areas,
            "query_type": article.query_type,
            "publication_date": article.publication_date,
            "pubmed_url": article.get_url(),
            "doi_url": article.get_doi_url() if article.doi else "",
            "fwci": article.fwci,
            "fwci_source": article.fwci_source,
            "citation_normalized_percentile": article.citation_normalized_percentile,
            "cite_score": article.cite_score,
            "sjr": article.sjr,
            "snip": article.snip,
            "journal_percentile": article.journal_percentile,
            "open_access": article.open_access,
            "full_text_available": article.full_text_available,
            "full_text_sections": article.full_text_sections,
        })

    _store_sources(search_sources, tool_name=sources_tool_name)
    return "\n".join(result_parts)


@tool
def search_pubmed_multi(
    queries: Annotated[
        list[str],
        (
            '2-3 specific English sub-queries on different facets of the same question, each a different evidence stream (max 3).'
        ),
    ],
    num_articles: Annotated[
        int,
        "Total articles in the merged result: the user's number if given, else the default 5 (never ask); max 10.",
    ] = _PUBMED_DEFAULT_ARTICLES,
) -> str:
    """
    Search PubMed with 2-3 focused sub-queries; returns merged, deduplicated results ranked by confidence. Use instead of search_pubmed when evidence differs by therapy subtype, population or subgroup, or one broad query would miss nuances or return low-relevance articles; always for subgroup signals (one general drug-safety sub-query plus one subgroup sub-query).
    """
    if not queries or len(queries) < 2:
        return "Please provide at least 2 sub-queries for multi-query search."

    # Reject queries written in non-Latin scripts (audit P10).
    for q in queries:
        if _looks_non_english(q):
            return "ERROR: All PubMed queries must be written in English (Latin script)."

    queries = queries[:3]
    requested_articles = int(num_articles)
    num_articles = max(1, min(requested_articles, _PUBMED_MAX_ARTICLES))
    logger.info(f"[TOOL] search_pubmed_multi: {len(queries)} sub-queries: {queries}, num_articles={num_articles}")

    debug_info = {"sub_queries": queries, "cache_hit": False, "num_articles_requested": num_articles}

    try:
        result = pubmed_service.search_pubmed_multi(
            queries=queries,
            max_per_query=8,
            min_confidence=settings.pubmed_min_confidence,
        )

        debug_info["articles_fetched"] = len(result.articles)
        debug_info["avg_confidence"] = result.avg_confidence
        _store_debug(debug_info)

        if not result.articles:
            _store_sources(None, tool_name="search_pubmed_multi")
            return (
                "No PubMed articles found across all sub-queries. "
                "Try broader or different search terms."
            )

        return _build_pubmed_response(
            queries=queries,
            articles=result.articles,
            avg_confidence=result.avg_confidence,
            sources_tool_name="search_pubmed_multi",
            max_articles=num_articles,
            requested=requested_articles,
        )

    except Exception as exc:
        logger.error(f"[TOOL] search_pubmed_multi failed: {exc}", exc_info=True)
        _store_debug(debug_info)
        return _safe_error_response("multi-query PubMed search", exc)


ALL_TOOLS = [
    get_drug_info,
    check_drug_interactions,
    check_drug_food_interaction,
    search_drugs_by_indication,
    search_drugs_by_category,
    recommend_alternative_drug,
    check_for_overdose_interaction,
    analyze_patient_medications,
    search_pubmed,
    search_pubmed_multi,
]
