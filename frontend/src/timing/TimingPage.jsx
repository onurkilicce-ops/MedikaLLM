import React, { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { timingRequest } from './client';
import { quantity, conditionText, httpError, safeUrl, fieldStatus, coverageStatus } from './format';
import Timeline from './Timeline';
import './timing.css';

const foods = {breakfast:'Kahvaltı (aç karnına, öncesi)', dairy_alone:'Süt/yoğurt — öğün dışında tek başına',
  calcium_drink_alone:'Kalsiyumla zenginleştirilmiş içecek — öğün dışında', dairy_in_meal:'Öğünün parçası olan süt ürünü'};

function SourceLink({url, children}) {
  const safe = safeUrl(url);
  return safe ? <a href={safe} target="_blank" rel="noopener noreferrer">{children}</a> : <span>{children} (bağlantı yok)</span>;
}

export function Measurement({m, derived}) {
  const source = m.source;
  return <article className={`m02-measure ${m.review_required ? 'm02-review' : ''}`} id={`m02-${m.measurement_id}`}>
    <h4>{m.measure_type === 'tmax' ? 'Tmax' : 'Yarı ömür'}: {m.approximate ? '≈ ' : ''}{quantity(m.hours)}
      {m.dispersion && ` ± ${m.dispersion.value_hours} sa (yayılım türü belirtilmemiş)`}</h4>
    <p>Özgün değer: {quantity(m.original, m.original.unit)}{m.original.lower_unit ? ` (alt sınır birimi: ${m.original.lower_unit})` : ''}</p>
    <p>{conditionText(m.conditions)}</p>
    {m.review_required && <p><strong>İnceleme gerekli:</strong> {m.review_reasons.join(', ')}</p>}
    {derived && (derived.status === 'computed' ? <p><strong>Hesaplanan ≈5×: {quantity(derived.hours)}</strong>
      {derived.dispersion && ` ± ${derived.dispersion.value_hours} sa (istatistik türü belirtilmemiş)`}</p>
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
  const [contexts,setContexts] = useState({});
  const [selectedFoods,setFoods] = useState([]);
  const [result,setResult] = useState(null);
  const [advice,setAdvice] = useState(null);
  const [error,setError] = useState('');
  const [adviceError,setAdviceError] = useState('');
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
    setResult(null); setAdvice(null); setError(''); setAdviceError(''); setBusy(false);
  }
  function add(item) {
    if (selected.length >= 10 || selected.some(x => x.drug_id === item.drug_id)) return;
    invalidate(); setSelected([...selected,item]); setQuery('');
  }
  function remove(id) {
    invalidate(); setSelected(selected.filter(x => x.drug_id !== id));
    setContexts(Object.fromEntries(Object.entries(contexts).filter(([key]) => key !== id)));
  }
  async function compare() {
    invalidate(); const current = revision.current;
    const controller = new AbortController(); requestRef.current = controller; setBusy(true);
    const drug_ids = selected.map(x => x.drug_id);
    const body = {drug_ids, contexts:Object.entries(contexts).filter(([,v]) => v).map(([drug_id,profile_id]) => ({drug_id,profile_id})), foods:selectedFoods};
    const [pk, intervals] = await Promise.allSettled([
      timingRequest('compare', {drug_ids}, controller.signal), timingRequest('advice', body, controller.signal),
    ]);
    if (controller.signal.aborted || revision.current !== current) return;
    if (pk.status === 'fulfilled') setResult(pk.value); else setError(httpError(pk.reason));
    if (intervals.status === 'fulfilled') setAdvice(intervals.value); else setAdviceError(httpError(intervals.reason));
    setBusy(false);
  }
  return <main className="m02-page">
    <header className="m02-header"><div><p className="m02-eyebrow">MedicaLLM · M-02</p><h1>İlaç zamanlaması</h1>
      <p>Kaynak metinleriyle süreleri karşılaştırın; uygun ürün koşullarında kaynaklı zamanlama önerilerini inceleyin.</p></div>
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
        {selected.map(item => <div className="m02-selection" key={item.drug_id}>
          <div><strong>{item.name}</strong> · {item.drug_id} <button onClick={()=>remove(item.drug_id)} aria-label={`${item.name} kaldır`}>Kaldır</button></div>
          {item.profiles.length > 0 ? <label>Öneri için ürün koşulu — yalnız gerçekten eşleşiyorsa seçin
            <select aria-label={`${item.name} ürün koşulu`} value={contexts[item.drug_id] || ''} onChange={e=>{invalidate();setContexts({...contexts,[item.drug_id]:e.target.value});}}>
              <option value="">Bilinmiyor / eşleşmiyor</option>{item.profiles.map(p=><option key={p.profile_id} value={p.profile_id}>{p.label}</option>)}
            </select></label> : <p>Bu ilaç için mevcut öneri kataloğunda ürün profili yok. Süreler yine karşılaştırılabilir.</p>}
        </div>)}
      </section>
      <section className="m02-card"><h2>2. Zamanlama koşullarını belirtin</h2>
        <p>Gıda seçmek, hastanın bunu tükettiğini kaydetmez. Bu sorgu hiçbir hasta veya ilaç kaydını değiştirmez.</p>
        <fieldset><legend>Değerlendirilecek gıda/öğün</legend>{Object.entries(foods).map(([id,label]) => <label className="m02-checkbox" key={id}>
          <input type="checkbox" checked={selectedFoods.includes(id)} onChange={e=>{invalidate();setFoods(e.target.checked?[...selectedFoods,id]:selectedFoods.filter(x=>x!==id));}} />{label}</label>)}</fieldset>
        <p>Öneri kataloğu sınırlıdır: belirli UK/US ürün etiketlerini kapsar. Bunların Türkiye’deki ürünle eşdeğerliği varsayılmaz.
          Ürün seçimi, kaynakta belirtilen uygulama yolu ve formülasyonu doğruladığınız anlamına gelir.</p>
        <button className="m02-primary" disabled={selected.length<2 || busy} onClick={compare}>{busy?'Karşılaştırılıyor…':'Karşılaştır'}</button>
        {busy && <p role="status">Veriler okunuyor…</p>}
        {error && <p role="alert">{error}</p>}
      </section>
      {result && <>
        <Timeline drugs={result.drugs} />
        <section className="m02-card"><h2>Değerler ve kaynaklar</h2>
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
        </section>
      </>}
      {(advice || adviceError) && <section className="m02-card"><h2>Kaynaklı zaman aralığı değerlendirmesi</h2>
        <p>Bu bölüm, Tmax veya yarı ömürden hesaplanmaz. Zaman ayırmak bütün etkileşimleri çözmez; uzman değerlendirmesi gerekir.</p>
        {adviceError && <p role="alert">Öneri kontrolü tamamlanmadı: {adviceError}</p>}
        {advice && <><p>Durum: {advice.status === 'evaluated' ? 'Seçilen kapsam katalogda değerlendirildi' : advice.status === 'partially_evaluated' ? 'Kısmen değerlendirildi' : 'Koşullar eksik; değerlendirme tamamlanmadı'}.</p>
          {advice.advice.length===0 && <p>Bu durumda kaynakla doğrulanmış zaman aralığı önerisi belirlenemedi. Bu, etkileşim olmadığı veya birlikte kullanılabileceği anlamına gelmez.</p>}
          {advice.advice.map((a,i)=><article className="m02-measure" key={`${a.rule_id}-${i}`}>
            <h3>{selected.find(x=>x.drug_id===a.subject_drug_id)?.name} → {foods[a.other_id] || a.other_name}</h3>
            <p className="m02-interval">İlk ilaç, diğer öğeden <strong>{quantity(a.interval_hours)} {a.direction==='before'?'önce':'sonra'}</strong>.</p>
            <ul>{a.conditions.map(c=><li key={c}>{c}</li>)}</ul>
            <details><summary>Önerinin açık kaynağı</summary><blockquote>{a.source.excerpt}</blockquote>
              <SourceLink url={a.source.url}>{a.source.title}</SourceLink><p>{a.source.section} · Etiket: {a.source.label_updated} · Açılarak kontrol: {a.source.checked_on}</p>
              <p>Kaynak metni kontrol edildi. Uzman/klinik kabulü henüz yapılmadı.</p></details>
          </article>)}
          <details open><summary>Kapsam ve eksik kontroller</summary><ul>{advice.coverage.map((c,i)=><li key={i}>
            {c.item_ids.map(id=>selected.find(x=>x.drug_id===id)?.name || foods[id] || id).join(' / ')}: <strong>{coverageStatus[c.status]}</strong><p>{c.reason}</p></li>)}</ul></details>
        </>}
      </section>}
    </>}
  </main>;
}
