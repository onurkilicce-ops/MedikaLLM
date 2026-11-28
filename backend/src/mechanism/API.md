# M-03 — Organlar, enzimler ve taşıyıcılar (`POST /api/mechanism/compare`)

Sözleşme `m03-mechanism/1`, kurallar `m03-mechanism-rules/1` ([RULES.md](RULES.md)).
M-02 ile aynı ekranda gösterilir (`/timing`, "Organlar, enzimler ve taşıyıcılar (M-03)"
bölümü). M-02 sürelerin ne olduğunu, M-03 neden değişebildiğini anlatır.

- **Veri:** yalnız DrugBank'in saklı kayıtları okunur:
  - `drugs.route_of_elimination`, `metabolism`, `clearance`;
  - `drug_enzymes`, `drug_transporters`, `drug_carriers`;
  - istenen ilaçlar arasındaki `drug_interactions` kayıtları.
- **Yazma ve dış çağrı yok:** hiçbir şey yazılmaz; LLM ve dış kaynak çağrılmaz.
- **Okuma:** `READ ONLY` işlemde yapılır ve geri alınır.
- **Erişim:** M-02 ile aynı Bearer token ve sağlık profesyoneli (doktor profili) kontrolü,
  aynı `SEARCH_LIMIT` hız sınırı.

## İstek

```json
{"drug_ids": ["DB00001", "DB00002"]}
```

1–10 farklı DrugBank kimliği (`DB` + 5 ASCII rakam). Ek alan gönderilirse 422 döner.

## Yanıt (özet)

| Alan | Anlamı |
|---|---|
| `drugs[]` | İstek sırasında. Bilinmeyen kimlik için `lookup_status: "not_found"`, `drug: null`, boş listeler |
| `drugs[].proteins[]` | `kind` (`enzyme` / `transporter` / `carrier`), `protein_id` (DrugBank BE kimliği), `name`, `organism`, `human`, `roles` (`substrate` / `inhibitor` / `inducer` / `other`), DrugBank'in ham `raw_actions` ve `known_action` değeri, enzimde `inhibition_strength` / `induction_strength` (kayıttaki gibi) |
| `drugs[].organs[]` | `organ` (`kidney` / `liver` / `bile_feces` / `lungs`), `source_field`, cümlenin birebir `quote` metni ve `[quote_start, quote_end)` konumu (gösterilen metnin içinde), `quote_truncated` ve pencerenin kesildiği yerler (`quote_cut_before`, `quote_cut_after`), `notes` (`negated_or_minor`, `uncertain_statement`, `condition_context`, `condition_also_mentioned`, `metabolite_mentioned` (bilgi), `metabolite_route` (bu yolla giden metabolit), `other_subject_possible`, `other_drug_named`, `animal_study`), `other_drugs` (cümlede geçen başka DrugBank ilaçlarının adları). Organa yüzde/pay atanmaz; yüzdeler alıntıda okunur |
| `drugs[].organs_truncated` / `proteins_truncated` | Organ listesi alan başına 50, protein listesi 200 ile sınırlandı. Çift açıklamaları her zaman tüm kayıtlarla yapılır |
| `drugs[].texts[]` | Okunan saklı metinler, en çok 20 000 karakter (`truncated`). `Not Available` gibi yer tutucular (sondaki noktalama dahil) atlanır |
| `pairs[]` | Her ilaç çifti, istek sırasıyla |
| `pairs[].status` | `explained_by_shared_protein`, `shared_substrate_only`, `shared_protein_no_direction`, `no_shared_protein_in_record` veya `drug_not_found` |
| `pairs[].explanations[]` | `mechanism`, `perpetrator_id` → `victim_id`, `effect`, `directional` (net yön var mı), iki ilacın kanıtı (`evidence`: rol başına tek kaydın `known_action` ve gücü) ve `caveats` (aşağıda) |
| `pairs[].shared_proteins_without_direction` | Hiç açıklaması olmayan ortak proteinlerin adları |
| `pairs[].recorded_interactions[]` | DrugBank'in bu iki ilaç arasındaki kendi etkileşim metni (`from_drug_id` → `to_drug_id`); yinelenenler bir kez |

`mechanism` değerleri: `inhibition`, `induction`, `shared_substrate`.

`effect` değerleri:
- enzimde: `victim_exposure_may_increase` / `victim_exposure_may_decrease`;
- taşıyıcıda: `victim_transport_may_decrease` / `victim_transport_may_increase`;
- plazma taşıyıcı proteininde (`carrier`): `carrier_binding_may_change`; yönsüzdür;
- ortak substratta: `competition_possible_not_established`.

`caveats` değerleri:
- `known_action_not_confirmed`;
- `perpetrator_listed_as_inhibitor_and_inducer`;
- `prodrug_reverses_direction`;
- `strength_not_stated`;
- `transport_direction_depends_on_protein`;
- `carrier_binding_direction_not_established`;
- `listed_under_different_protein_kinds`;
- `shared_substrate_is_weak_evidence`;
- `other_pathways_may_compensate`.

**Yorum kuralı.** Ortak protein yokluğu "etkileşim yok" değildir. Açıklama bir önem
derecesi, doz önerisi ya da "birlikte kullanılabilir" anlamı taşımaz (`notice` alanı).

## Hatalar

M-02 ile aynı:

| Kod | Durum |
|---|---|
| 401 | Token yok, geçersiz ya da kullanıcı yok |
| 403 | Doktor profili yok |
| 422 | Geçersiz gövde |
| 429 | Hız sınırı aşıldı |
| 503 | Veritabanı okunamadı (kimlik kontrolü dahil). Gövde: `{"detail": "Mechanism data is temporarily unavailable; no result was produced."}`; ayrıntı sızdırılmaz |

Ekran 503'ü "protein yok" diye göstermez, "Mekanizma kontrolü tamamlanmadı" der.

M-03 isteği M-02'den bağımsızdır: M-02 sonuçlarını beklemez ve geciktirmez. M-02
bölümleri hazır olur olmaz görünür; M-03 bölümü sonra dolar.
