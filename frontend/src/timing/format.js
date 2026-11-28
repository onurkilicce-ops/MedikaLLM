// One tr-TR number format for every number on the screen (values, ± spreads,
// axis ticks), so ',' is always the decimal and '.' always the group separator.
export function num(x, digits = 7) {
  return x == null ? '—' : new Intl.NumberFormat('tr-TR', { maximumSignificantDigits: digits }).format(x);
}

// Status line of the advice section, derived from the coverage reasons so a
// missing drug record is not reported as missing product conditions.
export function adviceStatusText(advice) {
  if (advice.status === 'evaluated') return 'Seçilen kapsam katalogda değerlendirildi';
  const reasons = new Set(advice.coverage.map(c => c.status));
  const why = [reasons.has('drug_not_found') && 'bir ilaç kaydı bulunamadı',
    reasons.has('conditions_required') && 'ürün/koşul doğrulaması gerekli'].filter(Boolean).join('; ');
  if (advice.status === 'partially_evaluated') return `Kısmen değerlendirildi${why ? ` (${why})` : ''}`;
  return `Değerlendirme tamamlanmadı${why ? `: ${why}` : ''}`;
}

export function quantity(q, unit = 'sa') {
  if (!q) return '—';
  const n = num;
  if (q.kind === 'range') return q.lower_unit ? `${n(q.lower)} ${q.lower_unit}–${n(q.upper)} ${unit}` : `${n(q.lower)}–${n(q.upper)} ${unit}`;
  if (q.kind === 'lower_bound') return `${q.inclusive ? '≥' : '>'}${n(q.lower)} ${unit}`;
  if (q.kind === 'upper_bound') return `${q.inclusive ? '≤' : '<'}${n(q.upper)} ${unit}`;
  return `${n(q.value)} ${unit}`;
}

export function conditionText(c) {
  return Object.entries(c || {}).flatMap(([key, value]) =>
    Array.isArray(value) ? value : key === 'analyte' && value !== 'not_stated' ? [value] : []
  ).join(' · ') || 'Koşul kaynakta belirtilmemiş';
}

export function httpError(error) {
  return ({401:'Oturum geçersiz veya süresi dolmuş. Yeniden giriş yapın.',
    403:'Bu ekran için sağlık profesyoneli hesabı gerekiyor.',
    422:'Seçimler veya ürün koşulları geçersiz. Seçimleri kontrol edin.',
    429:'İstek sınırına ulaşıldı. Biraz bekleyip yeniden deneyin.',
    503:'Veritabanına ulaşılamadı. Kontrol tamamlanmadı; bu, veri veya etkileşim olmadığı anlamına gelmez.'})[error.status]
    || 'Teknik hata: kontrol tamamlanmadı. Bağlantıyı kontrol edip yeniden deneyin.';
}

export function safeUrl(url) {
  try { const parsed = new URL(url); return ['https:', 'http:'].includes(parsed.protocol) ? parsed.href : null; }
  catch { return null; }
}

export const fieldStatus = {
  empty:'Veri yok', placeholder:'Kaynakta değer yok', parsed:'Yapılandırılmış veri var',
  parsed_needs_review:'İnceleme gerekli', unparsed_needs_review:'Metin ayrıştırılamadı; inceleme gerekli',
  no_statement_found:'Bu ölçüme ilişkin ifade bulunamadı',
};
export const coverageStatus = {
  matched:'Kaynakla eşleşti', conditions_required:'Ürün/koşul doğrulaması gerekli',
  not_in_catalog:'Bu katalogda kaynaklı zaman aralığı bulunamadı',
  not_applicable:'Bu koşula uygulanmıyor', drug_not_found:'İlaç kaydı bulunamadı',
};
