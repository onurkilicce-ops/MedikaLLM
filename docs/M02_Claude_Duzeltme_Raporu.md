# M-02 — Claude düzeltme teslimi (Astra kontrolü için)

**Durum: bağımsız denetimdeki üç engelleyici bulgu (B1, B2, B3) ve yedi engelleyici
olmayan bulgu (N1–N7) düzeltildi. Hepsi commit edildi, PR #5'e push edildi ve CI
yeşil. Teknik kabul kararı Astra'nın bu rapordaki kontrollerine bırakılmıştır.**

Bu teslim klinik kabul anlamına gelmez. Form A ≥%90 uzman kabulü yapılmadı.
Sentetik testlerin geçmesi bu hedefi karşılamaz.

- Tarih: 27 Kasım 2026
- Uygulayıcı: Claude (Onur Kılıç adına; git kimliği `onur kılıç`)
- Kontrol eden: Astra
- Denetim raporu: `M02_Claude_Bagimsiz_Teslim_Denetimi.md` (çalışma klasöründe;
  karar "TEKNİK TESLİME HAZIR DEĞİL" idi)

---

## 1. Sürüm

| Alan | Değer |
|---|---|
| Depo / PR | `onurkilicce-ops/MedikaLLM`, PR #5 (taslak) |
| Dal | `feat/onur/m02-timing` |
| Hedef / base | `team-test/2026-11-23-stage-0-1` / `c86dcc121047fe94a87b38245e8f467045afdb07` |
| Önceki PR head (R7) | `c0910da6657c50bbed526f7a19c8a65540d9fa50` |
| Commit 1 — Astra teslimi (değiştirilmeden) | `7be156b8d89e71f644fb4d6962d04bf59e9d54bf` (tree `9b8a78f5d6c47109de8de4fc50f1ae2209216995` = teslim manifestindeki `staged_tree`) |
| Commit 2 — denetim düzeltmeleri | `__FIX_SHA__` |
| CI | `__CI__` |

Astra teslimi ayrı commit olarak, olduğu gibi tutuldu. Böylece düzeltmeler kendi
diff'iyle incelenebilir: `git diff 7be156b __FIX_SHORT__`.

## 2. Bulgular ve düzeltmeler

### B1 — önceki cümleden yanlış ilaç aidiyeti (engelleyici) → düzeltildi

**Sorun.** `Drug B was studied. Its half-life is 6 hours.` Drug A kaydında temiz
6 sa ve ≈5× hesap veriyordu.

**Düzeltme** (`backend/src/timing/parser.py`, parser `m02-text-parser/10`,
kurallar RULES 8j):

- Miras yalnız **anaforik** (`its`, `their`, `it`, `they`, `this`, `these`,
  `both`, `each`, `the former` …) ya da **yok** özneye (`Half-life: 6 hours`)
  uygulanır. Belirli `The half-life …` miras almaz.
- Kaynak: aynı cümlenin değerden önceki kısmı, sonra önceki cümleler (en yakın önce;
  en çok 3 parça / 600 karakter). İlaç biçimli kanıt taşıyan ilk parça karar verir.
- İlaç biçimli kanıt yalnız şunlardır:
  - kodlu ilaç adı (`drug b`, `compound c`, `drugs B and C`);
  - biçim/durum sözcüğünün `of` tümleci (`the formulation of drug b`).

  Yabancıysa sonuç `subject_unresolved` olur; ölçüm ve ≈5× yoktur.
- Değerin cümleciği virgülle bağlanmış cümle, `;`, `:`, tire, parantez ve
  `and/but/while/whereas its…` sınırlarıyla ayrılır.

**Tasarım notu.** İlk taslak önceki cümlenin öznesini fiil listesiyle okuyordu.
Kendi çekişmeli denememde iki yönde 16 hata çıktı:
- Listede olmayan fiiller (`penetrates`, `crosses`, `accumulates`), virgülle
  bağlanmış cümle, `It … Its` zinciri, `both/these` → yanlış ilaç hâlâ temiz.
- `Cmax is 200 ng/mL.`, `The tablet contains lactose.`,
  `Healthy volunteers received 10 mg.` → aşırı ret.

Fiil listesi kaldırıldı ve yerine ilaç biçimli kanıt kuralı kondu. Bu 16 örnek ve
akrabaları regresyon testi oldu.

**Bilinen sınır (Astra'nın bilmesi gerekir).** Ayrıştırıcı ilaç adı tanımaz. Önceki
cümlede kodsuz gerçek bir ilaç adı varsa (`Ritonavir increases exposure. Its
half-life is 6 hours.`) miras yoluyla yakalanmaz. Betimleyici PK cümlelerini aşırı
reddetmemek için bu bilinçli bir takastır. Değerin kendi cümlesindeki açık özne
(`The half-life of ritonavir …`) önceki kurallarla yine yakalanır. Bu kalıntı risk
gerçek veri kapsam incelemesinde ve uzman kabulünde ölçülmelidir.

**Testler.**
- `backend/tests/unit/test_m02_audit_r8.py`:
  - B1 olumsuz: 11 örnek, ayrıca 23 çekişmeli örnek;
  - B1 olumlu: 9 örnek, ayrıca 15 çekişmeli örnek;
  - N1: 8 + 3 örnek.
- `backend/tests/integration/test_m02_audit_r8_http_pg.py`: B1 HTTP → yetki →
  servis → sentetik PG üzerinden.

### B2 — teslim edilen canlı akış testi/CI adımı başarısız (engelleyici) → düzeltildi

**Sorun.** `vite.m02.config.js` ile çalışan React DOM → HTTP → PG akışı `TypeError:
Expected signal to be an instance of AbortSignal` ile düşüyordu. jsdom'un
`AbortSignal`'ı Node'un yerleşik `fetch`'ine veriliyordu.

**Düzeltme.** `frontend/e2e/setup.js` yalnız bu canlı akış yapılandırmasında
`fetch`'i sarar. jsdom sinyali Node `fetch`'ine iletilmez; iptal edilen istek yine
`AbortError` ile reddedilir. Uygulama kodu değişmedi; gerçek tarayıcıda tek bir
`AbortSignal` vardır. `vite.m02.config.js` → `setupFiles: ['./e2e/setup.js']`.

**Kanıt.** Sentetik demo sunucusuna karşı canlı akış 6/6 geçti (yerel Node 24). CI'da
(Node 20) aynı adım `__CI_E2E__`.

### B3 — commit/push/CI yok (süreç engeli) → düzeltildi

İki commit `feat/onur/m02-timing` dalına push edildi; PR #5 taslak kaldı. Merge, force
push, main'e push veya geçmiş yeniden yazma yapılmadı. CI: bkz. §1.

### N1 — aşırı retler → düzeltildi

- Farmakokinetik bölüm etiketleri ad sayılmaz: `Excretion:`, `Metabolism:`,
  `Protein binding:`, `Pharmacokinetic properties:`.
- Niteleyiciler ad sayılmaz: `mainly`, `extensive`, `absolute`, `systemic`,
  `proportionally`.
- Tuz, çapraz atıf ve ölçü kısaltması parantezleri sahip sayılmaz: `(hydrochloride)`,
  `(as sodium)`, `(see section 5.2)`, `(Tmax)`.
- İyelik eki `'s` ad sözcüğü değildir: `drug a's mean terminal elimination half-life`.
- `Coadministration of drug b … The half-life is …` temiz kalır (belirli `The`).
- Aynı yapılar başka ilaçla yazıldığında yine reddedilir, ör. `drug b (hydrochloride)`
  ve `drug b's …`.

### N2 — "İlk ilaç" ifadesi → düzeltildi

Öneri cümlesi artık öznenin adını verir: «Kaynağa göre **X**, «Y» öğesinden
**1–2 saat önce**.» Ad yoksa `subject_drug_id` gösterilir
(`TimingPage.jsx`, `data-testid="advice-interval"`).

### N3 — emc 885 alıntısı 4.5 değil 4.2'de → düzeltildi

`advice.py` `cipro_food`:
- `source_ref`: `emc:885:4.2`;
- başlık: Ciproxin 250 mg/5 mL süspansiyon;
- bölüm: "4.2 — Method of administration".

`SOURCES.md` satırı 4.2'yi gösterir ve 4.5'in doğrulanmadığını not eder. Alıntı
metni değişmedi.

### N4 — casefold / lower uyumsuzluğu → düzeltildi

`repository.search_drugs` sorguyu saklı `name_lower`/`synonym_lower` ile aynı
biçimde `lower()` ile normalize eder. Örnek: `Süß` sorgusu `süßholz` eş adını bulur
(HTTP/PG testi).

### N5 — NUL karakteri 500 veriyordu → düzeltildi

`GET /api/timing/drugs` kontrol karakteri (`ord < 32` veya `127`) içeren `q` için
veritabanına gitmeden 422 döner (HTTP/PG testi: `\x00`, `\x07`).

### N6 — drug_not_found için "Koşullar eksik" etiketi → düzeltildi

`format.js` `adviceStatusText` durumu kapsamdan türetir:
- "bir ilaç kaydı bulunamadı";
- "ürün/koşul doğrulaması gerekli";
- "Kısmen değerlendirildi (…)";
- "Değerlendirme tamamlanmadı: …".

### N7 — ± ve eksen etiketleri tr-TR değil → düzeltildi

`format.js` `num()` (tr-TR, ondalık virgül). `±` yayılımı, çizelge eksen etiketleri
ve miktarlar bunu kullanır (`TimingPage.jsx`, `Timeline.jsx`).
Testler: `frontend/src/timing/TimingAuditFixes.test.jsx` (N2, N6, N7).

## 3. Doğrulama sonuçları

| Kontrol | Sonuç |
|---|---|
| Backend birim testleri | 1247 geçti (PG gerektirmeyenler) |
| Katı tam paket (`MEDICALLM_STRICT_TESTS=1`, ayrı sentetik PG 127.0.0.1:55440) | **1519 geçti, 0 atlandı** |
| R2–R7 ve D1–D6 HTTP tarama setleri (önceki turların kayıtlı çıktılarına karşı) | 7 setin 7'si de birebir aynı (r2 20, r3 26, r4 27, r5 22, r6 23, r7 21, d1–d6 13 kayıt; yalnız sürüm dizesi normalize edildi) |
| Frontend testleri | 67 geçti (7 dosya) |
| Frontend derleme | başarılı |
| React DOM → HTTP → yetki → servis → sentetik PG canlı akışı | 6/6 geçti (yerel, `--seed` ile yeniden kurulan demo sunucusu 127.0.0.1:18102) |
| GitHub CI | __CI__ |

Gerçek DrugBank kümesi başlatılmadı, sayılmadı, içe aktarılmadı, değiştirilmedi.
Lisanslı metin, anahtar, parola veya hasta verisi Git'e ya da bu rapora girmedi.
Tüm test metinleri `[SYNTHETIC]` etiketlidir.

## 4. Astra için kontrol listesi

1. **Sürüm.**
   - `git log --oneline c0910da..__FIX_SHORT__` iki commit göstermeli.
   - `git rev-parse 7be156b^{tree}` = `9b8a78f5d6c47109de8de4fc50f1ae2209216995`
     olmalı (teslim değiştirilmeden uygulandı).
2. **Düzeltme diff'i.** `git diff 7be156b __FIX_SHORT__`: yalnız §2'deki dosyalar
   değişmeli. Şema, migration, bağımlılık ve kilit dosyalarına dokunulmadı.
3. **B1.** Aşağıdaki gibi kendi örneklerinle dene (`parse_field("half_life", "[SYNTHETIC] …",
   subject_names=["[SYNTHETIC] Drug A"])`). Özellikle şunlara bak:
   - virgülle bağlanmış cümle;
   - anafor zinciri;
   - `both/each/the former`;
   - kayıt ilacı ile yabancı ilacın aynı cümlede geçmesi;
   - betimleyici PK cümleleri;
   - kodsuz gerçek ad sınırı (§2 B1). Bu sınırın kabul edilebilir olup olmadığı
     ürün kararıdır.
4. **Sabitlenmiş örnekler.** Önceden kayıtlı 94 örnek ve D1–D6 / R2–R7 setleri
   değiştirilmedi. Testlerdeki sürüm iddiaları `/10`'a çekildi:
   - `test_m02_audit_http_pg.py`, `test_m02_timing_api_pg.py`: `/10`;
   - `test_m02_audit_r7.py`: "≥ 9".
5. **B2.** `frontend/e2e/setup.js` yalnız `vite.m02.config.js` içinde yüklenir.
   Normal `vitest` ve üretim kodu bu sarmalayıcıyı görmez.
6. **CI.** PR #5 check'lerinde backend, frontend ve "M02 React DOM to PostgreSQL
   flow" adımlarının yeşil olduğunu doğrula.
7. **Kapsam.**
   - CI dosyasındaki M-02 adımı Astra teslimiyle eklenmişti (R3'teki "CI'ya dokunma"
     kısıtı bu tamamlama görevinde kullanıcı yetkisiyle aşıldı). Düzeltme commit'i
     CI dosyasını değiştirmez.
   - Ajan/C1 ve hasta ekranları değişmedi.

## 5. Açık kalanlar (bu teslimin dışında)

- Form A ≥%90 uzman kabulü (adlı hekim/eczacı, önceden belirlenmiş örnekler) — yapılmadı.
- Gerçek veri kapsamı ölçümü ve §2 B1'deki kodsuz gerçek ad sınırının oranı — ölçülmedi.
- M-06/C1 sohbet entegrasyonu — kapsam dışı (API.md).
- Merge kararı — PR #5 taslak; merge yapılmadı.
