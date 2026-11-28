import React, { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { timingRequest } from './client';
import { mechanismRequest } from './mechanismClient';
import { quantity, conditionText, httpError, safeUrl, fieldStatus, num } from './format';
import Timeline from './Timeline';
import Mechanism from './Mechanism';
import FoodTable from './FoodTable';
import './timing.css';

function SourceLink({url, children}) {
  const safe = safeUrl(url);
  return safe ? <a href={safe} target="_blank" rel="noopener noreferrer">{children}</a> : <span>{children} (bağlantı yok)</span>;
}

export function Measurement({m, derived}) {
  const source = m.source;
  return <article className={`m02-measure ${m.review_required ? 'm02-review' : ''}`} id={`m02-${m.measurement_id}`}>
    <h4>{m.measure_type === 'tmax' ? 'Tmax' : 'Yarı ömür'}: {m.approximate ? '≈ ' : ''}{quantity(m.hours)}
      {m.dispersion && ` ± ${num(m.dispersion.value_hours)} sa (yayılım türü belirtilmemiş)`}</h4>
    <p>Özgün değer: {quantity(m.original, m.original.unit)}{m.original.lower_unit ? ` (alt sınır birimi: ${m.original.lower_unit})` : ''}</p>
    <p>{conditionText(m.conditions)}</p>
    {m.review_required && <p><strong>İnceleme gerekli:</strong> {m.review_reasons.join(', ')}</p>}
    {derived && (derived.status === 'computed' ? <p><strong>Hesaplanan ≈5×: {quantity(derived.hours)}</strong>
      {derived.dispersion && ` ± ${num(derived.dispersion.value_hours)} sa (istatistik türü belirtilmemiş)`}</p>
      : <p>≈5× hesaplanmadı: {derived.not_computed_reasons.join(', ')}</p>)}
    {derived && <details><summary>Hesabın varsayımları ve sınırları</summary><p>{derived.interpretation}</p>
      <ul>{derived.assumptions.map(a => <li key={a}>{a}</li>)}</ul></details>}
    <details><summary>Kaynak metni ve referanslar</summary>
      <blockquote>{source.quote}</blockquote>
      <p><SourceLink url={source.source_record_url}>{source.source_ref}</SourceLink> · {source.source_field} · metin konumu [{source.quote_start}, {source.quote_end})</p>
      <p>Okunan bölüm: “{source.value_text}” [{source.value_start}, {source.value_end})</p>
      {source.stored_text_possibly_truncated && <p>Kaydedilmiş metin kesilmiş olabilir.</p>}
      <p>{source.stored_reference_attributed ? 'Belirteç aynı ilacın saklı referansıyla eşleşti; dış kaynağın bu değeri doğruladığı ayrıca denetlenmedi.'
        : 'Değere özgü, doğrulanmış dış kaynak eşlemesi yok.'}</p>
      <p>Atıf kapsamı: {source.reference_scope}. Belirteçler: {source.inline_reference_tokens.join(', ') || 'yok'}.</p>
      {source.references.length > 0 && <ul>{source.references.map((r,i) => <li key={`${r.ref_id}-${i}`}>
        <SourceLink url={r.url || (r.pubmed_id ? `https://pubmed.ncbi.nlm.nih.gov/${r.pubmed_id}/` : null)}>
          {r.ref_id}: {r.title || r.citation || 'Saklı referans'}</SourceLink>
        {!source.stored_reference_attributed && ' — bu değere özgü kaynak olarak kabul edilmedi'}
      </li>)}</ul>}
      <p>Yakındaki diğer belirteçler (bu değerin kaynağı değildir): {source.nearby_reference_tokens.join(', ') || 'yok'}.</p>
      <p>Eşleşmeyen belirteçler: {source.unmatched_reference_tokens.join(', ') || 'yok'}.</p>
    </details>
  </article>;
}

export default function TimingPage() {
  const [query,setQuery] = useState('');
  const [items,setItems] = useState([]);
  const [limited,setLimited] = useState(false);
  const [searching,setSearching] = useState(false);
  const [searchError,setSearchError] = useState('');
  const [access,setAccess] = useState('checking');
  const [accessError,setAccessError] = useState('');
  const [selected,setSelected] = useState([]);
  const [result,setResult] = useState(null);
  const [table,setTable] = useState(null);
  const [error,setError] = useState('');
  const [tableError,setTableError] = useState('');
  const [tableBusy,setTableBusy] = useState(false);
  const [mechanism,setMechanism] = useState(null);
  const [mechanismError,setMechanismError] = useState('');
  const [mechanismBusy,setMechanismBusy] = useState(false);
  const [busy,setBusy] = useState(false);
  const requestRef = useRef(null);
  const revision = useRef(0);
  const [accessAttempt,setAccessAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setAccess('checking'); setAccessError('');
    timingRequest('drugs?q=DB', null, controller.signal).then(() => setAccess('ready')).catch(e => {
      if (e.name !== 'AbortError') { setAccess('denied'); setAccessError(httpError(e)); }
    });
    return () => controller.abort();
  }, [accessAttempt]);
  useEffect(() => {
    const controller = new AbortController();
    setItems([]); setSearchError(''); setLimited(false); setSearching(false);
    if (query.trim().length < 2 || access !== 'ready') return () => controller.abort();
    setSearching(true);
    const timer = setTimeout(async () => {
      setSearching(true);
      try {
        const data = await timingRequest(`drugs?q=${encodeURIComponent(query.trim())}`, null, controller.signal);
        if (!controller.signal.aborted) { setItems(data.items); setLimited(data.limited); }
      } catch(e) { if (!controller.signal.aborted) setSearchError(httpError(e)); }
      finally { if (!controller.signal.aborted) setSearching(false); }
    }, 250);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [query, access]);
  useEffect(() => () => requestRef.current?.abort(), []);

  function invalidate() {
    revision.current += 1; requestRef.current?.abort();
    setResult(null); setTable(null); setError(''); setTableError(''); setTableBusy(false); setMechanism(null); setMechanismError(''); setMechanismBusy(false); setBusy(false);
  }
  function add(item) {
    if (selected.length >= 10 || selected.some(x => x.drug_id === item.drug_id)) return;
    invalidate(); setSelected([...selected,item]); setQuery('');
  }
  function remove(id) {
    invalidate(); setSelected(selected.filter(x => x.drug_id !== id));
  }
  function loadTable(drug_ids, controller, current) {
    setTableBusy(true);
    timingRequest('table', {drug_ids}, controller.signal).then(value => {
      if (controller.signal.aborted || revision.current !== current) return;
      if (value?.schema_version === 'm02-timing-table/1') setTable(value); else setTableError(httpError({}));
    }, reason => { if (!controller.signal.aborted && revision.current === current) setTableError(httpError(reason)); })
      .finally(() => { if (revision.current === current) setTableBusy(false); });
  }
  // one drug: its timing table and organ/protein profile (the M-02 comparison needs two drugs)
  function profileOnly() {
    invalidate(); const current = revision.current;
    const controller = new AbortController(); requestRef.current = controller; setMechanismBusy(true);
    loadTable(selected.map(x => x.drug_id), controller, current);
    mechanismRequest(selected.map(x => x.drug_id), controller.signal).then(value => {
      if (controller.signal.aborted || revision.current !== current) return;
      if (value?.schema_version === 'm03-mechanism/1') setMechanism(value); else setMechanismError(httpError({}));
    }, reason => { if (!controller.signal.aborted && revision.current === current) setMechanismError(httpError(reason)); })
      .finally(() => { if (revision.current === current) setMechanismBusy(false); });
  }
  async function compare() {
    invalidate(); const current = revision.current;
    const controller = new AbortController(); requestRef.current = controller; setBusy(true);
    const drug_ids = selected.map(x => x.drug_id);
    loadTable(drug_ids, controller, current);
    // M-03 is independent: it never delays or hides the M-02 results.
    setMechanismBusy(true);
    mechanismRequest(drug_ids, controller.signal).then(value => {
      if (controller.signal.aborted || revision.current !== current) return;
      // only an m03 contract is rendered; anything else is a technical error, never an empty 'no proteins'
      if (value?.schema_version === 'm03-mechanism/1') setMechanism(value); else setMechanismError(httpError({}));
    }, reason => {
      if (controller.signal.aborted || revision.current !== current) return;
      setMechanismError(httpError(reason));
    }).finally(() => { if (revision.current === current) setMechanismBusy(false); });
    const [pk] = await Promise.allSettled([timingRequest('compare', {drug_ids}, controller.signal)]);
    if (controller.signal.aborted || revision.current !== current) return;
    if (pk.status === 'fulfilled') setResult(pk.value); else setError(httpError(pk.reason));
    setBusy(false);
  }
  return <main className="m02-page">
    <header className="m02-header"><div><p className="m02-eyebrow">MedicaLLM · M-02 / M-03</p><h1>İlaç zamanlaması ve mekanizma</h1>
      <p>İlaçları seçin: neyle ve ne zaman alınacağı tek tabloda; süreler, organlar ve proteinler altında.</p></div>
      <Link to="/chat">Panele dön</Link></header>
    <p className="m02-note">Sağlık profesyonelleri için karar desteği. Doz hesabı veya kişisel kullanım takvimi üretmez.</p>
    {access === 'checking' && <p role="status">Erişim kontrol ediliyor…</p>}
    {access === 'denied' && <div role="alert"><p>{accessError}</p><Link to="/login">Giriş yap</Link> <button onClick={() => setAccessAttempt(x=>x+1)}>Yeniden dene</button></div>}
    {access === 'ready' && <>
      <section className="m02-card"><h2>1. İlaçları seçin</h2>
        <label htmlFor="m02-search">İlaç adı, eş adı veya DrugBank kimliği (en az 2 karakter)</label>
        <input id="m02-search" value={query} maxLength={100} onChange={e=>setQuery(e.target.value)} autoComplete="off" />
        {searching && <p role="status">Aranıyor…</p>}
        {searchError && <p role="alert">{searchError}</p>}
        {query.trim().length >= 2 && !searching && !searchError && items.length === 0 && <p>Arama sonucu yok.</p>}
        <ul className="m02-search-results">{items.map(item => <li key={item.drug_id}>
          <button disabled={selected.length>=10 || selected.some(x=>x.drug_id===item.drug_id)} onClick={()=>add(item)}>
            Ekle: {item.name} · {item.drug_id}</button></li>)}</ul>
        {limited && <p>İlk 20 sonuç gösteriliyor. Aramayı daraltın.</p>}
        <p>{selected.length}/10 ilaç seçildi. Karşılaştırma için en az 2 farklı ilaç gerekir.</p>
        <div className="m02-chips">{selected.map(item => <span className="m02-chip" key={item.drug_id}>
          <strong>{item.name}</strong> · {item.drug_id} <button onClick={()=>remove(item.drug_id)} aria-label={`${item.name} kaldır`}>Kaldır</button></span>)}</div>
        <button className="m02-primary" disabled={selected.length<2 || busy} onClick={compare}>{busy?'Karşılaştırılıyor…':'Karşılaştır'}</button>
        {selected.length===1 && <button onClick={profileOnly} disabled={mechanismBusy}>Organ ve protein profilini göster (M-03)</button>}
        {selected.length===1 && <p><small>Tek ilaç için de “neyle, ne zaman” tablosu ve organ/protein profili gösterilir.</small></p>}
        {busy && <p role="status">Veriler okunuyor…</p>}
        {error && <p role="alert">{error}</p>}
      </section>
      {(table || tableError || tableBusy) && <FoodTable table={table} error={tableError} busy={tableBusy} />}
      {result && <>
        <Timeline drugs={result.drugs} />
        <section className="m02-card"><details><summary><h2 className="m02-inline">Değerler ve kaynaklar</h2> (ayrıntı)</summary>
          {result.drugs.map(d => <section key={d.requested_id} className="m02-drug-card"><h3>{d.drug?.name || d.requested_id}</h3>
            {d.lookup_status === 'not_found' ? <p>İlaç kaydı bulunamadı; kontrol tamamlanamadı.</p> : <>
              <p>Tmax: {fieldStatus[d.data_status.tmax]} · Yarı ömür: {fieldStatus[d.data_status.half_life]}</p>
              {d.measurements.map(m=><Measurement key={m.measurement_id} m={m} derived={d.derived.find(x=>x.based_on_measurement_id===m.measurement_id)} />)}
              {d.fields.map(f=><details className="m02-field" key={f.source_field}><summary>{f.source_field}: saklı metin ve inceleme kalemleri ({f.review_items.length})</summary>
                <blockquote>{f.stored_text || 'Saklı metin yok.'}</blockquote>
                {f.stored_text_possibly_truncated && <p>Kaynak metni kaydedilirken kesilmiş olabilir.</p>}
                {f.review_items.map((x,i)=><article className="m02-review" key={i}><strong>İnceleme: {x.reason}</strong><blockquote>{x.quote}</blockquote>
                  <p>Konum [{x.quote_start}, {x.quote_end}). {x.value_text || ''}</p></article>)}
              </details>)}
            </>}
          </section>)}
          <p>Eksik değerler sıfır değildir. “Kayıt yok”, “güvenli” anlamına gelmez.</p>
        </details></section>
      </>}
      {mechanismBusy && !mechanism && !mechanismError && <p role="status">Organ ve protein verileri okunuyor…</p>}
      {(mechanism || mechanismError) && <Mechanism mechanism={mechanism} error={mechanismError} />}
    </>}
  </main>;
}
