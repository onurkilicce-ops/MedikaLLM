import React, { useId, useState } from 'react';
import { safeUrl } from './format';

// One table instead of paragraphs: rows = foods / situations, columns = the selected drugs.
// Every cell keeps its source one click away (DrugBank entry or a checked product label).

const KIND_CLASS = {avoid:'m02t-avoid', separate:'m02t-separate', limit:'m02t-limit', take_with:'m02t-with',
  take_without:'m02t-without', info:'m02t-info'};

function Cell({c, rowLabel, drugName}) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const url = safeUrl(c.source_url);
  return <div className={`m02t-cell ${KIND_CLASS[c.kind] || ''}`} data-testid="food-cell">
    <div>{c.text}</div>
    {c.timing_text && <div className="m02t-time"><strong>{c.timing_text}</strong></div>}
    {c.product && <div className="m02t-product">Etiket: {c.product}</div>}
    <button type="button" className="m02t-src" onClick={() => setOpen(!open)} aria-expanded={open}
      aria-controls={id} aria-label={`Kaynak: ${rowLabel} — ${drugName}`}>
      {open ? 'kaynağı gizle' : 'kaynak'}</button>
    {open && <div className="m02t-quote" id={id}>
      <blockquote>{c.source_text}</blockquote>
      <small>{c.source === 'label' ? (url ? <a href={url} target="_blank" rel="noopener noreferrer">{c.source_ref}</a> : c.source_ref)
        : 'DrugBank besin etkileşimi kaydı'}</small>
    </div>}
  </div>;
}

export default function FoodTable({table, error, busy}) {
  if (error) return <section className="m02-card"><h2>Ne zaman, neyle alınır?</h2>
    <p role="alert">Zamanlama tablosu okunamadı: {error}</p></section>;
  if (busy && !table) return <section className="m02-card"><h2>Ne zaman, neyle alınır?</h2><p role="status">Tablo hazırlanıyor…</p></section>;
  if (!table) return null;
  const drugs = table.drugs;
  const missing = drugs.filter(d => !d.found);
  const anyFound = drugs.some(d => d.found);
  const name = d => d.name || d.requested_id;
  return <section className="m02-card" data-testid="food-table-section"><h2>Ne zaman, neyle alınır?</h2>
    <p className="m02t-lead">Süreler ilacın kendisine göredir: <strong>“2 sa önce”</strong> = ilacı o şeyden 2 saat önce alın;
      <strong> “4 sa sonra”</strong> = ondan 4 saat sonra alın. Hücredeki “kaynak” özgün cümleyi gösterir.</p>
    {missing.length > 0 && <p role="status" data-testid="food-missing">İlaç kaydı bulunamadı: {missing.map(d => d.requested_id).join(', ')}.
      Bu ilaçlar için tabloda bilgi gösterilemez.</p>}
    {table.rows.length === 0 ? (anyFound && <p>Bulunan ilaçların kayıtlarında besin veya zamanlama bilgisi yok.
      Bu, etkileşim olmadığı anlamına gelmez.</p>) :
    <div className="m02t-wrap"><table className="m02t" data-testid="food-table">
      <thead><tr><th scope="col">Besin / durum</th>
        {drugs.map(d => <th scope="col" key={d.requested_id}>{name(d)}
          {!d.found && <small> (kayıt yok)</small>}
          {d.found && !d.has_food_entries && <small> (DrugBank besin kaydı yok)</small>}</th>)}</tr></thead>
      <tbody>{table.rows.map(r => <tr key={r.row_id} data-row={r.row_id}>
        <th scope="row">{r.label}</th>
        {drugs.map(d => <td key={d.requested_id}>
          {!d.found ? <span className="m02t-empty">kayıt yok</span>
            : (r.cells[d.requested_id] || []).length === 0 ? <span className="m02t-empty">—</span>
            : r.cells[d.requested_id].map((c, i) => <Cell key={i} c={c} rowLabel={r.label} drugName={name(d)} />)}
        </td>)}
      </tr>)}</tbody>
    </table></div>}
    <p className="m02t-foot">— = kayıtta bilgi yok (güvenli demek değildir). {table.notice}</p>
  </section>;
}
