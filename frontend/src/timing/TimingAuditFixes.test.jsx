// Audit fixes N2 (named subject in the advice sentence), N6 (status reason
// from coverage) and N7 (tr-TR numbers for ± and axis ticks). Synthetic data.
import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import TimingPage from './TimingPage';
import Timeline from './Timeline';
import { adviceStatusText, num } from './format';
import { timingRequest } from './client';
vi.mock('./client', () => ({ timingRequest: vi.fn() }));
// M-03 section is tested in Mechanism.test.jsx; here it answers with an empty result.
vi.mock('./mechanismClient',()=>({mechanismRequest:vi.fn(async()=>({schema_version:'m03-mechanism/1',drugs:[],pairs:[],notice:''}))}));

const search = [{ drug_id: 'DB00316', name: '[SYNTHETIC] Sucralfate', profiles: [] },
  { drug_id: 'DB00006', name: '[SYNTHETIC] Ciprofloxacin', profiles: [] }];
const source = { source_ref: 'emc:4346:4.5', url: 'https://www.medicines.org.uk/emc/product/4346/smpc', title: 'Synthetic label',
  section: '4.5', excerpt: 'synthetic excerpt', label_updated: '2026-10-15', checked_on: '2026-11-26', verification: 'x' };
const advice = { status: 'evaluated', coverage: [{ item_ids: ['DB00316', 'DB00006'], status: 'matched', reason: 'ok' }],
  advice: [{ rule_id: 'r', subject_drug_id: 'DB00006', other_kind: 'drug', other_id: 'DB00316', other_name: '[SYNTHETIC] Sucralfate',
    direction: 'before', interval_hours: { kind: 'range', lower: 1, upper: 2 }, conditions: [], source }] };
const empty = (id, name) => ({ requested_id: id, drug: { name }, lookup_status: 'found', measurements: [], derived: [], fields: [],
  data_status: { half_life: 'empty', tmax: 'empty' } });

function mount() { return render(<MemoryRouter><TimingPage /></MemoryRouter>); }
async function selectSucralfateFirst() {
  await screen.findByLabelText(/İlaç adı/);
  fireEvent.change(screen.getByLabelText(/İlaç adı/), { target: { value: 'Su' } });
  fireEvent.click(await screen.findByRole('button', { name: /Ekle:.*Sucralfate/ }));
  fireEvent.change(screen.getByLabelText(/İlaç adı/), { target: { value: 'Ci' } });
  fireEvent.click(await screen.findByRole('button', { name: /Ekle:.*Ciprofloxacin/ }));
}
beforeEach(() => { timingRequest.mockReset(); });
afterEach(cleanup);

describe('audit fixes', () => {
  it('N2: a pair cell names the other drug and sits in the subject drug column, independent of order', async () => {
    const table = { schema_version: 'm02-timing-table/1', notice: '',
      drugs: [{ requested_id: 'DB00316', drug_id: 'DB00316', name: '[SYNTHETIC] Sucralfate', found: true, has_food_entries: true },
              { requested_id: 'DB00006', drug_id: 'DB00006', name: '[SYNTHETIC] Ciprofloxacin', found: true, has_food_entries: true }],
      rows: [{ row_id: 'selected_drugs', label: 'Seçilen diğer ilaçlarla', cells: { DB00006: [{ kind: 'separate',
        text: '[SYNTHETIC] Sucralfate: ayrı alın', timing_text: '1–2 sa önce veya ≥4 sa sonra', before: null, after: null,
        source: 'label', source_text: 'synthetic excerpt', timing_quote: 'synthetic excerpt', source_ref: 'emc:4346:4.5',
        source_url: 'https://www.medicines.org.uk/emc/product/4346/smpc', product: 'Synthetic product (UK)', with_drug_id: 'DB00316' }] } }] };
    timingRequest.mockImplementation(async path => path === 'compare'
      ? { drugs: [empty('DB00316', '[SYNTHETIC] Sucralfate'), empty('DB00006', '[SYNTHETIC] Ciprofloxacin')] }
      : path === 'table' ? table : { items: search, limited: false });
    mount(); await selectSucralfateFirst();
    fireEvent.click(screen.getByRole('button', { name: 'Karşılaştır' }));
    const t = await screen.findByTestId('food-table');
    const tds = t.querySelectorAll('tbody tr')[0].querySelectorAll('td');
    expect(tds[0].textContent).toBe('—');                       // Sucralfate column
    expect(tds[1].textContent).toContain('[SYNTHETIC] Sucralfate: ayrı alın');   // Ciprofloxacin column
    expect(tds[1].textContent).toContain('1–2 sa önce veya ≥4 sa sonra');
    expect(tds[1].textContent).toContain('Etiket: Synthetic product (UK)');
    expect(t.textContent).not.toContain('İlk ilaç');
  });

  it('N6: a missing drug record is not reported as missing conditions', () => {
    const t = adviceStatusText({ status: 'not_evaluated', advice: [],
      coverage: [{ item_ids: ['DB1', 'DB2'], status: 'drug_not_found', reason: 'x' }] });
    expect(t).toContain('bir ilaç kaydı bulunamadı');
    expect(t).not.toContain('ürün/koşul');
    expect(adviceStatusText({ status: 'not_evaluated', advice: [],
      coverage: [{ item_ids: ['a', 'b'], status: 'conditions_required', reason: 'x' }] })).toContain('ürün/koşul doğrulaması gerekli');
    expect(adviceStatusText({ status: 'evaluated', advice: [], coverage: [] })).toBe('Seçilen kapsam katalogda değerlendirildi');
  });

  it('N7: ± spreads and axis ticks use the tr-TR number format', () => {
    expect(num(0.333333)).toBe('0,333333');
    expect(num(1.65, 3)).toBe('1,65');
    const m = { measurement_id: 'm1', measure_type: 'tmax', hours: { kind: 'point', value: 1.5 },
      dispersion: { kind: 'plus_minus', value_original: 20, unit: 'minutes', value_hours: 0.333333 },
      conditions: {}, review_required: false, approximate: false, time_reference: 'after_administration' };
    render(<Timeline drugs={[{ drug: { name: '[SYNTHETIC] Drug A' }, measurements: [m], derived: [] }]} />);
    expect(screen.getByText(/± 0,333333 sa/)).toBeTruthy();
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'log' } });
    const ticks = [...document.querySelectorAll('svg text')].map(t => t.textContent);
    expect(ticks.some(t => t.includes(','))).toBe(true);
    expect(ticks.every(t => !/\d\.\d/.test(t))).toBe(true);
  });
});

describe('parser /11: enantiomer values', () => {
  it('shows the enantiomer as a condition so R and S stay on separate rows', async () => {
    const { conditionText } = await import('./format');
    expect(conditionText({route:[], stereoisomer:['R-warfarin'], analyte:'not_stated'})).toBe('R-warfarin');
    expect(conditionText({route:[], stereoisomer:['S-warfarin'], analyte:'not_stated'})).not.toBe(
      conditionText({route:[], stereoisomer:['R-warfarin'], analyte:'not_stated'}));
  });
});
