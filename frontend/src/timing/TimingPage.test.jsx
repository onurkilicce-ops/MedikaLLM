import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import TimingPage, { Measurement } from './TimingPage';
import Timeline from './Timeline';
import { quantity, safeUrl } from './format';
import { timingRequest } from './client';
import { mechanismRequest } from './mechanismClient';
vi.mock('./client',()=>({timingRequest:vi.fn()}));
// M-03 section is tested in Mechanism.test.jsx; here it answers with an empty result.
vi.mock('./mechanismClient',()=>({mechanismRequest:vi.fn(async()=>({schema_version:'m03-mechanism/1',drugs:[],pairs:[],notice:''}))}));

const source={source_ref:'drugbank:DB00001',source_record_url:'https://go.drugbank.com/drugs/DB00001',source_field:'half_life',
  quote:'[SYNTHETIC] The half-life is 4-6 hours.[A1]',quote_start:0,quote_end:44,value_text:'4-6 hours',value_start:29,value_end:38,
  stored_text_possibly_truncated:false,stored_reference_attributed:false,reference_scope:'sentence_shared',
  inline_reference_tokens:['A1'],nearby_reference_tokens:['A2'],unmatched_reference_tokens:[],
  references:[{ref_id:'A1',title:'Synthetic shared reference',url:'javascript:alert(1)'}]};
const m={measurement_id:'DB00001-hl-1',measure_type:'half_life',hours:{kind:'range',lower:4,upper:6},
  original:{kind:'range',lower:4,upper:6,unit:'hours'},conditions:{route:['oral'],population:['healthy adults']},
  review_required:false,review_reasons:[],approximate:false,source,time_reference:'not_applicable_duration'};
const derived={derived_id:'d1',based_on_measurement_id:m.measurement_id,status:'computed',hours:{kind:'range',lower:20,upper:30},
  assumptions:['Synthetic constant half-life assumption'],interpretation:'Not complete elimination.'};
const drug={requested_id:'DB00001',drug:{name:'[SYNTHETIC] Drug A'},lookup_status:'found',
  data_status:{half_life:'parsed',tmax:'empty'},measurements:[m],derived:[derived],fields:[]};
const other={...drug,requested_id:'DB00002',drug:{name:'[SYNTHETIC] Drug B'},measurements:[],derived:[],
  data_status:{half_life:'unparsed_needs_review',tmax:'empty'},fields:[{source_field:'half_life',stored_text:'[SYNTHETIC] Other drug uncertain.',
    review_items:[{reason:'subject_unresolved',quote:'[SYNTHETIC] Other drug uncertain.',quote_start:0,quote_end:35}]}]};
const search=[{drug_id:'DB00001',name:'[SYNTHETIC] Drug A',profiles:[]},{drug_id:'DB00002',name:'[SYNTHETIC] Drug B',profiles:[]}];
const noAdvice={status:'evaluated',advice:[],coverage:[{item_ids:['DB00001','DB00002'],status:'not_in_catalog',reason:'No matching catalog rule.'}]};
function mount(){return render(<MemoryRouter><TimingPage /></MemoryRouter>);}
async function selectTwo(){
  await screen.findByLabelText(/İlaç adı/);
  fireEvent.change(screen.getByLabelText(/İlaç adı/),{target:{value:'Drug'}});
  fireEvent.click(await screen.findByRole('button',{name:/Ekle:.*Drug A/}));
  fireEvent.change(screen.getByLabelText(/İlaç adı/),{target:{value:'Drug'}});
  fireEvent.click(await screen.findByRole('button',{name:/Ekle:.*Drug B/}));
}
beforeEach(()=>{timingRequest.mockReset();timingRequest.mockImplementation(async path=>path==='compare'?{drugs:[drug,other]}:
  path==='advice'?noAdvice:{items:search,limited:false});});
afterEach(cleanup);

describe('M02 complete screen',()=>{
  it('selects two distinct drugs, compares, opens sources and preserves missing/review states',async()=>{
    mount();await screen.findByLabelText(/İlaç adı/);
    expect(screen.getByRole('button',{name:'Karşılaştır'}).disabled).toBe(true);
    await selectTwo();fireEvent.click(screen.getByRole('button',{name:'Karşılaştır'}));
    await screen.findByText('Değerler ve kaynaklar');
    expect(screen.getAllByTestId('timeline-row')).toHaveLength(2);
    expect(screen.getAllByText(/Tmax: Veri yok/)).toHaveLength(2);
    expect(screen.getByText('İnceleme: subject_unresolved')).toBeTruthy();
    expect(screen.getByText(/kaynakla doğrulanmış zaman aralığı önerisi belirlenemedi/)).toBeTruthy();
    fireEvent.click(screen.getByText('Kaynak metni ve referanslar'));
    expect(screen.getByText(source.quote)).toBeTruthy();
    expect(screen.getByText(/bu değere özgü kaynak olarak kabul edilmedi/)).toBeTruthy();
    expect(screen.queryByRole('link',{name:/Synthetic shared reference/})).toBeNull();
    fireEvent.click(screen.getByRole('button',{name:'[SYNTHETIC] Drug A kaldır'}));
    expect(screen.queryByText('Değerler ve kaynaklar')).toBeNull();
    expect(screen.getByRole('button',{name:'Karşılaştır'}).disabled).toBe(true);
  });
  it.each([401,403,503])('shows access error %s without exposing comparison controls',async status=>{
    timingRequest.mockRejectedValue(Object.assign(new Error(),{status}));mount();
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.queryByRole('button',{name:'Karşılaştır'})).toBeNull();
  });
  it('does not present a failed advice lookup as no evidence',async()=>{
    timingRequest.mockImplementation(async path=>{
      if(path==='advice')throw Object.assign(new Error(),{status:503});
      return path==='compare'?{drugs:[drug,other]}:{items:search,limited:false};
    });mount();await selectTwo();fireEvent.click(screen.getByRole('button',{name:'Karşılaştır'}));
    expect(await screen.findByText(/Öneri kontrolü tamamlanmadı:/)).toBeTruthy();
    expect(screen.queryByText(/kaynakla doğrulanmış zaman aralığı önerisi belirlenemedi/)).toBeNull();
    expect(screen.getByText('Değerler ve kaynaklar')).toBeTruthy();
  });
  it('discards a late response after selection changes',async()=>{
    let resolve;
    timingRequest.mockImplementation(path=>path==='compare'?new Promise(r=>{resolve=r;}):Promise.resolve(path==='advice'?noAdvice:{items:search,limited:false}));
    mount();await selectTwo();fireEvent.click(screen.getByRole('button',{name:'Karşılaştır'}));
    await screen.findByText('Veriler okunuyor…');
    fireEvent.click(screen.getByRole('button',{name:'[SYNTHETIC] Drug A kaldır'}));
    resolve({drugs:[drug,other]});await waitFor(()=>expect(screen.queryByText('Veriler okunuyor…')).toBeNull());
    expect(screen.queryByText('Değerler ve kaynaklar')).toBeNull();
  });
  it('distinguishes an empty search from a failed search',async()=>{
    timingRequest.mockImplementation(async path=>{
      if(path==='drugs?q=broken')throw Object.assign(new Error(),{status:503});
      return {items:[],limited:false};
    });mount();await screen.findByLabelText(/İlaç adı/);
    fireEvent.change(screen.getByLabelText(/İlaç adı/),{target:{value:'empty'}});
    await screen.findByText('Arama sonucu yok.');
    fireEvent.change(screen.getByLabelText(/İlaç adı/),{target:{value:'broken'}});
    await screen.findByRole('alert');
    expect(screen.queryByText('Arama sonucu yok.')).toBeNull();
  });
  it('keeps a failed PK request separate from the independent advice result',async()=>{
    timingRequest.mockImplementation(async path=>{
      if(path==='compare')throw Object.assign(new Error(),{status:503});
      return path==='advice'?noAdvice:{items:search,limited:false};
    });mount();await selectTwo();fireEvent.click(screen.getByRole('button',{name:'Karşılaştır'}));
    await screen.findByRole('alert');
    expect(screen.queryByText('Değerler ve kaynaklar')).toBeNull();
    expect(screen.queryAllByTestId('timeline-row')).toHaveLength(0);
    expect(screen.getByText('Kaynaklı zaman aralığı değerlendirmesi')).toBeTruthy();
  });
  it('shows directional advice with its source and unchanged interval range',async()=>{
    timingRequest.mockImplementation(async path=>path==='advice'?{status:'evaluated',coverage:[],advice:[
      {rule_id:'synthetic',subject_drug_id:'DB00001',other_id:'DB00002',other_name:'Drug B',direction:'before',
       interval_hours:{kind:'range',lower:1,upper:2},conditions:['Synthetic condition'],source:{title:'Synthetic label',url:'https://example.org',excerpt:'[SYNTHETIC] Before statement.',section:'Test',label_updated:'2026-01-01',checked_on:'2026-11-26'}},
      {rule_id:'synthetic',subject_drug_id:'DB00001',other_id:'DB00002',other_name:'Drug B',direction:'after',
       interval_hours:{kind:'lower_bound',lower:4,inclusive:true},conditions:['Synthetic condition'],source:{title:'Synthetic label',url:'https://example.org',excerpt:'[SYNTHETIC] After statement.',section:'Test'}}
    ]}:path==='compare'?{drugs:[drug,other]}:{items:search,limited:false});
    mount();await selectTwo();fireEvent.click(screen.getByRole('button',{name:'Karşılaştır'}));
    expect(await screen.findByText('1–2 sa önce')).toBeTruthy();expect(screen.getByText('≥4 sa sonra')).toBeTruthy();
    expect(screen.getByText('[SYNTHETIC] Before statement.')).toBeTruthy();
  });
});

it('plots ranges on one scale, supports large differences, omits review values',()=>{
  const long={...drug,requested_id:'DB00003',drug:{name:'Long drug'},measurements:[{...m,measurement_id:'long',hours:{kind:'point',value:24000}}],derived:[]};
  const review={...other,measurements:[{...m,measurement_id:'review',review_required:true}],derived:[]};
  render(<Timeline drugs={[drug,long,review]}/>);
  expect(screen.getAllByTestId('timeline-row')).toHaveLength(3);
  expect(screen.getByText('4–6 sa')).toBeTruthy();expect(screen.getByText('≈ 20–30 sa')).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Ölçek'),{target:{value:'log'}});
  expect(screen.getByRole('img',{name:'Logaritmik saat ekseni'})).toBeTruthy();
});
it('keeps mixed original units, bounds, nulls and rejects executable URLs',()=>{
  expect(quantity({kind:'range',lower:30,upper:1,lower_unit:'min'},'hours')).toBe('30 min–1 hours');
  expect(quantity(null)).toBe('—');expect(safeUrl('javascript:alert(1)')).toBeNull();
});

describe('M03 on the M-02 screen',()=>{
  it('M03: a hanging mechanism request never delays or hides the M-02 results',async()=>{
    mechanismRequest.mockImplementationOnce(()=>new Promise(()=>{}));
    mount();await selectTwo();fireEvent.click(screen.getByRole('button',{name:'Karşılaştır'}));
    expect(await screen.findByText('Değerler ve kaynaklar')).toBeTruthy();
    expect(screen.getByText('Kaynaklı zaman aralığı değerlendirmesi')).toBeTruthy();
    expect(screen.getByText('Organ ve protein verileri okunuyor…')).toBeTruthy();
    expect(screen.getByRole('button',{name:'Karşılaştır'}).disabled).toBe(false);
  });
  it('M03: a failed mechanism request is a technical error next to intact M-02 results',async()=>{
    mechanismRequest.mockImplementationOnce(async()=>{throw Object.assign(new Error(),{status:503});});
    mount();await selectTwo();fireEvent.click(screen.getByRole('button',{name:'Karşılaştır'}));
    expect(await screen.findByText(/Mekanizma kontrolü tamamlanmadı/)).toBeTruthy();
    expect(screen.getByText('Değerler ve kaynaklar')).toBeTruthy();
  });
  it('M03: one selected drug can open its organ/protein profile without an M-02 comparison',async()=>{
    mount();await screen.findByLabelText(/İlaç adı/);
    fireEvent.change(screen.getByLabelText(/İlaç adı/),{target:{value:'Drug'}});
    fireEvent.click(await screen.findByRole('button',{name:/Ekle:.*Drug A/}));
    expect(screen.getByRole('button',{name:'Karşılaştır'}).disabled).toBe(true);
    fireEvent.click(screen.getByRole('button',{name:'Organ ve protein profilini göster (M-03)'}));
    await waitFor(()=>expect(mechanismRequest).toHaveBeenCalledWith(['DB00001'], expect.anything()));
    expect(await screen.findByTestId('m03-mechanism')).toBeTruthy();
    expect(screen.queryByText('Değerler ve kaynaklar')).toBeNull();
  });
});
