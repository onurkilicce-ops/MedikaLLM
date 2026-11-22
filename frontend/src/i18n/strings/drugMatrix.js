/**
 * Drug interaction matrix UI strings.
 *
 * Cells show the lookup state of each pair (see src/pages/drugMatrixModel.js),
 * not a severity: DrugBank's interaction records carry no severity label and
 * no expert review exists yet, so no severity scale is shown. A pair without
 * a record is "no record" — never a check mark or "safe".
 */
export const DRUG_MATRIX_STRINGS = {
  en: {
    title: 'Drug Interaction Matrix',
    subtitle: 'Add drugs to see which pairs have a documented DrugBank interaction record.',
    searchPlaceholder: 'Search drugs to add…',
    loadFromPatient: 'Load from patient…',
    patientMedsHint: (n) => `${n} meds`,
    clearAll: 'Clear all',
    checking: 'Checking interactions…',
    summaryDrugs: 'Drugs',
    summaryRecords: 'Interaction records',
    summaryPairs: 'Pairs checked',
    severityNote:
      'Severity is not rated: DrugBank provides no severity label for these records and no expert review exists yet. "No record" does not mean the combination is safe.',
    emptyTitle: 'Add at least 2 drugs',
    emptyDescGeneric: 'Search for drugs above to see the interaction matrix.',
    emptyDescDoctor: "Search for drugs above or load a patient's medication list to see the interaction matrix.",
    errorBanner: 'The interaction check failed; the matrix shows no result for this selection.',
    retry: 'Retry',
    unresolvedBanner: (names) => `Not found in the database and NOT checked: ${names}`,
    patientMedsUnresolved: (names) =>
      `Patient medications not matched to a database drug (not in the matrix, not checked): ${names}`,
    patientMedsLookupFailed: (names) =>
      `The lookup failed for these patient medications (result unknown, not checked): ${names}`,
    patientMedsOverLimit: (names) =>
      `Not in the matrix — one check covers at most 10 drugs (not checked): ${names}`,
    maxDrugs: (n) => `At most ${n} drugs can be checked at once.`,
    detailSeverity: 'Severity: not rated (no source label)',
    detailSource: 'Source: DrugBank record ↗',
    legendHeading: 'Legend',
    cell: {
      record: 'Record',
      noRecord: 'No record',
      notChecked: 'Not checked',
      error: 'Failed',
      loading: '…',
    },
    legend: {
      record: 'DrugBank interaction record (severity not rated)',
      no_record: 'No record found — does not mean safe',
      not_checked: 'Not checked (drug not found in database)',
      error: 'Check failed — result unknown',
      loading: 'Checking…',
    },
  },
  tr: {
    title: 'İlaç Etkileşim Matrisi',
    subtitle: 'İlaçları ekleyerek hangi ikililerin DrugBank etkileşim kaydı olduğunu görün.',
    searchPlaceholder: 'Eklenecek ilacı ara…',
    loadFromPatient: 'Hastadan yükle…',
    patientMedsHint: (n) => `${n} ilaç`,
    clearAll: 'Tümünü temizle',
    checking: 'Etkileşimler kontrol ediliyor…',
    summaryDrugs: 'İlaç',
    summaryRecords: 'Etkileşim kaydı',
    summaryPairs: 'Kontrol edilen ikili',
    severityNote:
      'Önem derecesi değerlendirilmedi: DrugBank bu kayıtlar için önem etiketi sağlamıyor ve henüz uzman değerlendirmesi yok. "Kayıt yok" kombinasyonun güvenli olduğu anlamına gelmez.',
    emptyTitle: 'En az 2 ilaç ekleyin',
    emptyDescGeneric: 'Etkileşim matrisini görmek için yukarıdan ilaç arayın.',
    emptyDescDoctor: 'Etkileşim matrisini görmek için yukarıdan ilaç arayın veya bir hastanın ilaç listesini yükleyin.',
    errorBanner: 'Etkileşim kontrolü başarısız oldu; matris bu seçim için sonuç göstermiyor.',
    retry: 'Yeniden dene',
    unresolvedBanner: (names) => `Veritabanında bulunamadı, kontrol EDİLMEDİ: ${names}`,
    patientMedsUnresolved: (names) =>
      `Veritabanındaki bir ilaçla eşleşmeyen hasta ilaçları (matriste yok, kontrol edilmedi): ${names}`,
    patientMedsLookupFailed: (names) =>
      `Şu hasta ilaçları için arama başarısız oldu (sonuç bilinmiyor, kontrol edilmedi): ${names}`,
    patientMedsOverLimit: (names) =>
      `Matriste yok — bir kontrol en fazla 10 ilacı kapsar (kontrol edilmedi): ${names}`,
    maxDrugs: (n) => `Aynı anda en fazla ${n} ilaç kontrol edilebilir.`,
    detailSeverity: 'Önem: derecelendirilmedi (kaynakta etiket yok)',
    detailSource: 'Kaynak: DrugBank kaydı ↗',
    legendHeading: 'Açıklama',
    cell: {
      record: 'Kayıt var',
      noRecord: 'Kayıt yok',
      notChecked: 'Kontrol yok',
      error: 'Başarısız',
      loading: '…',
    },
    legend: {
      record: 'DrugBank etkileşim kaydı var (önem derecelendirilmedi)',
      no_record: 'Kayıt bulunamadı — güvenli anlamına gelmez',
      not_checked: 'Kontrol edilmedi (ilaç veritabanında bulunamadı)',
      error: 'Kontrol yapılamadı — sonuç bilinmiyor',
      loading: 'Kontrol ediliyor…',
    },
  },
};
