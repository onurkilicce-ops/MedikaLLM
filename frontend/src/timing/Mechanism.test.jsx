import React from 'react';
import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import Mechanism from './Mechanism';

afterEach(cleanup);
const T = '[SYNTHETIC] ';
const drug = (id, name, extra = {}) => ({requested_id:id, lookup_status:'found', drug:{drug_id:id, name:T+name},
  proteins:[], organs:[], texts:[], ...extra});
const cyp = {kind:'enzyme', protein_id:'BE1', name:T+'Cytochrome P450 3A4', organism:'Humans', human:true};
const inhibitor = {protein_kind:'enzyme', protein_id:'BE1', protein_name:T+'Cytochrome P450 3A4', mechanism:'inhibition',
  perpetrator_id:'DB00002', victim_id:'DB00001', effect:'victim_exposure_may_increase',
  evidence:[{drug_id:'DB00002', roles:['inhibitor'], raw_actions:'inhibitor', known_action:'yes', strength:'strong'},
            {drug_id:'DB00001', roles:['substrate'], raw_actions:'substrate', known_action:'yes', strength:''}],
  caveats:['prodrug_reverses_direction','other_pathways_may_compensate'], directional:true};
const body = (pairs, drugs) => ({schema_version:'m03-mechanism/1', notice:'Synthetic notice.', pairs, drugs: drugs || [
  drug('DB00001','Victim', {organs:[{organ:'kidney', source_field:'route_of_elimination', quote:T+'About 60% in urine.', quote_start:0, quote_end:20, notes:[]},
                                    {organ:'liver', source_field:'clearance', quote:T+'Reduced in hepatic impairment.', quote_start:0, quote_end:30, notes:['condition_context']}],
    proteins:[{...cyp, roles:['substrate'], raw_actions:'substrate', known_action:'yes', inhibition_strength:'', induction_strength:''},
              {kind:'enzyme', protein_id:'BE9', name:T+'Rodent enzyme', organism:'Rattus', human:false, roles:['substrate'], raw_actions:'substrate', known_action:'', inhibition_strength:'', induction_strength:''}],
    texts:[{source_field:'route_of_elimination', stored_text:T+'About 60% in urine.'}]}),
  drug('DB00002','Perpetrator', {proteins:[{...cyp, roles:['inhibitor'], raw_actions:'inhibitor', known_action:'yes', inhibition_strength:'strong', induction_strength:''}]})]});

describe('M03 mechanism section', () => {
  it('explains the interaction through the shared enzyme with the right direction', () => {
    render(<Mechanism mechanism={body([{drug_ids:['DB00001','DB00002'], status:'explained_by_shared_protein', explanations:[inhibitor],
      shared_proteins_without_direction:[], recorded_interactions:[{from_drug_id:'DB00002', to_drug_id:'DB00001', description:T+'Recorded text.'}]}])} />);
    const text = screen.getByTestId('m03-explanation').textContent;
    expect(text).toContain(`${T}Perpetrator, ${T}Victim ilacını işleyen ${T}Cytochrome P450 3A4 enzimini yavaşlatır (${T}Victim bu enzimin substratı olarak kayıtlı)`);
    expect(text).toContain(`${T}Victim kanda birikebilir`);
    expect(screen.getByText(/ön ilaçsa \(prodrug\) yön tersine döner/)).toBeTruthy();
    expect(screen.getByText(/güç: strong/)).toBeTruthy();
    expect(screen.getByText(new RegExp(`${T.replace(/[[\]]/g,'\\$&')}Recorded text`))).toBeTruthy();
  });
  it('shows organs with their quote and caution notes, never an attributed share', () => {
    render(<Mechanism mechanism={body([])} />);
    expect(screen.getByText('Böbrek (idrar)')).toBeTruthy();
    expect(screen.getAllByText(`${T}About 60% in urine.`).length).toBe(2);
    expect(screen.queryByText(/metindeki pay/)).toBeNull();
    expect(screen.getAllByText(/sistem bir organa yüzde atamaz/).length).toBe(2);
    expect(screen.getByText(/yalnız hasta durumu bağlamı/)).toBeTruthy();
    expect(screen.getAllByText(/kullanır \(substrat\)/).length).toBeGreaterThan(0);
    expect(screen.getByText(/insan dışı \(Rattus\); karşılaştırmaya alınmaz/)).toBeTruthy();
    expect(screen.getByText(/inhibisyon gücü: strong/)).toBeTruthy();
  });
  it('never presents missing data as no interaction', () => {
    render(<Mechanism mechanism={body([{drug_ids:['DB00001','DB00003'], status:'no_shared_protein_in_record', explanations:[],
      shared_proteins_without_direction:[], recorded_interactions:[]}],
      [drug('DB00001','Victim'), drug('DB00003','Empty')])} />);
    expect(screen.getByText(/ortak bir insan proteini yok. Bu, etkileşim olmadığı anlamına gelmez/)).toBeTruthy();
    expect(screen.getAllByText(/Bu, ilacın bunları kullanmadığı anlamına gelmez/).length).toBe(2);
    expect(screen.getAllByText(/organ yolu ifadesi bulunamadı \(atılım\/metabolizma\/klirens metni yok\)/).length).toBe(2);
  });
  it('labels a shared substrate as weak and an inducer as faster clearance', () => {
    const shared = {...inhibitor, mechanism:'shared_substrate', perpetrator_id:null, victim_id:null, effect:'competition_possible_not_established',
      caveats:['shared_substrate_is_weak_evidence'], directional:false};
    const inducer = {...inhibitor, mechanism:'induction', effect:'victim_exposure_may_decrease'};
    render(<Mechanism mechanism={body([{drug_ids:['DB00001','DB00002'], status:'explained_by_shared_protein', explanations:[inducer, shared],
      shared_proteins_without_direction:[], recorded_interactions:[]}])} />);
    const [a, b] = screen.getAllByTestId('m03-explanation').map(x => x.textContent);
    expect(a).toContain('enzimini hızlandırır') ; expect(a).toContain('daha hızlı temizlenebilir');
    expect(b).toContain('Birbirleriyle yarışabilirler; bu kayıtta yön belirlenemez');
  });
  it('gives carriers no transport direction and flags an inhibitor+inducer conflict', () => {
    const carrier = {...inhibitor, protein_kind:'carrier', protein_name:T+'Serum albumin', effect:'carrier_binding_may_change',
      caveats:['carrier_binding_direction_not_established'], directional:false};
    const conflict = {...inhibitor, caveats:['perpetrator_listed_as_inhibitor_and_inducer'], directional:false};
    render(<Mechanism mechanism={body([{drug_ids:['DB00001','DB00002'], status:'shared_protein_no_direction', explanations:[conflict, carrier],
      shared_proteins_without_direction:[], recorded_interactions:[]}])} />);
    const [c1, c2] = screen.getAllByTestId('m03-explanation');
    expect(c1.parentElement.className).toBe('m03-weak'); expect(c2.parentElement.className).toBe('m03-weak');
    expect(screen.getByText(/Ortak protein var, ama kayıttan net bir yön çıkarılamıyor/)).toBeTruthy();
    expect(screen.getByText(/iki açıklama birbirine zıttır, net yön belirlenemez/)).toBeTruthy();
    expect(c2.textContent).toContain('serbest düzeyin yönü bu kayıttan belirlenemez');
    expect(c2.textContent).not.toContain('hücre zarından');
  });
  it('labels a shared-substrate-only pair as having no recorded direction', () => {
    render(<Mechanism mechanism={body([{drug_ids:['DB00001','DB00002'], status:'shared_substrate_only', explanations:[],
      shared_proteins_without_direction:[], recorded_interactions:[]}])} />);
    expect(screen.getByText(/Yalnız ortak kullanılan protein var/)).toBeTruthy();
  });
  it('R3: renders an inhibitor+inducer conflict once, as an undetermined direction', () => {
    const conflictInh = {...inhibitor, caveats:['perpetrator_listed_as_inhibitor_and_inducer'], directional:false};
    const conflictInd = {...conflictInh, mechanism:'induction', effect:'victim_exposure_may_decrease'};
    render(<Mechanism mechanism={body([{drug_ids:['DB00001','DB00002'], status:'shared_protein_no_direction', explanations:[conflictInh, conflictInd],
      shared_proteins_without_direction:[], recorded_interactions:[]}])} />);
    const items = screen.getAllByTestId('m03-explanation');
    expect(items).toHaveLength(1);
    expect(items[0].textContent).toContain('hem yavaşlatıcı (inhibitör) hem hızlandırıcı (indükleyici)');
    expect(items[0].textContent).toContain('belirlenemez');
    expect(items[0].textContent).not.toContain('birikebilir');
  });
  it('R3: explains known_action without saying the drug has no effect, and separates flagged organs', () => {
    const drugs = [drug('DB00001','Victim', {organs:[
      {organ:'kidney', source_field:'route_of_elimination', quote:T+'Excreted in urine.', quote_start:0, quote_end:30, notes:[]},
      {organ:'liver', source_field:'metabolism', quote:T+'Not metabolized by the liver.', quote_start:0, quote_end:40, notes:['negated_or_minor']}],
      proteins:[{...cyp, roles:['inhibitor'], raw_actions:'inhibitor', known_action:'no', inhibition_strength:'strong', induction_strength:''}],
      texts:[{source_field:'route_of_elimination', stored_text:T+'Excreted in urine.'}]})];
    render(<Mechanism mechanism={body([], drugs)} />);
    expect(screen.queryByText(/farmakolojik etkisi yok/)).toBeNull();
    expect(screen.getByText(/bu, proteini etkilemediği anlamına gelmez/)).toBeTruthy();
    expect(screen.getByTestId('m03-organs-route').textContent).toContain('Böbrek (idrar)');
    expect(screen.getByTestId('m03-organs-route').textContent).not.toContain('Karaciğer');
    expect(screen.getByTestId('m03-organs-flagged').textContent).toContain('Karaciğer');
  });
  it('R3: a shared plasma-protein substrate is worded as binding, not transport', () => {
    const shared = {...inhibitor, protein_kind:'carrier', protein_name:T+'Serum albumin', mechanism:'shared_substrate', perpetrator_id:null,
      victim_id:null, effect:'competition_possible_not_established', caveats:['shared_substrate_is_weak_evidence'], directional:false};
    render(<Mechanism mechanism={body([{drug_ids:['DB00001','DB00002'], status:'shared_substrate_only', explanations:[shared],
      shared_proteins_without_direction:[], recorded_interactions:[]}])} />);
    expect(screen.getByTestId('m03-explanation').textContent).toContain('aynı kan/plazma bağlanma proteinine');
  });
  it('shows a technical error instead of an empty result', () => {
    render(<Mechanism mechanism={null} error="Veritabanına ulaşılamadı." />);
    expect(screen.getByRole('alert').textContent).toContain('Mekanizma kontrolü tamamlanmadı');
  });
});
