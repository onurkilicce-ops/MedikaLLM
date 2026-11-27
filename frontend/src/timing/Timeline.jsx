import React, { useState } from 'react';
import { quantity, conditionText } from './format';

/** Durations on one scale, NOT predicted concentrations or an administration schedule. */
export default function Timeline({ drugs }) {
  const [scale, setScale] = useState('linear');
  const rows = drugs.flatMap(d => d.measurements.flatMap(m => {
    if (m.review_required) return [];
    const base = { drug: d.drug.name, condition: conditionText(m.conditions), measurementId: m.measurement_id };
    const entries = [{ ...base, id:m.measurement_id, label:m.measure_type === 'tmax' ? 'Tmax' : 'Yarı ömür',
      q:m.hours, spread:m.dispersion?.value_hours, type:m.measure_type, approximate:m.approximate,
      ref:m.time_reference }];
    const derived = d.derived.find(x => x.based_on_measurement_id === m.measurement_id && x.status === 'computed');
    if (derived) entries.push({ ...base, id:derived.derived_id, label:'≈5 × yarı ömür', q:derived.hours,
      spread:derived.dispersion?.value_hours, type:'derived', approximate:true, ref:'duration' });
    return entries;
  }));
  const max = Math.max(1, ...rows.flatMap(r => [r.q.value, r.q.lower, r.q.upper].filter(Number.isFinite)));
  const position = n => 8 + 84 * (scale === 'linear' ? n / max : Math.log1p(n) / Math.log1p(max));
  const ticks = [0, .25, .5, .75, 1].map(f => scale === 'linear' ? max*f : Math.expm1(Math.log1p(max)*f));
  return <section className="m02-card" aria-label="Ortak zaman çizelgesi">
    <div className="m02-section-head"><h2>Ortak zaman çizelgesi</h2>
      <label>Ölçek <select value={scale} onChange={e => setScale(e.target.value)}>
        <option value="linear">Doğrusal</option><option value="log">Logaritmik (1 + saat)</option>
      </select></label></div>
    <p>0, süre karşılaştırmasının başlangıcıdır; ortak bir doz saati değildir. Tmax yalnız kaynak belirtiyorsa uygulamadan sonraki zamanı gösterir.
      Yarı ömür ve ≈5×, ayrı sürelerdir; Tmax bunlara eklenmez. Kişisel ilaç düzeyi eğrisi değildir.</p>
    <p className="m02-note">Koşulları farklı satırlar ayrı tutulur. İnceleme gereken değerler çizilmez; aşağıdaki kaynak kartlarında korunur.
      ≈5×, tam atılımı, etkinin bitişini veya güvenli kullanım aralığını göstermez.</p>
    {rows.length === 0 ? <p role="status">Çizelgeye yerleştirilebilen değer yok. Kaynak ve inceleme kartlarına bakın.</p> : <>
      <div className="m02-axis"><span>Saat</span><svg viewBox="0 0 100 8" role="img" aria-label={`${scale === 'linear' ? 'Doğrusal' : 'Logaritmik'} saat ekseni`}>
        {ticks.map((t,i) => <g key={i}><line x1={position(t)} x2={position(t)} y1="0" y2="2" stroke="currentColor" />
          <text x={position(t)} y="6" textAnchor="middle" fontSize="3">{Number(t.toPrecision(3))}</text></g>)}
      </svg></div>
      {rows.map(r => {
        const lo = r.q.value ?? r.q.lower ?? r.q.upper;
        const hi = r.q.value ?? r.q.upper ?? r.q.lower;
        return <div className="m02-timeline-row" key={r.id} data-testid="timeline-row">
          <div><a href={`#m02-${r.measurementId}`}>{r.drug} · {r.label}</a>
            <small>{r.condition}</small>
            {r.type === 'tmax' && <small>{r.ref === 'after_administration' ? 'Uygulamadan sonra' : 'Tmax zaman başlangıcı kaynakta belirtilmemiş'}</small>}
          </div>
          <div><svg viewBox="0 0 100 8" role="img" aria-label={`${r.label}: ${quantity(r.q)}`}>
            <line x1="8" x2="92" y1="4" y2="4" stroke="#cbd5e1" strokeWidth=".3" />
            <line x1={position(lo)} x2={position(hi)} y1="4" y2="4" stroke={r.type === 'derived' ? '#8b5cf6' : '#087e8b'} strokeWidth="2" />
            <circle cx={position(lo)} cy="4" r="1" fill="#087e8b" />
            {r.q.kind.endsWith('bound') && <text x={position(lo)} y="3" textAnchor="middle" fontSize="4">{r.q.kind === 'lower_bound' ? '→' : '←'}</text>}
          </svg><strong>{r.approximate ? '≈ ' : ''}{quantity(r.q)}{r.spread != null ? ` ± ${r.spread} sa (istatistik türü belirtilmemiş)` : ''}</strong></div>
        </div>;
      })}
    </>}
  </section>;
}
