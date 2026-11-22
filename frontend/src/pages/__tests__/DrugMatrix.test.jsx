/**
 * DrugMatrix rendered with a mocked backend.
 *
 * Covers the screen-level regressions: a failed interaction request, a pair
 * whose drug was not found and an unmatched patient medication must not be
 * shown as a check mark / "no interaction".
 */
import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, test, vi } from 'vitest';
import DrugMatrix from '../DrugMatrix';

const json = (body, status = 200) =>
  Promise.resolve({ ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) });

function mockBackend({ interactions }) {
  return vi.fn((url) => {
    if (url.includes('/api/users/profile/patient/')) {
      return json({ current_medications: ['Warfarin', 'Aspirin', 'Paracetamol', 'Xyzzyl'] });
    }
    if (url.includes('/api/drugs/search/')) {
      const q = decodeURIComponent(url.split('/api/drugs/search/')[1].split('?')[0]).toLowerCase();
      const known = {
        warfarin: { drug_id: 'DB00682', name: 'Warfarin' },
        aspirin: { drug_id: 'DB00945', name: 'Acetylsalicylic acid' },
        paracetamol: { drug_id: 'DB00316', name: 'Acetaminophen' },
      };
      return json({ success: true, results: known[q] ? [known[q]] : [] });
    }
    if (url.includes('/api/drugs/interactions')) return interactions();
    return json({}, 404);
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

const renderMatrix = () =>
  render(<DrugMatrix user={{ isDoctor: false }} initialPatientId="p-1" />);

const cellStates = (container) =>
  Array.from(container.querySelectorAll('td[data-cell-state]')).map((td) => td.getAttribute('data-cell-state'));

describe('DrugMatrix', () => {
  test('failed interaction request → error cells, error banner, no check marks', async () => {
    vi.stubGlobal('fetch', mockBackend({ interactions: () => json({ detail: 'boom' }, 500) }));
    const { container } = renderMatrix();
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(cellStates(container)).toEqual(['error', 'error', 'error']);
    expect(container.textContent).not.toContain('✓');
    // The unmatched patient medication is reported, not dropped.
    expect(container.textContent).toContain('Xyzzyl');
  });

  test('backend status "error" is also shown as failed, not as "no record"', async () => {
    vi.stubGlobal('fetch', mockBackend({
      interactions: () => json({ status: 'error', interactions: [], count: 0, error: { code: 'database_error' } }),
    }));
    const { container } = renderMatrix();
    await waitFor(() => expect(cellStates(container).length).toBe(3));
    await waitFor(() => expect(cellStates(container).every((s) => s === 'error')).toBe(true));
  });

  test('successful check → record and neutral "no record" cells, no severity scale', async () => {
    vi.stubGlobal('fetch', mockBackend({
      interactions: () => json({
        status: 'found',
        interactions: [{
          drug1_id: 'DB00682', drug1_name: 'Warfarin', drug2_id: 'DB00945', drug2_name: 'Acetylsalicylic acid',
          description: 'Bleeding risk can be increased.', severity: null, severity_status: 'not_rated',
          source_url: 'https://go.drugbank.com/drugs/DB00682',
        }],
        count: 1, unresolved_drug_ids: [], pairs_checked: 3, pairs_total: 3,
      }),
    }));
    const { container } = renderMatrix();
    await waitFor(() => expect(cellStates(container)).toContain('record'));
    const states = cellStates(container).sort();
    expect(states).toEqual(['no_record', 'no_record', 'record']);
    expect(container.textContent).not.toContain('✓');
    for (const label of ['Contraindicated', 'Critical', 'Kontrendike', 'Kritik']) {
      expect(container.textContent).not.toContain(label);
    }
  });
});

describe('DrugMatrix patient medication lookups', () => {
  test('failed lookup is reported separately from "not matched"', async () => {
    const backend = vi.fn((url) => {
      if (url.includes('/api/users/profile/patient/')) {
        return json({ current_medications: ['Warfarin', 'Aspirin', 'Brokenlookup', 'Xyzzyl'] });
      }
      if (url.includes('/api/drugs/search/')) {
        const q = decodeURIComponent(url.split('/api/drugs/search/')[1].split('?')[0]).toLowerCase();
        if (q === 'brokenlookup') return json({ detail: 'boom' }, 500);
        const known = {
          warfarin: { drug_id: 'DB00682', name: 'Warfarin' },
          aspirin: { drug_id: 'DB00945', name: 'Acetylsalicylic acid' },
        };
        return json({ success: true, results: known[q] ? [known[q]] : [] });
      }
      if (url.includes('/api/drugs/interactions')) {
        return json({ status: 'no_record', interactions: [], unresolved_drug_ids: [], pairs_checked: 1, pairs_total: 1 });
      }
      return json({}, 404);
    });
    vi.stubGlobal('fetch', backend);
    const { container } = renderMatrix();
    await waitFor(() => expect(cellStates(container)).toEqual(['no_record']));
    const notes = Array.from(container.querySelectorAll('[role=note]')).map((n) => n.textContent);
    expect(notes.some((t) => t.includes('Xyzzyl') && !t.includes('Brokenlookup'))).toBe(true);
    expect(notes.some((t) => t.includes('Brokenlookup') && !t.includes('Xyzzyl'))).toBe(true);
  });

  test('more than 10 matched medications: first 10 checked, rest listed as not checked', async () => {
    const meds = Array.from({ length: 12 }, (_, i) => `Drug${i + 1}`);
    vi.stubGlobal('fetch', vi.fn((url) => {
      if (url.includes('/api/users/profile/patient/')) return json({ current_medications: meds });
      if (url.includes('/api/drugs/search/')) {
        const q = decodeURIComponent(url.split('/api/drugs/search/')[1].split('?')[0]);
        return json({ success: true, results: [{ drug_id: `ID-${q}`, name: q }] });
      }
      if (url.includes('/api/drugs/interactions')) {
        return json({ status: 'no_record', interactions: [], unresolved_drug_ids: [], pairs_checked: 45, pairs_total: 45 });
      }
      return json({}, 404);
    }));
    const { container } = renderMatrix();
    await waitFor(() => expect(cellStates(container).length).toBe(45));
    const notes = Array.from(container.querySelectorAll('[role=note]')).map((n) => n.textContent).join(' ');
    expect(notes).toContain('Drug11');
    expect(notes).toContain('Drug12');
  });
});
