/** React DOM -> real fetch -> real router/auth/service -> synthetic PostgreSQL.
 * This is a jsdom integration test, not a visual browser acceptance test.
 * Requires scripts/m02_synthetic_demo.py on 127.0.0.1:18102, freshly seeded.
 */
import React from 'react';
import { beforeEach, afterEach, describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import TimingPage from '../src/timing/TimingPage';

vi.mock('../src/api/config',()=>({ default:{API_URL:'http://127.0.0.1:18102'} }));
const ROOT='http://127.0.0.1:18102';
async function login(who='doctor.a') {
  const r=await fetch(`${ROOT}/api/auth/login`,{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({email:`synthetic.${who}@synthetic-medicallm.org`,password:'Synth-Pass-1!'})});
  expect(r.status).toBe(200);
  const data=await r.json();
  localStorage.setItem('token',data.token);
  localStorage.setItem('user',JSON.stringify(data.user));
}
function mount(){render(<MemoryRouter><TimingPage/></MemoryRouter>);}
async function add(name){
  fireEvent.change(await screen.findByLabelText(/İlaç adı/),{target:{value:name}});
  fireEvent.click(await screen.findByRole('button',{name:new RegExp(`Ekle:.*${name}`)}, {timeout:10000}));
}
async function compare(){
  fireEvent.click(screen.getByRole('button',{name:'Karşılaştır'}));
  await screen.findByText('Değerler ve kaynaklar',{}, {timeout:15000});
  await screen.findByText('Kaynaklı zaman aralığı değerlendirmesi');
}
beforeEach(()=>localStorage.clear());
afterEach(cleanup);

describe('M02 live synthetic flow',()=>{
  it('selects drugs, reads PG values, preserves ranges and opens the actual source',async()=>{
    await login();mount();await add('Ciprofloxacin');await add('Sucralfate');await compare();
    expect(screen.getAllByTestId('timeline-row')).toHaveLength(5);
    expect(screen.getAllByText(/0,5–1 sa/).length).toBeGreaterThan(0);
    expect(screen.getByText('Hesaplanan ≈5×: 20–30 sa')).toBeTruthy();
    fireEvent.click(screen.getAllByText('Kaynak metni ve referanslar')[1]);
    expect(screen.getAllByText('[SYNTHETIC] The half-life is 4-6 hours.[A900001]').length).toBeGreaterThan(0);
    expect(screen.getByText(/Ürün\/koşul doğrulaması gerekli/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText('[SYNTHETIC] Ciprofloxacin ürün koşulu'),{target:{value:'cipro_uk_tablet'}});
    fireEvent.change(screen.getByLabelText('[SYNTHETIC] Sucralfate ürün koşulu'),{target:{value:'sucralfate_oral'}});
    await compare();
    expect(screen.getByText('1–2 sa önce')).toBeTruthy();expect(screen.getByText('≥4 sa sonra')).toBeTruthy();
    expect(screen.getAllByRole('link',{name:/Ciprofloxacin 500 mg film-coated/})[0].href).toContain('/4346/smpc');
    fireEvent.click(screen.getByRole('button',{name:'[SYNTHETIC] Sucralfate kaldır'}));
    expect(screen.queryByText('Değerler ve kaynaklar')).toBeNull();
    expect(screen.getByRole('button',{name:'Karşılaştır'}).disabled).toBe(true);
  });
  it('M03: shows organs, proteins and the shared-enzyme explanation from PG',async()=>{
    await login();mount();await add('Ciprofloxacin');await add('Uncertain agent');await compare();
    const section=await screen.findByTestId('m03-mechanism',{}, {timeout:15000});
    expect(section.textContent).toContain('Böbrek (idrar)');
    expect(section.textContent).toContain('Safra / dışkı');
    expect(section.textContent).toContain('[SYNTHETIC] About 50% is excreted unchanged in urine and 15% in feces.');
    expect(section.textContent).not.toContain('metindeki pay');
    const text=screen.getByTestId('m03-explanation').textContent;
    expect(text).toContain('[SYNTHETIC] Ciprofloxacin, [SYNTHETIC] Uncertain agent ilacını işleyen [SYNTHETIC] Cytochrome P450 1A2 enzimini yavaşlatır');
    expect(text).toContain('kanda birikebilir');
    expect(section.textContent).toContain('The metabolism of Uncertain agent can be decreased');
  });
  it('M03: one drug opens its organ/protein profile from PG',async()=>{
    await login();mount();await add('Ciprofloxacin');
    fireEvent.click(screen.getByRole('button',{name:'Organ ve protein profilini göster (M-03)'}));
    const section=await screen.findByTestId('m03-mechanism',{}, {timeout:15000});
    expect(section.textContent).toContain('[SYNTHETIC] Cytochrome P450 1A2');
    expect(section.textContent).toContain('yavaşlatır (inhibitör)');
    expect(screen.queryAllByTestId('m03-pair')).toHaveLength(0);
  });
  it('keeps an unresolved subject and an empty record out of the timeline',async()=>{
    await login();mount();await add('Uncertain agent');await add('Empty agent');await compare();
    expect(screen.queryAllByTestId('timeline-row')).toHaveLength(0);
    expect(screen.getByText('İnceleme: subject_unresolved')).toBeTruthy();
    expect(screen.getByText(/Tmax: Veri yok · Yarı ömür: Veri yok/)).toBeTruthy();
    expect(screen.getByText(/Bu katalogda kaynaklı zaman aralığı bulunamadı/)).toBeTruthy();
  });
  it('shows sourced food timing only for the matching formulation and meal context',async()=>{
    await login();mount();await add('Ciprofloxacin');await add('Empty agent');
    fireEvent.change(screen.getByLabelText('[SYNTHETIC] Ciprofloxacin ürün koşulu'),{target:{value:'ciproxin_uk_suspension'}});
    fireEvent.click(screen.getByLabelText('Süt/yoğurt — öğün dışında tek başına'));
    await compare();
    expect(screen.getByText('1–2 sa önce')).toBeTruthy();expect(screen.getByText('≥4 sa sonra')).toBeTruthy();
    expect(screen.getAllByRole('link',{name:/Ciproxin 250 mg\/5 mL/})[0].href).toContain('/885/smpc');
    fireEvent.click(screen.getByLabelText('Süt/yoğurt — öğün dışında tek başına'));
    fireEvent.click(screen.getByLabelText('Öğünün parçası olan süt ürünü'));await compare();
    expect(screen.queryByText('1–2 sa önce')).toBeNull();
    expect(screen.getByText(/Bu koşula uygulanmıyor/)).toBeTruthy();
  });
  it('does not invent the reverse breakfast interval',async()=>{
    await login();mount();await add('Levothyroxine');await add('Empty agent');
    fireEvent.change(screen.getByLabelText('[SYNTHETIC] Levothyroxine ürün koşulu'),{target:{value:'levothyroxine_us_tablet'}});
    fireEvent.click(screen.getByLabelText('Kahvaltı (aç karnına, öncesi)'));await compare();
    expect(screen.getByText('0,5–1 sa önce')).toBeTruthy();
    expect(screen.queryByText(/sa sonra$/)).toBeNull();
  });
  it('rejects a real patient token at the professional screen',async()=>{
    await login('patient2');mount();
    expect(await screen.findByText(/sağlık profesyoneli hesabı gerekiyor/)).toBeTruthy();
    expect(screen.queryByLabelText(/İlaç adı/)).toBeNull();
  });
  it('shows an expired/invalid session instead of empty data',async()=>{
    localStorage.setItem('token','invalid-synthetic-token');mount();
    expect(await screen.findByText(/Oturum geçersiz/)).toBeTruthy();
    expect(screen.queryByLabelText(/İlaç adı/)).toBeNull();
  });
});
