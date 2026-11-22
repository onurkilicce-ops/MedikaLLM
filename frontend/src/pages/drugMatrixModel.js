/**
 * Pure helpers for the drug interaction matrix (no React, unit tested).
 *
 * The matrix used to mark every pair without an interaction record with a
 * green check — also when the request failed, while it was loading, or when
 * the response belonged to a previous drug selection. A cell is now derived
 * from a result that is bound to the exact selection it was computed for.
 */

export const CELL = Object.freeze({
  LOADING: 'loading', // request for this selection still running
  ERROR: 'error', // request failed or backend reported status "error"
  RECORD: 'record', // DrugBank holds an interaction record for the pair
  NO_RECORD: 'no_record', // pair was checked, no record (NOT "safe")
  NOT_CHECKED: 'not_checked', // a drug of the pair was not found / not checked
});

/** Stable key for a drug selection, independent of order. */
export function selectionKey(drugIds) {
  return [...new Set(drugIds)].sort().join('|');
}

function findRecord(interactions, a, b) {
  return (interactions || []).find(
    (i) => (i.drug1_id === a && i.drug2_id === b) || (i.drug1_id === b && i.drug2_id === a),
  );
}

/**
 * @param {object|null} result  { key, phase: 'loading'|'done'|'error', data }
 * @param {string} currentKey   selectionKey() of the drugs on screen
 */
export function cellState(result, currentKey, drug1Id, drug2Id) {
  // A result computed for another selection is never reused.
  if (!result || result.key !== currentKey || result.phase === 'loading') {
    return { state: CELL.LOADING };
  }
  if (result.phase === 'error' || !result.data || result.data.status === 'error') {
    return { state: CELL.ERROR };
  }
  const data = result.data;
  const unresolved = new Set(data.unresolved_drug_ids || []);
  if (unresolved.has(drug1Id) || unresolved.has(drug2Id) || data.status === 'unresolved') {
    return { state: CELL.NOT_CHECKED };
  }
  const record = findRecord(data.interactions, drug1Id, drug2Id);
  if (record) return { state: CELL.RECORD, interaction: record };
  // Only an explicit successful status may produce "no record"; an older or
  // unexpected payload without status stays "not checked".
  if (['found', 'no_record', 'incomplete'].includes(data.status)) {
    return { state: CELL.NO_RECORD };
  }
  return { state: CELL.NOT_CHECKED };
}

/** Summary numbers for the result that matches the current selection. */
export function summarize(result, currentKey, drugs) {
  const empty = { records: null, pairsChecked: null, pairsTotal: null, unresolvedNames: [] };
  if (!result || result.key !== currentKey || result.phase !== 'done' || !result.data) return empty;
  const data = result.data;
  if (data.status === 'error') return empty;
  const nameOf = (id) => drugs.find((d) => d.drug_id === id)?.name || id;
  return {
    records: (data.interactions || []).length,
    pairsChecked: data.pairs_checked ?? null,
    pairsTotal: data.pairs_total ?? null,
    unresolvedNames: (data.unresolved_drug_ids || []).map(nameOf),
  };
}
