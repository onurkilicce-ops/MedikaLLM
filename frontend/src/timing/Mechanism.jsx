import React from 'react';

// M-03: organs, proteins and shared-protein explanations, shown on the same
// screen as M-02 because they explain WHY timing and levels change.

export const organLabel = {kidney:'Böbrek (idrar)', liver:'Karaciğer', bile_feces:'Safra / dışkı', lungs:'Akciğer (solunum)'};
export const kindLabel = {enzyme:'Enzim', transporter:'Taşıyıcı (membran)', carrier:'Taşıyıcı protein (kan/plazma)'};
export const roleLabel = {substrate:'kullanır (substrat)', inhibitor:'yavaşlatır (inhibitör)',
  inducer:'hızlandırır (indükleyici)', other:'başka etki'};
const fieldLabel = {route_of_elimination:'Atılım yolu', metabolism:'Metabolizma', clearance:'Klirens'};
const noteLabel = {negated_or_minor:'kayıt bu yolun olmadığını ya da çok küçük olduğunu söylüyor', uncertain_statement:'kayıt bunun bilinmediğini/belirsiz olduğunu söylüyor',
  condition_context:'yalnız hasta durumu bağlamı (ör. böbrek yetmezliğinde) — atılım yolu ifadesi değil',
  condition_also_mentioned:'cümlede ayrıca bir hasta durumu geçiyor',
  metabolite_mentioned:'metabolit geçiyor; ifade ana ilaca ait olmayabilir', other_subject_possible:'cümlede başka bir ilaç/karşılaştırma geçiyor; bu ilaca ait olmayabilir',
  other_drug_named:'cümlede başka bir ilaç adı geçiyor; ifade o ilaca ait olabilir', animal_study:'hayvan çalışması; insana uygulanmayabilir'};
// DrugBank known_action: is this protein part of the drug's OWN pharmacological action?
// It does not say whether the drug affects or uses the protein.
const knownLabel = {yes:'ilacın kendi etki mekanizmasının parçası (DrugBank)', no:'ilacın kendi etki mekanizmasının parçası olarak işaretli değil (bu, proteini etkilemediği anlamına gelmez)',
  unknown:'etki mekanizmasıyla ilişkisi bilinmiyor (DrugBank)'};
export const caveatLabel = {
  known_action_not_confirmed:'DrugBank bu proteini ilacın kendi etki mekanizmasının parçası olarak işaretlememiş (çoğu metabolizma kaydında böyledir); bu, ilişkinin olmadığı anlamına gelmez.',
  prodrug_reverses_direction:'İlaç bu enzimle etkinleşen bir ön ilaçsa (prodrug) yön tersine döner.',
  strength_not_stated:'Etkinin gücü kayıtta belirtilmemiş.',
  transport_direction_depends_on_protein:'Kandaki düzeyin artıp azalacağı taşıyıcının yerine ve yönüne bağlıdır.',
  shared_substrate_is_weak_evidence:'İkisinin aynı proteini kullanması tek başına zayıf bir kanıttır.',
  perpetrator_listed_as_inhibitor_and_inducer:'DrugBank bu ilacı aynı protein için hem inhibitör hem indükleyici olarak kaydetmiş; iki açıklama birbirine zıttır, net yön belirlenemez.',
  carrier_binding_direction_not_established:'Bu bir kan/plazma bağlanma proteinidir; serbest ilaç düzeyinin hangi yöne değişeceği bu kayıttan belirlenemez.',
  listed_under_different_protein_kinds:'Aynı protein iki ilaçta farklı türlerde (enzim/taşıyıcı) kaydedilmiş.',
  other_pathways_may_compensate:'Başka yollar etkiyi dengeleyebilir; klinik önem uzman değerlendirmesi gerektirir.',
};

function name(drugs, id) {
  return drugs.find(d => d.requested_id === id)?.drug?.name || id;
}

export function explanationText(x, drugs) {
  const p = <strong>{x.protein_name || x.protein_id}</strong>;
  const A = <strong>{name(drugs, x.perpetrator_id)}</strong>;
  const B = <strong>{name(drugs, x.victim_id)}</strong>;
  if (x.mechanism === 'shared_substrate') {
    const [a, b] = x.evidence.map(e => <strong key={e.drug_id}>{name(drugs, e.drug_id)}</strong>);
    if (x.protein_kind === 'carrier' && !x.caveats.includes('listed_under_different_protein_kinds')) {
      return <>{a} ve {b} aynı kan/plazma bağlanma proteinine ({p}) bağlanır. Bağlanmada yarışabilirler; serbest düzeyin yönü bu kayıttan belirlenemez.</>;
    }
    const what = x.caveats.includes('listed_under_different_protein_kinds') ? 'proteini' : x.protein_kind === 'enzyme' ? 'enzimi' : 'taşıyıcıyı';
    return <>{a} ve {b} aynı {what} ({p}) kullanır. Birbirleriyle yarışabilirler; bu kayıtta yön belirlenemez.</>;
  }
  if (x.caveats.includes('perpetrator_listed_as_inhibitor_and_inducer')) {
    return <>DrugBank {A} ilacını {p} için <strong>hem yavaşlatıcı (inhibitör) hem hızlandırıcı (indükleyici)</strong> olarak kaydetmiş; {B} bu proteinin substratı. {B} düzeyinin hangi yöne değişeceği bu kayıttan <strong>belirlenemez</strong>.</>;
  }
  if (x.protein_kind === 'enzyme') {
    return x.mechanism === 'inhibition'
      ? <>{A}, {B} ilacını işleyen {p} enzimini <strong>yavaşlatır</strong> ({B} bu enzimin substratı olarak kayıtlı). Bu yüzden {B} kanda <strong>birikebilir</strong> (düzeyi artabilir).</>
      : <>{A}, {B} ilacını işleyen {p} enzimini <strong>hızlandırır</strong> ({B} bu enzimin substratı olarak kayıtlı). Bu yüzden {B} kandan <strong>daha hızlı temizlenebilir</strong> (düzeyi azalabilir).</>;
  }
  if (x.protein_kind === 'carrier') {
    return <>{A}, {B} ilacının bağlandığı {p} proteini üzerinde etkili olarak kayıtlı ({x.mechanism === 'inhibition' ? 'inhibitör' : 'indükleyici'}). {B} ilacının bağlanması değişebilir; serbest düzeyin yönü bu kayıttan belirlenemez.</>;
  }
  return x.mechanism === 'inhibition'
    ? <>{A}, {B} ilacını taşıyan {p} proteinini <strong>yavaşlatır</strong>. {B} ilacının hücre zarından geçişi azalabilir.</>
    : <>{A}, {B} ilacını taşıyan {p} proteinini <strong>hızlandırır</strong>. {B} ilacının hücre zarından geçişi artabilir.</>;
}

// an inhibitor+inducer conflict comes as two opposite items: show one hedged sentence
export function visibleExplanations(list) {
  const seen = new Set();
  return list.filter(x => {
    if (!x.caveats.includes('perpetrator_listed_as_inhibitor_and_inducer')) return true;
    const key = `${x.protein_id}|${x.protein_name}|${x.perpetrator_id}|${x.victim_id}`;
    if (seen.has(key)) return false;
    seen.add(key); return true;
  }).map(x => {
    if (!x.caveats.includes('perpetrator_listed_as_inhibitor_and_inducer')) return x;
    // keep the strength of BOTH opposite records next to the single hedged sentence
    const twins = list.filter(y => y.protein_id === x.protein_id && y.protein_name === x.protein_name &&
      y.perpetrator_id === x.perpetrator_id && y.victim_id === x.victim_id);
    const label = {inhibition:'inhibisyon', induction:'indüksiyon'};
    const strengths = twins.map(y => `${label[y.mechanism]}: ${y.evidence[0]?.strength || 'belirtilmemiş'}`).join(' · ');
    return {...x, conflict_strengths: strengths};
  });
}

// denied / uncertain / condition-only: not a clearing route as stated
const FLAGGED = ['negated_or_minor', 'uncertain_statement', 'condition_context'];
// the sentence may be about another drug, an animal or a metabolite: whose route it is, is unclear
const ATTRIBUTION = ['other_drug_named', 'other_subject_possible', 'animal_study', 'metabolite_mentioned'];
export function organGroup(o) {
  if (o.notes.some(n => FLAGGED.includes(n))) return 'flagged';
  if (o.notes.some(n => ATTRIBUTION.includes(n))) return 'attribution';
  return 'route';
}
function OrganItem({o}) {
  return <li className={o.notes.length ? 'm03-flag' : ''}>
    <strong>{organLabel[o.organ]}</strong> <small>({fieldLabel[o.source_field]})</small>
    {o.notes.length > 0 && <small> · dikkat: {o.notes.map(n => noteLabel[n]).join('; ')}</small>}
    {o.other_drugs?.length > 0 && <small> · geçen ilaç: {o.other_drugs.join(', ')}</small>}
    <blockquote>{o.quote_cut_before && '[…] '}{o.quote}{o.quote_cut_after && ' […]'}</blockquote></li>;
}

function ProteinTable({proteins}) {
  if (proteins.length === 0) return <p>DrugBank bu ilaç için enzim veya taşıyıcı kaydetmemiş. Bu, ilacın bunları kullanmadığı anlamına gelmez.</p>;
  return <table className="m03-table"><thead><tr><th>Tür</th><th>Protein</th><th>Bu ilaç onu…</th><th>Kayıt ayrıntısı</th></tr></thead>
    <tbody>{proteins.map((p, i) => <tr key={`${p.kind}-${p.protein_id}-${i}`} className={p.human ? '' : 'm03-nonhuman'}>
      <td>{kindLabel[p.kind]}</td>
      <td>{p.name || p.protein_id}{!p.human && <small> · insan dışı ({p.organism || 'tür yok'}); karşılaştırmaya alınmaz</small>}</td>
      <td>{p.roles.length ? p.roles.map(r => roleLabel[r]).join(', ') : 'etki türü kayıtlı değil'}
        {p.inhibition_strength && <small> · inhibisyon gücü: {p.inhibition_strength}</small>}
        {p.induction_strength && <small> · indüksiyon gücü: {p.induction_strength}</small>}</td>
      <td><small>DrugBank: “{p.raw_actions || '—'}” · {knownLabel[p.known_action] || 'etki durumu yok'} · {p.protein_id || 'kimlik yok'}</small></td>
    </tr>)}</tbody></table>;
}

export default function Mechanism({mechanism, error}) {
  if (error) return <section className="m02-card"><h2>Organlar, enzimler ve taşıyıcılar (M-03)</h2><p role="alert">Mekanizma kontrolü tamamlanmadı: {error}</p></section>;
  if (!mechanism) return null;
  const {drugs, pairs} = mechanism;
  return <section className="m02-card" data-testid="m03-mechanism"><h2>Organlar, enzimler ve taşıyıcılar (M-03)</h2>
    <p>DrugBank'in protein listelerinden ve saklı metninden okunur. Doz veya önem derecesi değildir.</p>
    {drugs.map(d => <section key={d.requested_id} className="m02-drug-card"><h3>{d.drug?.name || d.requested_id}</h3>
      {d.lookup_status === 'not_found' ? <p>İlaç kaydı bulunamadı; kontrol tamamlanamadı.</p> : <>
        <h4>Hangi organlar temizliyor?</h4>
        <p><small>Kayıt metnindeki ifadeler. Pay ve yüzdeler alıntının içinde okunmalıdır; sistem bir organa yüzde atamaz.</small></p>
        {d.organs.length === 0 ? <p>Kayıt metninde organ yolu ifadesi bulunamadı{d.texts.length === 0 ? ' (atılım/metabolizma/klirens metni yok)' : ''}.</p>
          : <>
            {d.organs.some(o => organGroup(o) === 'route') ? <ul className="m03-organs" data-testid="m03-organs-route">
              {d.organs.filter(o => organGroup(o) === 'route').map((o, i) => <OrganItem key={i} o={o} />)}</ul>
              : <p>Kayıtta bir organın bu ilacı temizlediğini açıkça söyleyen bir ifade yok.</p>}
            {d.organs.some(o => organGroup(o) === 'attribution') && <details open><summary>Aidiyeti belirsiz ifadeler</summary>
              <p><small>Bu cümleler başka bir ilacı, bir karşılaştırmayı, bir hayvan çalışmasını veya bir metaboliti anlatıyor olabilir.
                Seçilen ilacın atılım yolu olarak sayılmadı; alıntıyı okuyun.</small></p>
              <ul className="m03-organs" data-testid="m03-organs-attribution">{d.organs.filter(o => organGroup(o) === 'attribution').map((o, i) => <OrganItem key={i} o={o} />)}</ul></details>}
            {d.organs.some(o => organGroup(o) === 'flagged') && <details open><summary>Kayıtta olumsuz, belirsiz veya yalnız hasta durumu olarak geçen organlar</summary>
              <ul className="m03-organs" data-testid="m03-organs-flagged">{d.organs.filter(o => organGroup(o) === 'flagged').map((o, i) => <OrganItem key={i} o={o} />)}</ul></details>}
          </>}
        {d.organs_truncated && <p><small>Organ ifadeleri listesi kısaltıldı; tam metin aşağıda.</small></p>}
        <h4>Hangi proteinler işliyor?</h4>
        <ProteinTable proteins={d.proteins} />
        {d.proteins_truncated && <p><small>Protein listesi kısaltılarak gösteriliyor; çift açıklamaları tüm kayıtlarla yapıldı.</small></p>}
        {d.texts.length > 0 && <details><summary>Saklı atılım/metabolizma metni</summary>
          {d.texts.map(t => <div key={t.source_field}><strong>{fieldLabel[t.source_field]}</strong><blockquote>{t.stored_text}{t.truncated && ' […]'}</blockquote></div>)}</details>}
      </>}
    </section>)}
    {pairs.length > 0 && <><h3>Ortak protein üzerinden etkileşim açıklaması</h3>
      {pairs.map(p => <article key={p.drug_ids.join('-')} className="m02-measure" data-testid="m03-pair">
        <h4>{p.drug_ids.map(id => name(drugs, id)).join(' + ')}</h4>
        {p.status === 'drug_not_found' && <p>Bir ilaç kaydı bulunamadı; bu çift değerlendirilemedi.</p>}
        {p.status === 'no_shared_protein_in_record' && <p>Kayıtlarda ortak bir insan proteini yok. Bu, etkileşim olmadığı anlamına gelmez.</p>}
        {p.status === 'shared_substrate_only' && <p>Yalnız ortak kullanılan protein var; bir ilacın diğerini yavaşlattığı veya hızlandırdığı kayıtlı değil.</p>}
        {p.status === 'shared_protein_no_direction' && <p>Ortak protein var{p.shared_proteins_without_direction.length > 0 ? ` (${p.shared_proteins_without_direction.join(', ')})` : ''}, ama kayıttan net bir yön çıkarılamıyor.</p>}
        {visibleExplanations(p.explanations).map((x, i) => <div key={i} className={x.directional ? 'm03-strong' : 'm03-weak'}>
          <p data-testid="m03-explanation">{explanationText(x, drugs)}</p>
          <details><summary>Kanıt ve sınırlar</summary><ul>
            {x.evidence.map(e => <li key={e.drug_id}>{name(drugs, e.drug_id)}: DrugBank “{e.raw_actions}” · {knownLabel[e.known_action] || 'etki durumu yok'}{e.strength && ` · güç: ${e.strength}`}</li>)}
            {x.conflict_strengths && <li>Kayıtlı güçler: {x.conflict_strengths}</li>}
            {x.caveats.map(c => <li key={c}>{caveatLabel[c] || c}</li>)}</ul></details>
        </div>)}
        {p.shared_proteins_without_direction.length > 0 && p.status !== 'shared_protein_no_direction' && <p><small>Yön çıkarılamayan diğer ortak proteinler: {p.shared_proteins_without_direction.join(', ')}</small></p>}
        {p.recorded_interactions.length > 0 && <details><summary>DrugBank'in bu çift için kayıtlı etkileşim metni</summary>
          {p.recorded_interactions.map((r, i) => <blockquote key={i}>{name(drugs, r.from_drug_id)} → {name(drugs, r.to_drug_id)}: {r.description}</blockquote>)}</details>}
      </article>)}
      {/* the API notice is English; the screen states the same rule in Turkish */}
      <p className="m02-note" data-testid="m03-notice">Bu açıklamalar yalnız DrugBank'in protein listelerinden ve saklı metninden çıkarılır.
        Ortak protein yokluğu etkileşim olmadığı anlamına gelmez; açıklama bir önem derecesi veya doz önerisi değildir.</p>
    </>}
  </section>;
}
