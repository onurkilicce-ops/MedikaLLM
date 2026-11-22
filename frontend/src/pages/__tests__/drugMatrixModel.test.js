/**
 * Drug matrix cell semantics. The regression: failed / loading / stale /
 * unchecked pairs were rendered with the same green check as a pair that was
 * really checked and has no DrugBank record.
 */
import { describe, expect, test } from 'vitest';
import { CELL, cellState, selectionKey, summarize } from '../drugMatrixModel';

const W = 'DB00682';
const A = 'DB00945';
const P = 'DB00316';
const record = { drug1_id: W, drug2_id: A, description: 'bleeding risk', source_url: 'https://go.drugbank.com/drugs/DB00682' };

const key = selectionKey([W, A, P]);
const done = (data) => ({ key, phase: 'done', data });

describe('cellState', () => {
  test('selection key ignores order', () => {
    expect(selectionKey([P, W, A])).toBe(key);
  });

  test('pair with a record → record (no severity bucket)', () => {
    const r = done({ status: 'found', interactions: [record], unresolved_drug_ids: [] });
    expect(cellState(r, key, A, W)).toEqual({ state: CELL.RECORD, interaction: record });
  });

  test('checked pair without record → no_record, never a "safe" state', () => {
    const r = done({ status: 'found', interactions: [record], unresolved_drug_ids: [] });
    expect(cellState(r, key, W, P).state).toBe(CELL.NO_RECORD);
  });

  test('request failure → error for every pair', () => {
    expect(cellState({ key, phase: 'error' }, key, W, P).state).toBe(CELL.ERROR);
    const backendError = done({ status: 'error', interactions: [], error: { code: 'database_error' } });
    expect(cellState(backendError, key, W, A).state).toBe(CELL.ERROR);
  });

  test('loading → loading', () => {
    expect(cellState({ key, phase: 'loading' }, key, W, A).state).toBe(CELL.LOADING);
    expect(cellState(null, key, W, A).state).toBe(CELL.LOADING);
  });

  test('result of the previous selection is never reused for a new one', () => {
    const oldKey = selectionKey([W, A]);
    const oldResult = { key: oldKey, phase: 'done', data: { status: 'no_record', interactions: [] } };
    expect(cellState(oldResult, key, W, A).state).toBe(CELL.LOADING);
  });

  test('unresolved drug → its pairs are not checked', () => {
    const r = done({ status: 'incomplete', interactions: [], unresolved_drug_ids: [P] });
    expect(cellState(r, key, W, P).state).toBe(CELL.NOT_CHECKED);
    expect(cellState(r, key, W, A).state).toBe(CELL.NO_RECORD);
  });

  test('payload without status (legacy/unknown) never yields no_record', () => {
    const r = done({ interactions: [] });
    expect(cellState(r, key, W, A).state).toBe(CELL.NOT_CHECKED);
  });
});

describe('summarize', () => {
  test('summary only for the matching, successful result', () => {
    const drugs = [{ drug_id: W, name: 'Warfarin' }, { drug_id: A, name: 'Aspirin' }, { drug_id: P, name: 'Paracetamol' }];
    const r = done({ status: 'incomplete', interactions: [record], unresolved_drug_ids: [P], pairs_checked: 1, pairs_total: 3 });
    expect(summarize(r, key, drugs)).toEqual({ records: 1, pairsChecked: 1, pairsTotal: 3, unresolvedNames: ['Paracetamol'] });
    expect(summarize({ key, phase: 'error' }, key, drugs).records).toBeNull();
    expect(summarize(r, selectionKey([W, A]), drugs).records).toBeNull();
  });
});
