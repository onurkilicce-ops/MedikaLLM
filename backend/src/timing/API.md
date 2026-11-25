# M-02 `POST /api/timing/compare` — tipli sözleşme (`m02-timing-compare/2`)

Salt okunur; LLM/harici kaynak çağırmaz; hasta, doz, kişisel zamanlama veya
reçete bilgisi almaz/üretmez. Ayrıştırma kuralları: [RULES.md](RULES.md).
Makine tarafından okunur şema: çalışan uygulamada `/openapi.json`
(`TimingCompareRequest`, `TimingCompareResponse` ve alt modeller; yanıtta her
zaman bulunan alanlar `required` olarak işaretlidir).

Bu belgedeki bütün kayıt içerikleri **sentetiktir** (`[SYNTHETIC]`); gerçek
ilaç verisi değildir. Kimlikler biçim örneğidir.

## İstek

```json
{"drug_ids": ["DB00006", "DB00682", "DB99999"]}
```

| Kural | Davranış |
|---|---|
| 2–10 öğe (bu teslimin **teknik** sınırı; Form A'nın klinik kuralı değil) | dışı → 422 |
| Her öğe `DB` + 5 ASCII rakam (`^DB[0-9]{5}$`, tam eşleşme) | küçük harf, boşluk, kısa/uzun, ad, sayı, Unicode rakam → 422 |
| Öğeler farklı | yineleme → 422 |
| Başka alan yok (`extra="forbid"`) | `patient_id`, `dose_mg` … → 422 |
| Sıra korunur; bulanık eşleştirme, büyük/küçük harf düzeltme, kırpma, liste kesme yok | — |

## Yetki ve durum kodları

| Kod | Ne zaman | Gövde |
|---|---|---|
| 200 | Sorgu tamamlandı (bilinmeyen kimlik ve verisi eksik ilaç dahil; ilaç başına ayrı durum) | `TimingCompareResponse` |
| 401 | Bearer yok / Bearer değil / geçersiz veya süresi geçmiş token / token'daki kullanıcı veritabanında yok (geçerli gövdeyle) | `{"detail": "..."}` |
| 403 | Oturum var ama hesabın doktor profili yok (`is_doctor` = mevcut tanım: `doctors` kaydı) | `{"detail": "A healthcare-professional account is required"}` |
| 422 | Gövde kurala uymuyor | FastAPI doğrulama gövdesi (mevcut ASCII-güvenli işleyici) |
| 429 | Mevcut ortak hız sınırı (`SEARCH_LIMIT`, varsayılan 60/dk/kullanıcı) | `{"error": "Rate limit exceeded: ..."}` |
| 503 | Kullanıcı veya ilaç okuması sırasında veritabanı hatası (bağlantı ya da sorgu) | `{"detail": "Timing data is temporarily unavailable; no result was produced."}` |

503 asla "ilaç bulunamadı" veya boş başarı olarak dönmez; gövdede SQL, bağlantı
adresi, istisna metni veya traceback yoktur.

Doğrulama sırası FastAPI'nin mevcut davranışıdır (değiştirilmedi): yetki
bağımlılığı gövde doğrulamasından önce çözülür. Bu yüzden bu uçta token'sız +
geçersiz gövde → 401 (gerçek çağrıyla doğrulandı); geçerli token + geçersiz
gövde → 422; geçerli token + geçersiz gövde + veritabanı kapalı → 503 (kullanıcı
okuması gövdeden önce yapılır). Not: STATUS'taki C3 kaydı `change-password`
için token'sız + geçersiz gövdede 422 bildiriyor; bu uçta 401 gözlendi. Bu
teslim o sırayı yeniden düzenlemez.

## Yanıt tipleri (özet)

Kural: **her dizi alanı her zaman vardır** (boşsa `[]`); bilinmeyen sayı
`null`'dır, asla `0` değildir.

```
TimingCompareResponse
  schema_version: "m02-timing-compare/2"
  parser_version: "m02-text-parser/4"
  drugs: DrugTimingResult[]               # istek sırasıyla
  timing_advice: {status: "not_evaluated", advice: [] , note: str}
  limitations: {code: str, message: str}[]

DrugTimingResult
  position: int; requested_id: str
  lookup_status: "found" | "not_found"
  drug: {drug_id, name, source_record_url} | null          # yalnız not_found'da null
  data_status: {tmax: FieldStatus, half_life: FieldStatus} | null   # yalnız not_found'da null
  fields: FieldReport[]          # found: [absorption, half_life]; not_found: []
  measurements: TimingMeasurement[]
  derived: DerivedDuration[]     # her half_life ölçümü için bir nesne
  limitations: str[]

FieldStatus = "empty" | "placeholder" | "parsed" | "parsed_needs_review"
            | "unparsed_needs_review" | "no_statement_found"

FieldReport
  source_field: "absorption" | "half_life"; field_status: FieldStatus
  stored_text: str | null (değiştirilmeden); stored_text_length: int
  stored_text_possibly_truncated: bool      # half_life tam 1000 karakter
  measurement_ids: str[]; review_items: ReviewItem[]; field_flags: str[]

ReviewItem {source_field, quote, quote_start, quote_end, value_text: str|null, reason: str}

TimingMeasurement
  measurement_id: "<drug_id>:<field>:<n>"; drug_id
  measure_type: "tmax" | "half_life"
  measure_basis: "value_keyword" | "sentence_keyword" | "field_only"
  source: SourceExcerpt
  original: Quantity + {unit: str, lower_unit: str|null}   # metindeki birimle
  hours: Quantity                                          # saate çevrilmiş
  approximate: bool
  dispersion: {kind: "plus_minus", value_original, unit, value_hours} | null
  conditions: {route[], formulation[], population[], food_state[], dosing[],
               analyte: "parent"|"metabolite"|"not_stated", analyte_terms[],
               phase[], matrix[], kinetics[], other[]}
  time_reference: "after_administration" | "not_stated" | "not_applicable_duration"
  review_required: bool; review_reasons: str[]; conflict_group: str | null
  parser_version: str

Quantity  {kind: "point"|"range"|"upper_bound"|"lower_bound",
           value, lower, upper: float|null, inclusive: bool|null}
           point→value; range→lower+upper (ortalama yok); upper_bound→upper; lower_bound→lower

SourceExcerpt
  source_ref: "drugbank:<drug_id>"; source_record_url; source_field
  quote (saklanan metnin tam cümlesi), quote_start, quote_end
  value_text, value_start, value_end       # stored_text[value_start:value_end] == value_text
  truncated: false (alıntı kısaltılmaz); stored_text_possibly_truncated: bool
  inline_reference_tokens: str[]          # tokens ATTRIBUTED to this value
  nearby_reference_tokens: str[]          # other tokens of the sentence, NOT attributed
  references: ReferenceLink[]; unmatched_reference_tokens: str[]
  reference_status: "matched"|"partially_matched"|"unmatched"|"no_inline_reference"
  reference_scope: "value_window"|"sentence_single_value"|"sentence_shared"|"sentence_other_clause"|"none"
  stored_reference_attributed: bool      # stored ref_id match + token belongs to this value alone;
                                         # NOT a check that the external source was opened or supports it

ReferenceLink {ref_id, ref_type, pubmed_id, isbn, citation, title, url}   # aynı ilacın drug_references satırı

DerivedDuration
  derived_id: "<measurement_id>:x5"; kind: "approx_five_half_lives"
  based_on_measurement_id; status: "computed" | "not_computed"; multiplier: 5
  hours: Quantity | null (not_computed'da null)
  dispersion: {kind: "plus_minus", statistic: "not_stated", value_hours, source_value_hours} | null
              # kaynak '±' yayılımı aynı x5 ile taşınır; SD/aralık/GA diye yorumlanmaz, min–max'a çevrilmez
  not_computed_reasons: str[]
  includes_tmax: false; assumptions: str[]; interpretation: str
```

C1 eşlemesi (ileride, C1 değiştirilmeden): `source.source_ref` ↔ C1
`source_ref`, `source.source_field` ↔ `source_field`, `source.quote` ↔ `quote`,
`source.truncated` ↔ `truncated`; sınırlamalar dizi olarak taşınır.

## Tam 200 örneği — kaynaklı değer, eksik veri, bilinmeyen kimlik

Aşağıdaki yanıt `service.compare(["DB00006", "DB00682", "DB99999"])`'in
sentetik satırlarla gerçek çıktısıdır (yalnız uzun sınırlama listesi kısaltıldı).

```json
{
  "schema_version": "m02-timing-compare/2",
  "parser_version": "m02-text-parser/4",
  "drugs": [
    {
      "position": 0,
      "requested_id": "DB00006",
      "lookup_status": "found",
      "drug": {"drug_id": "DB00006", "name": "[SYNTHETIC] Timing Agent A",
               "source_record_url": "https://go.drugbank.com/drugs/DB00006"},
      "data_status": {"tmax": "parsed", "half_life": "parsed"},
      "fields": [
        {"source_field": "absorption", "field_status": "parsed",
         "stored_text": "[SYNTHETIC] Peak plasma concentrations are reached within 0.5-1 hours after oral administration.[A900001]",
         "stored_text_length": 105, "stored_text_possibly_truncated": false,
         "measurement_ids": ["DB00006:absorption:1"], "review_items": [], "field_flags": []},
        {"source_field": "half_life", "field_status": "parsed",
         "stored_text": "[SYNTHETIC] The elimination half-life is 4-6 hours.[A900002]",
         "stored_text_length": 60, "stored_text_possibly_truncated": false,
         "measurement_ids": ["DB00006:half_life:1"], "review_items": [], "field_flags": []}
      ],
      "measurements": [
        {
          "measurement_id": "DB00006:absorption:1", "drug_id": "DB00006",
          "measure_type": "tmax", "measure_basis": "value_keyword",
          "source": {
            "source_ref": "drugbank:DB00006", "source_record_url": "https://go.drugbank.com/drugs/DB00006",
            "source_field": "absorption",
            "quote": "[SYNTHETIC] Peak plasma concentrations are reached within 0.5-1 hours after oral administration.[A900001]",
            "quote_start": 0, "quote_end": 105,
            "value_text": "0.5-1 hours", "value_start": 58, "value_end": 69,
            "truncated": false, "stored_text_possibly_truncated": false,
            "inline_reference_tokens": ["A900001"], "nearby_reference_tokens": [],
            "references": [{"ref_id": "A900001", "ref_type": "article", "pubmed_id": null, "isbn": null,
                            "citation": "[SYNTHETIC] Synthetic absorption study.", "title": null, "url": null}],
            "unmatched_reference_tokens": [], "reference_status": "matched",
            "reference_scope": "sentence_single_value", "stored_reference_attributed": true
          },
          "original": {"kind": "range", "value": null, "lower": 0.5, "upper": 1.0, "inclusive": null,
                       "unit": "hours", "lower_unit": null},
          "hours": {"kind": "range", "value": null, "lower": 0.5, "upper": 1.0, "inclusive": null},
          "approximate": false, "dispersion": null,
          "conditions": {"route": ["oral"], "formulation": [], "population": [], "food_state": [], "dosing": [],
                         "analyte": "not_stated", "analyte_terms": [], "phase": [], "matrix": ["plasma"],
                         "kinetics": [], "other": []},
          "time_reference": "after_administration",
          "review_required": false, "review_reasons": [], "conflict_group": null,
          "parser_version": "m02-text-parser/4"
        },
        {
          "measurement_id": "DB00006:half_life:1", "drug_id": "DB00006",
          "measure_type": "half_life", "measure_basis": "value_keyword",
          "source": {
            "source_ref": "drugbank:DB00006", "source_record_url": "https://go.drugbank.com/drugs/DB00006",
            "source_field": "half_life",
            "quote": "[SYNTHETIC] The elimination half-life is 4-6 hours.[A900002]",
            "quote_start": 0, "quote_end": 60,
            "value_text": "4-6 hours", "value_start": 41, "value_end": 50,
            "truncated": false, "stored_text_possibly_truncated": false,
            "inline_reference_tokens": ["A900002"], "nearby_reference_tokens": [],
            "references": [{"ref_id": "A900002", "ref_type": "article", "pubmed_id": null, "isbn": null,
                            "citation": "[SYNTHETIC] Synthetic elimination study.", "title": null, "url": null}],
            "unmatched_reference_tokens": [], "reference_status": "matched",
            "reference_scope": "sentence_single_value", "stored_reference_attributed": true
          },
          "original": {"kind": "range", "value": null, "lower": 4.0, "upper": 6.0, "inclusive": null,
                       "unit": "hours", "lower_unit": null},
          "hours": {"kind": "range", "value": null, "lower": 4.0, "upper": 6.0, "inclusive": null},
          "approximate": false, "dispersion": null,
          "conditions": {"route": [], "formulation": [], "population": [], "food_state": [], "dosing": [],
                         "analyte": "not_stated", "analyte_terms": [], "phase": ["elimination"], "matrix": [],
                         "kinetics": [], "other": []},
          "time_reference": "not_applicable_duration",
          "review_required": false, "review_reasons": [], "conflict_group": null,
          "parser_version": "m02-text-parser/4"
        }
      ],
      "derived": [
        {
          "derived_id": "DB00006:half_life:1:x5", "kind": "approx_five_half_lives",
          "based_on_measurement_id": "DB00006:half_life:1",
          "status": "computed", "multiplier": 5,
          "hours": {"kind": "range", "value": null, "lower": 20.0, "upper": 30.0, "inclusive": null},
          "dispersion": null,
          "not_computed_reasons": [], "includes_tmax": false,
          "assumptions": ["single_constant_half_life", "first_order_exponential_decline",
                          "approximate_duration_not_complete_elimination", "tmax_not_added"],
          "interpretation": "About 5 x the stated half-life. Only under a single, constant half-life (first-order decline) about 3% of the amount present at the start would remain after this time. It is an approximate duration derived from the source value, not a time point after a dose. It must not be read as complete elimination, as the end of the drug's effect or as clearance to give another drug, and it is not a personal drug level, dose or clinical interval."
        }
      ],
      "limitations": []
    },
    {
      "position": 1,
      "requested_id": "DB00682",
      "lookup_status": "found",
      "drug": {"drug_id": "DB00682", "name": "[SYNTHETIC] Timing Agent C",
               "source_record_url": "https://go.drugbank.com/drugs/DB00682"},
      "data_status": {"tmax": "placeholder", "half_life": "empty"},
      "fields": [
        {"source_field": "absorption", "field_status": "placeholder", "stored_text": "Not Available",
         "stored_text_length": 13, "stored_text_possibly_truncated": false,
         "measurement_ids": [], "review_items": [], "field_flags": []},
        {"source_field": "half_life", "field_status": "empty", "stored_text": "",
         "stored_text_length": 0, "stored_text_possibly_truncated": false,
         "measurement_ids": [], "review_items": [], "field_flags": []}
      ],
      "measurements": [],
      "derived": [],
      "limitations": ["half_life_text_empty", "absorption_text_placeholder"]
    },
    {
      "position": 2,
      "requested_id": "DB99999",
      "lookup_status": "not_found",
      "drug": null,
      "data_status": null,
      "fields": [],
      "measurements": [],
      "derived": [],
      "limitations": ["drug_id_not_in_database"]
    }
  ],
  "timing_advice": {
    "status": "not_evaluated",
    "advice": [],
    "note": "Timing-interval evidence was not searched in this version. This is not a statement that no source exists or that there is no interaction."
  },
  "limitations": [
    {"code": "stored_text_not_reverified", "message": "Values are read from text stored in this database (DrugBank import). ..."},
    {"code": "rule_based_extraction", "message": "Rule-based extraction (m02-text-parser/4, src/timing/RULES.md). ..."},
    {"code": "half_life_column_limit", "message": "..."},
    {"code": "general_references_not_linked", "message": "..."},
    {"code": "five_half_lives_is_an_approximation", "message": "..."},
    {"code": "tmax_not_added", "message": "..."},
    {"code": "timing_advice_not_evaluated", "message": "..."},
    {"code": "no_patient_data_no_dose", "message": "..."},
    {"code": "no_expert_acceptance", "message": "..."}
  ]
}
```

## Ayrıştırıcı 4 (M02-O1-R3) — tüketiciler için not

Sözleşme `m02-timing-compare/2` aynı kaldı (alan, kapsam değeri veya gerekçe kodu
eklenmedi); ayrıştırıcı `m02-text-parser/3` → `/4`. Yalnız davranış değişti
(ayrıntı: RULES.md 8d):

- Virgüllü ara ifade yöneten cümleciği artık gizlemez: `There is no evidence that, in
  adults, the half-life is 4 hours.` ve `… that the half-life, measured in adults, is 4
  hours.` → ölçüm yok, `undetermined_statement`; `It is not known whether, after oral
  administration, Tmax is 2 hours.` → `hypothetical_or_open_question`.
  `Studies failed to establish that …` → `undetermined_statement`.
- Ara ifadenin içindeki olumsuzluk/belirsizlik (`, which has never been confirmed,`)
  → `undetermined_statement`. Temkinde (`, possibly,`, `, if confirmed,`) değer kalır,
  `hedged_value` alır (5× yok). Zincirleme `that`, `remains to be shown`, `is false/
  mistaken` → `undetermined_statement`; soru cümlesi → `hypothetical_or_open_question`.
- `never shorter than 4 hours` artık alt sınırdır (`lower_bound`); önceden yanlışlıkla
  üst sınır okunuyordu.
- Küçük harfli iyelik (`drug b's half-life`), çerçeve (`For drug b, …`, `For drug b and
  drug c, …`), `compound a`, karşılaştırma ürünü (`comparator drug's`), çoğul (`the two
  drugs'`), başka ilacın metaboliti ve `drug b reaches peak …` kayıt ilacı değilse →
  ölçüm yok, `subject_unresolved`. Kendi öznesi olmayan sonraki değer (`… and 12 hours
  in children`) cümledeki önceki özneye göre değerlendirilir.
- Değerden sonraki ayrı iddia içeren ayraç veya `: …` içindeki belirteç ve böyle bir
  ayraçtan hemen sonra gelen belirteç `inline_reference_tokens`/`references`'a girmez,
  `nearby_reference_tokens`'ta kalır. Belirsiz ayraçtan sonra gelen cümle sonu
  belirteci `sentence_shared` olur (`stored_reference_attributed=false`). Koşul,
  istatistik, kısaltma ya da kaynak gösteren ayraç (`(e.g. in adults)`, `(n = 12,
  SD 1.1)`, `(Smith et al. [A1])`) değerin iddiasında kalır.

## Ayrıştırıcı 3 (M02-O1-R2) — tüketiciler için not

Sözleşme `m02-timing-compare/2` aynı kaldı (alan eklenmedi/değişmedi); ayrıştırıcı
`m02-text-parser/2` → `/3`. Davranış farkları:

- Yeni, ölçüm üretmeyen gerekçeler: `hypothetical_or_open_question` (`whether`/`if`
  cümleciğindeki değer) ve `subject_unresolved` (küçük/büyük harften bağımsız, kayıt
  ilacı olmayan açık özne). Üst cümleciğin olumsuzluğu (`There is no evidence that …`)
  `undetermined_statement` verir.
- `inline_reference_tokens` artık yalnız değerin **kendi iddiasındaki** belirteçleri
  içerir. Pencere içinde başka iddiaya ait belirteç (`…, while adverse events are
  described elsewhere [A2]`) `nearby_reference_tokens`'a gider. Değerden sonra başka iddia
  geliyorsa cümle sonu belirteci de `sentence_other_clause` + `nearby` olur (sürüm 2'de
  `sentence_shared` + listede kalıyordu).
- Bir hayvan türü ile farmakokinetik sözcüğün birlikte geçtiği değersiz cümle
  (`In dogs, elimination was studied.`) kapsam cümlesi sayılır.

## Sürüm 2 değişiklikleri (M02-O1-D1) — tüketiciler için not

`m02-timing-compare/1` → `/2`, `m02-text-parser/1` → `/2`. Gelecekteki ekran (Onur)
ve C1 eşlemesi (Kadir/Halil) için:

- `source.primary_reference_verified` **kaldırıldı**, yerine `source.stored_reference_attributed`
  (anlamı daraltıldı: saklı `ref_id` eşleşmesi + belirtecin yalnız bu değere ait olması;
  dış kaynağın açılıp doğrulandığı anlamına gelmez). Ekranda "doğrulandı" diye gösterilmemeli.
- `source.reference_scope` yeni değer: `sentence_other_clause` (belirteç başka `;` cümleciğini
  kapatıyor; bağlanmaz). `sentence_shared` artık cümlede başka değer **veya** değerden sonra başka
  iddia olduğunda da kullanılır.
- Yeni `source.nearby_reference_tokens`: cümledeki, bu değere atfedilmeyen belirteçler.
- Yeni `derived[].dispersion` (yalnız kaynakta `±` varsa; aksi halde `null`).
- Yeni inceleme gerekçeleri. Ölçüm üretmeyenler (yalnız `review_items`): `negated_value`,
  `undetermined_statement`, `subject_unresolved_comparison`, `subject_not_record_drug`,
  `dispersion_or_range_form_not_structured`. Ölçümü tutup işaretleyenler
  (`review_reasons`, ≈5× yok): `negated_condition`, `field_context_unattributed`,
  `non_human_context_in_field`, `hedged_value`, `comparison_in_clause`,
  `subject_code_unresolved`, `dispersion_not_structured`, sonraki cümle/cümlecikle
  gelen `undetermined_statement`. Türetilmişte: `invalid_dispersion`.
- Koşul terimleri artık metindeki olumsuzlamayı ve grup ifadesini korur
  (`without renal impairment`, `elderly patients`, `burn patients`).

## İnceleme ve hesaplanamama örneği (sentetik)

`half_life` = `"[SYNTHETIC] The half-life of the active metabolite is 20 hours."` →
ölçüm `review_required: false`, `conditions.analyte: "metabolite"`; ona bağlı
`derived`:

```json
{"status": "not_computed", "hours": null, "not_computed_reasons": ["metabolite_not_parent"],
 "includes_tmax": false}
```

`half_life` tam 1000 karakter ve son cümle yarım → `field_status:
"parsed_needs_review"`, `review_items[].reason: "sentence_possibly_truncated"`,
ölçümlerde `stored_text_possibly_truncated`, `derived.status: "not_computed"`.

## Hata örnekleri

```http
POST /api/timing/compare           (Authorization yok, geçerli gövde)
401 {"detail": "Not authenticated"}

POST /api/timing/compare           (geçerli token, doktor profili yok)
403 {"detail": "A healthcare-professional account is required"}

POST /api/timing/compare  {"drug_ids": ["DB00006", "DB00006"]}
422 {"detail": [{"type": "value_error", "loc": ["body", "drug_ids"], "msg": "Value error, drug ids must be distinct", ...}]}

POST /api/timing/compare           (veritabanı okunamıyor)
503 {"detail": "Timing data is temporarily unavailable; no result was produced."}
```
