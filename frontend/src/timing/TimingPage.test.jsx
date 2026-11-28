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
const cell=(o)=>({kind:'separate',text:'Antasitlerden ayrı alın',timing_text:'≥2 sa önce veya ≥2 sa sonra',before:null,after:null,
  source:'drugbank',source_text:'[SYNTHETIC] Take separate from antacids. Take at least 2 hours before or after antacids.',
  timing_quote:'[SYNTHETIC] Take at least 2 hours before or after antacids.',source_ref:'',source_url:'',product:'',with_drug_id:'',...o});
const tableBody={schema_version:'m02-timing-table/1',notice:'[SYNTHETIC] notice',
  drugs:[{requested_id:'DB00001',drug_id:'DB00001',name:'[SYNTHETIC] Drug A',found:true,has_food_entries:true},
         {requested_id:'DB00002',drug_id:'DB00002',name:'[SYNTHETIC] Drug B',found:true,has_food_entries:false}],
  rows:[{row_id:'minerals_antacids',label:'Antasit, demir, mineraller ve bağlayıcılar',cells:{DB00001:[cell({})]}},
        {row_id:'meal',label:'Yemek (aç / tok)',cells:{DB00001:[cell({kind:'take_without',text:'Aç karnına alın',timing_text:'0,5–1 sa önce'})]}}]};
function mount(){return render(<MemoryRouter><TimingPage /></MemoryRouter>);}
async function selectTwo(){
  await screen.findByLabelText(/İlaç adı/);
  fireEvent.change(screen.getByLabelText(/İlaç adı/),{target:{value:'Drug'}});
  fireEvent.click(await screen.findByRole('button',{name:/Ekle:.*Drug A/}));
  fireEvent.change(screen.getByLabelText(/İlaç adı/),{target:{value:'Drug'}});
  fireEvent.click(await screen.findByRole('button',{name:/Ekle:.*Drug B/}));
}
beforeEach(()=>{timingRequest.mockReset();timingRequest.mockImplementation(async path=>path==='compare'?{drugs:[drug,other]}:
  path==='table'?tableBody:{items:search,limited:false});});
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
    expect(screen.getByTestId('food-table')).toBeTruthy();
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
  it('does not present a failed table request as no information',async()=>{
    timingRequest.mockImplementation(async path=>{
      if(path==='table')throw Object.assign(new Error(),{status:503});
      return path==='compare'?{drugs:[drug,other]}:{items:search,limited:false};
    });mount();await selectTwo();fireEvent.click(screen.getByRole('button',{name:'Karşılaştır'}));
    expect(await screen.findByText(/Zamanlama tablosu okunamadı:/)).toBeTruthy();
    expect(screen.queryByText(/besin veya zamanlama bilgisi yok/)).toBeNull();
    expect(await screen.findByText('Değerler ve kaynaklar')).toBeTruthy();
  });
  it('discards a late response after selection changes',async()=>{
    let resolve;
    timingRequest.mockImplementation(path=>path==='compare'?new Promise(r=>{resolve=r;}):Promise.resolve(path==='table'?tableBody:{items:search,limited:false}));
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
  it('keeps a failed PK request separate from the independent timing table',async()=>{
    timingRequest.mockImplementation(async path=>{
      if(path==='compare')throw Object.assign(new Error(),{status:503});
      return path==='table'?tableBody:{items:search,limited:false};
    });mount();await selectTwo();fireEvent.click(screen.getByRole('button',{name:'Karşılaştır'}));
    await screen.findByRole('alert');
    expect(screen.queryByText('Değerler ve kaynaklar')).toBeNull();
    expect(screen.queryAllByTestId('timeline-row')).toHaveLength(0);
    expect(await screen.findByTestId('food-table')).toBeTruthy();
  });
  it('shows one table: rows are foods/situations, columns are drugs, times in bold, source on demand',async()=>{
    mount();await selectTwo();fireEvent.click(screen.getByRole('button',{name:'Karşılaştır'}));
    const t=await screen.findByTestId('food-table');
    const heads=[...t.querySelectorAll('thead th')].map(x=>x.textContent);
    expect(heads[1]).toContain('[SYNTHETIC] Drug A'); expect(heads[2]).toContain('(DrugBank besin kaydı yok)');
    const rows=[...t.querySelectorAll('tbody tr')].map(r=>r.querySelector('th').textContent);
    expect(rows).toEqual(['Antasit, demir, mineraller ve bağlayıcılar','Yemek (aç / tok)']);
    expect(screen.getByText('≥2 sa önce veya ≥2 sa sonra')).toBeTruthy();
    expect(screen.getByText('0,5–1 sa önce')).toBeTruthy();
    expect(t.querySelectorAll('tbody tr')[0].querySelectorAll('td')[1].textContent).toBe('—');
    expect(screen.queryByText(/Take at least 2 hours before or after antacids/)).toBeNull();
    // every source button names its row and drug, and points at the quote it opens
    const btn=screen.getByRole('button',{name:'Kaynak: Antasit, demir, mineraller ve bağlayıcılar — [SYNTHETIC] Drug A'});
    expect(screen.getByRole('button',{name:'Kaynak: Yemek (aç / tok) — [SYNTHETIC] Drug A'})).toBeTruthy();
    fireEvent.click(btn);
    expect(btn.getAttribute('aria-expanded')).toBe('true');
    expect(document.getElementById(btn.getAttribute('aria-controls')).textContent)
      .toMatch(/Take at least 2 hours before or after antacids/);
    expect(screen.queryByText(/ürün\/koşul doğrulaması gerekli/)).toBeNull();
    expect(screen.queryByRole('combobox',{name:/ürün koşulu/})).toBeNull();
  });
  it('reports a drug without a record as missing, not as "no food information"',async()=>{
    const onlyMissing={...tableBody,rows:[],drugs:[{requested_id:'DB00002',drug_id:null,name:null,found:false,has_food_entries:false}]};
    timingRequest.mockImplementation(async path=>path==='table'?onlyMissing:path==='compare'?{drugs:[drug,other]}:{items:search,limited:false});
    mount();await selectTwo();fireEvent.click(screen.getByRole('button',{name:'Karşılaştır'}));
    expect((await screen.findByTestId('food-missing')).textContent).toContain('İlaç kaydı bulunamadı: DB00002');
    expect(screen.queryByText(/kayıtlarında besin veya zamanlama bilgisi yok/)).toBeNull();
  });
  it('marks a missing drug column as "kayıt yok" instead of an empty dash',async()=>{
    const mixed={...tableBody,drugs:[tableBody.drugs[0],{requested_id:'DB00002',drug_id:null,name:null,found:false,has_food_entries:false}]};
    timingRequest.mockImplementation(async path=>path==='table'?mixed:path==='compare'?{drugs:[drug,other]}:{items:search,limited:false});
    mount();await selectTwo();fireEvent.click(screen.getByRole('button',{name:'Karşılaştır'}));
    const t=await screen.findByTestId('food-table');
    expect(t.querySelectorAll('tbody tr')[0].querySelectorAll('td')[1].textContent).toBe('kayıt yok');
    expect(screen.getByTestId('food-missing').textContent).toContain('DB00002');
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
    expect(await screen.findByTestId('food-table')).toBeTruthy();
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
    expect(timingRequest).toHaveBeenCalledWith('table', {drug_ids:['DB00001']}, expect.anything());
    expect(await screen.findByTestId('food-table')).toBeTruthy();
    expect(screen.queryByText('Değerler ve kaynaklar')).toBeNull();
  });
});
