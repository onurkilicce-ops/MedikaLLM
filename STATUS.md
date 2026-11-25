# MedicaLLM — Durum kaydı

Bu dosya projenin **tek durum kaydıdır**; sonraki aşamalar buraya eklenir.
`report.md` önceki ekibin 2. dönem proje raporudur, güncel hedeflerin veya
tamamlanmış işlerin kanıtı değildir. Kapsam kaynağı: *SDP Project Forms A/B*
(Form A "Before Edit With Client" — imzasız taslak; onaylı sözleşme sayılmaz).

Düzen: **"Tur 1" bölümü güncel ortak ilerleme kaydıdır** (tek kayıt; yeni durum
dosyası açılmaz). Altındaki "Aşama 0" ve "Aşama 0.1" bölümleri **tarihsel
uygulayıcı raporlarıdır**, değiştirilmeden korunur; oradaki canlı ölçümler
bağımsız olarak yeniden doğrulanmadı.

---

## Tur 1 — Güncel ilerleme kaydı (başlangıç 2026-11-24)

> Hiçbir MVP'nin (M-01…M-06) klinik kabulü yoktur. Testlerin geçmesi klinik
> doğrulama değildir. Klinik kabul için uzmanın önceden belirlediği örnekler
> gerekir (Form A 3.5: adlı hekim/eczacı, Hafta 7).

### 1. Ortak başlangıç

| Alan | Değer |
|---|---|
| Ekip deposu | `onurkilicce-ops/MedikaLLM` (kaynak proje: `IsmailEsadKilic/MedicaLLM`) |
| Entegrasyon dalı | `team-test/2026-11-23-stage-0-1` |
| Ortak başlangıç SHA | `f549e597e41539704e9b39a5ff0e30e6af7c8cd8` |
| Önceki checkpoint | `team-test/2026-11-22-checkpoint` @ `f0a36e8ebf3441348170faa702d6bed9388cf4ae` |
| Açık PR #1 | Yeni dalı eski checkpoint'e birleştirmeyi öneriyor; **Tur 1 görev PR'ı değildir**, merge/hedef değişikliği yapılmaz |
| Görev PR hedefi | Her görev PR'ı: base = `team-test/2026-11-23-stage-0-1` |
| Güncelleme yöntemi | `git merge --no-ff <KABUL_EDİLMİŞ_TAM_SHA>`; force push / rebase / reset --hard yok |

Kapsam belgesi durumu: `SDP_Project_Forms_Enhanced.docx.pdf` (8 sayfa) okundu;
Form A "Before Edit With Client" taslağıdır, imza/tarih, MVP "Owner" sütunu,
fikri mülkiyet ve ödeme seçenekleri boştur. **Ayrı bir güncel kapsam eki
bulunamadı** — eke bağlı kararlar (ör. MVP sahipliği, M-04 Türkiye OTC kaynağı,
M-05 önem etiketleme yöntemi) eksik olarak açıktır.

### 2. Görev ve dosya sahipliği (Tur 1)

| Görev | Sahip | Dal | Değişiklik alanı | Dokunmaz |
|---|---|---|---|---|
| R1-O1 Tekrarlanabilir taban + mevcut API onarımı (C2, C3, CI) | Onur Kılıç (entegrasyon sorumlusu) | `feat/onur/r1-baseline` | README.md, STATUS.md, .github/workflows/ci.yml, .env.example, .gitignore, compose.local.yml, backend/pyproject.toml, backend/uv.lock, (zorunluysa) run.py/config.py/main.py/scripts/init_tables.py, auth/router.py + service.py + dependencies.py, drugs/router.py, users/service.py (yalnız ortak erişim kontrolü), tests/conftest.py, tests/integration/conftest.py, synthetic_data.py, test_api_shape.py, test_r1_auth_access.py, frontend/package.json + package-lock.json | agent/, session/, conversations/, frontend/src/, sql_models.py/migration |
| R1-K1 Yanıt kanıtı C1 üretimi | Kadir Güllükaya | (Kadir'in görev dalı) | agent/, session/, conversations/ ve ilgili kanıt testleri | — |
| R1-H1 C1 gösterimi + etkin hekim analizi yanıtı | Halil Samet Şen | (Halil'in görev dalı) | frontend/src/ (arayüz, API istemcisi, çeviri, yönlendirme, stil) | — |
| R1-O2 Kontrol komutunun doğru sonuç vermesi + sınırlı canlı doğrulama (R1-O1 sonrası yeni, bağımsız iş) | Onur Kılıç | `fix/onur/r1-live-check` | backend/scripts/check_live_stack.py, backend/tests/test_check_live_stack.py, README.md (yalnız bu komut), STATUS.md (yalnız R1-O2) | uygulama modülleri, db/migration, ortak test fixture'ları, bağımlılık/CI/Docker/.env |

Okunabilir ama bu tur kimsenin değişiklik alanı olmayan: `drugs/service.py`,
`drugs/models.py`, `pubmed/`. `backend/src/db/sql_models.py` ve şema/migration bu
tur **değişmez**; ortak model isteği Onur'a gelir. Ortak bağımlılık dosyaları
(`backend/pyproject.toml`, `uv.lock`, `frontend/package*.json`) tek sahibi Onur'dur.

### 3. Ortak sözleşmeler — R1 hedefi

**C1 / Yanıt kanıtı (üretici Kadir, tüketici Halil) — kararlaştırılan hedef, henüz uygulanmadı.**
Mevcut `POST /api/session/query-stream` ve `POST /api/session/query` korunur;
istek `{query, conversation_id, patient_id?: string|null, session_id?: string|null}`,
Bearer yetkisi aynı. SSE `type` alanları ve `error/status/heartbeat` davranışı
korunur; `done` olayına `answer_evidence` eklenir. Aynı nesne kaydedilen
assistant `Message.debug.answer_evidence` içinde, `/query` yanıtındaki son
assistant mesajında ve geçmiş okumasında bulunur. Yeni tablo/migration yok.

Örnek (tamamen sentetik):

```json
{
  "version": 1,
  "mode": "source_extract",
  "checks": [{"tool": "check_drug_interactions", "status": "found",
              "unresolved_inputs": [], "requires_confirmation": [],
              "pairs_checked": 1, "pairs_total": 1}],
  "items": [{"source_ref": "REF1", "source_field": "interaction_description",
             "quote": "[SYNTHETIC] Substance A changes the measured exposure of substance B.",
             "truncated": false, "severity": null, "severity_status": "not_rated"}],
  "limitations": ["model_narrative_withheld"]
}
```

`sources[]` içindeki aynı `REF1`, gerçek araçtan gelen URL/başlıkla birlikte
`evidence_fields: {"interaction_description": "[SYNTHETIC] Substance A changes the measured exposure of substance B."}` taşır.

Kurallar (özet): `version`=1; `mode` ∈ `source_extract | insufficient_evidence | nonclinical`;
`checks/items/limitations` daima dizi; `status` ∈ `found/no_record/incomplete/unresolved/error`;
araç çalışmadıysa `checks=[]` + `limitations` içinde `not_checked` (klinik soruda
`insufficient_evidence`); `pairs_*` negatif olmayan integer|null (bilinmeyen 0 yapılmaz);
`quote` kaynak alanından aynen, kısaltma varsa `truncated=true` + görünür işaret;
önem bu tur `null` + `not_rated`; `nonclinical` yalnız önceden belirlenmiş
selam/yardım metinleri; `done.final_content`, kalıcı `Message.content` ve son
assistant içeriği güvenilir şablon + orijinal alıntıdır, doğrulanmamış serbest
model anlatısı normal yanıt/geçmiş/dışa aktarma olmaz; eski konuşmalar silinmez,
"eski/doğrulanmamış" ele alınır; sayısal atıf veya PubMed kalite puanı iddianın
desteklendiğini göstermez.

C1 durum örnekleri (her biri Kadir'in ayrı sentetik testi olacak):

| Araç sonucu | Beklenen `answer_evidence` |
|---|---|
| `found` | `mode=source_extract`, en az bir geçerli alıntı |
| `no_record` (başarıyla tamamlanmış gerçek boş sonuç) | `mode=insufficient_evidence`, `items=[]`, "güvenli anlamına gelmez" bilgisi |
| `unresolved` | `mode=insufficient_evidence`, `unresolved_inputs` dolu |
| `incomplete` | varsa geçerli alıntılar + kontrol edilmeyenler ve sınırlamalar görünür |
| araç hatası | `checks[].status=error`, sonuç bilinmiyor |
| sağlayıcı/ulaşım hatası | mevcut terminal `error` olayı (answer_evidence ile başarı gibi sunulmaz) |

**C2 / Mevcut hasta kontrolü (onarım Onur, tüketim Halil) — R1-O1 PR'ında uygulandı, kabul bekliyor.**
`POST /api/drugs/analyze-patient`, Bearer, gövde `{patient_id: string, additional_drug_ids: string[] = []}`
(serbest `chronic_conditions/allergies/current_medications` gövdesi sözleşme değildir).
Yanıt mevcut `AnalyzePatientResponse` (değişmedi): `patient_id, status, current_drugs,
interactions, count, unresolved_medications, medication_matches, not_checked_over_limit,
pairs_checked, pairs_total, error, safe_alternatives=[], alternatives_note`;
etkileşim `description` orijinal metin, `severity=null`, `severity_status=not_rated`,
`source/source_url` korunur. 200 içinde `status=error` olabilir (HTTP 200 tek başına
başarı kanıtı değildir). Oturumsuz/geçersiz/süresi geçmiş token veya silinmiş kullanıcı
→ 401; yetkisiz → 403; olmayan hasta → 404; yanlış gövde → 422; erişim kontrolünde DB
hatası → 500 (analiz çağrılmaz). Kayıtlı ilaç listesine yazılmaz. Yetki: mevcut
politika (`users.service.resolve_patient_access`): doktor profili olan kullanıcı yalnız
kendisine atanmış hastayı; değilse hasta profili olan kullanıcı yalnız kendi kaydını.
Dış kimlikler (`user_id`, `patient_id`) yalnız kendi sütunlarıyla, sahiplik/atama iç
sayısal anahtarlarla karşılaştırılır.

**C3 / Parola değiştirme (Onur) — R1-O1 PR'ında uygulandı, kabul bekliyor.**
`POST /api/auth/change-password`, Bearer, `{current_password, new_password}`. Başarı
`200 {success: true, message: string}`; token yok/bozuk/süresi geçmiş/Bearer değil,
imzası doğru ama `userId` iddiası eksik/null/boş/metin olmayan token veya kullanıcı kaydı
yok → 401; yanlış mevcut parola (veya bcrypt olmayan kayıtlı değer) → 400; kurallara
uymayan yeni parola (UTF-8'de 72 baytı aşan dahil), eksik alan → 422; DB/commit hatası → 500
(`{"detail":"Password change failed"}`, başarı görünmez). Yalnız bu kullanıcının hash'i,
tek işlemde, mevcut doğrulamadan sonra değişir; başarısız denemede kayıt değişmez.
Not: gövde doğrulaması FastAPI'de yetki kontrolünden önce çalıştığı için **token'sız
ve aynı zamanda geçersiz gövdeli** istek 422 döner; token'sız geçerli gövde 401'dir.

### 4. Kabul edilen PR / SHA kaydı

| Görev | PR | Durum | Kabul edilen tam SHA | Entegrasyon merge SHA |
|---|---|---|---|---|
| R1-O1 | [#2](https://github.com/onurkilicce-ops/MedikaLLM/pull/2) `feat/onur/r1-baseline` → `team-test/2026-11-23-stage-0-1` (taslak) | `6350d0d…` denetlendi → **düzeltme istendi** (D1–D3); düzeltmeler PR'a eklendi, **yeniden denetim bekliyor** (bkz. 7. bölüm) | — | — |
| R1-K1 | — | Kabul edilmedi / bu kayıtta görülmedi | — | — |
| R1-H1 | — | Kabul edilmedi / bu kayıtta görülmedi | — | — |

Kadir ve Halil işleri bu kayıtta **tamamlanmış sayılmaz**; denetçi kabulünden sonra
tam SHA ile bu tabloya eklenir.

### 5. Çalıştırılan / atlanan kontroller (R1-O1, 2026-11-24)

Ortam: Windows 11 Pro 10.0.26200; Python 3.12.12 (uv ile); uv 0.10.7; Node 24.19.0 /
npm 11.17.0; Git 2.53.0; PostgreSQL 16.2 (pgvector + pg_trgm), bu çalışma için yeni
oluşturulmuş geçici küme (127.0.0.1:55433) ve iki yeni veritabanı (`medicallm_r1_synth`
testler, `medicallm_r1_app` uygulama açılışı). Docker bu bilgisayarda yok. Klon:
yeni klasör, `f549e59…` üzerinden `feat/onur/r1-baseline`.

| Kontrol | Sonuç |
|---|---|
| `uv lock --check` | Geçti (kilit değişmedi) |
| `uv sync --locked --python 3.12` (temiz `.venv`) | Geçti, 39 sn |
| Backend tam paket, katı mod (`MEDICALLM_STRICT_TESTS=1`, sentetik PG, tiktoken verisi hazır) | **240 geçti, 0 atlandı, 0 başarısız**; 15 test modülünün hepsi toplandı |
| Aynı, yeni testler düzeltilmemiş kaynağa karşı (`git stash -- backend/src`) | 46 yeni testten 28'i başarısız/hata (hatalar gerçekten yakalanıyor) |
| Katı mod, PG adresi yok | Toplama başında açık hata |
| Katı mod, tokenizer verisi yok + ağ kapalı | 2 test **başarısız** (katı olmayan modda aynı 2 test atlanıyor) |
| Sıfırlama koruması, onay değişkeni yok | `RuntimeError`, hiçbir şey silinmedi |
| Frontend `npm ci --no-audit --no-fund`, `npm test`, `npm run build` | 53 test geçti; derleme başarılı (yalnız mevcut paket boyutu uyarısı; npm 11 esbuild `allow-scripts` uyarısı) |
| Temiz açılış: `.env.example`→`.env`, `init_tables.py`, `uv run python run.py`, `npm run dev` | 26 tablo oluştu; `/health` `status=ok`, `db=ok`, `llm.api_key_configured=false`; arayüz 200 |
| Sentetik uçtan uca API (2 hekim kaydı, hekimin oluşturduğu hasta, C2 ve C3) | **18/18**; verisiz DB'de analiz `status=unresolved` (ilaçlar bulunamadı), kayıtlı ilaç listesi değişmedi |
| Arayüz: sentetik hekim girişi → /chat; Ayarlar → "Şifreyi değiştir" | "Şifre güncellendi"; eski parola 401, yeni 200 |
| GitHub Actions, run 45279282702 (PR #2, `c1989596…` birleşik ref `65c88244…`) | **Yeşil.** Backend: `uv lock --check` ✔, `uv sync --locked` (Py 3.12.12, 179 paket, 33 sn), gerçek paket importu ✔, `o200k_base` hazır, katı pytest **240 geçti** (8,8 sn), job 1 dk 22 sn. Frontend: 19 sn ✔. İlk push koşusu (`5c542da`) geçersiz workflow ifadesi (`runner` bağlamı job `env`'de) nedeniyle iş başlatamadı; `c198959` ile düzeltildi |
| **Canlı LLM (Groq) doğrulaması** | **Eksik.** Mevcut yapılandırmayla küçük bir çağrı bu oturumun izin kuralı tarafından engellendi; anahtar istenmedi. `/health` LLM'in çalıştığını göstermez |
| DrugBank verili gerçek DB | Yapılmadı (veri bu klonda yok; yeniden içe aktarma yapılmadı) |

### 6. Kalan engeller ve açık noktalar

- CI yeşil, ancak kilitli kurulum CUDA'lı torch (~3 GB) indiriyor; şimdilik 33 sn. GitHub, `actions/*@v4` ve `setup-uv@v6` için Node 20 kullanım dışı uyarısı veriyor (sürüm yükseltmesi ayrı, küçük iş).
- Canlı Groq akışı ve gerçek DrugBank verisiyle uçtan uca kontrol: anahtar/veri sahibi ekip üyesinin kendi bilgisayarında ayrıca.
- Halil: etkin `doctor/PatientDetail.jsx` `/api/session/query` yanıtında `response/content` bekliyor, backend `AgentResponse.messages` döndürüyor (R1-H1). C2 yanıt şekli değişmedi; gerçek birleşik kabul R1-O1 kabulünden sonra.
- Kadir: C1 üretimi (R1-K1). `citations.py` yalnız atıf numarası ve atıfsız satır sayar; kaynakta olmayan iddiayı yakalamaz (denetim bulgusu).
- Form A'nın imzalı sürümü ve güncel kapsam eki yok.
- Kapsam dışı kalanlar: lisans aktarımı, uzman değerlendirmesi, M-01–M-06 tam özellikleri, ücretli plan, dağıtım, hasta portalı.

### R1-O2 — Kontrol komutunun doğru sonuç vermesi (teslim; teknik denetim bekliyor)

Başlangıç: entegrasyon `f4ab516fc23d3f4fbdb201029bd06a94f28d0616`; dal `fix/onur/r1-live-check`.
M-06'nın çalışma altyapısını destekler; yeni tıbbi özellik veya klinik kabul değildir.
Uygulama kodu, API (C1–C3), şema, bağımlılık ve CI değişmedi.

Sorun (denetçinin sentetik koşumu; betik `f549e59` ile `f4ab516`'da aynı, blob `f71f593`):
`--skip-llm` + DB hatası, `--only does_not_exist`, ajan kurulum hatası ve `normal_chat` için
terminal `error` olayı — dördü de **çıkış kodu 0** veriyordu. R1-O1 kaynaklı değil.

Yeni davranış (`scripts/check_live_stack.py`, rapor `report_version: 2`; sözleşme README "Canlı yığın kontrolü"):
- `--only` bağlantıdan önce doğrulanır; boş/boş öğe/bilinmeyen ad → çıkış 2, DB ve sağlayıcıya dokunulmaz.
- DB: önce `transaction_read_only = on` doğrulanır, değilse başka hiçbir şey okunmaz; tablo başına `exists`/`count`;
  gerçek `0` ile okunamayan `null` ayrı; `drug_data` = `present`/`empty`/`partial`/`unknown`. DB ön koşulu
  başarısızsa ajan kurulmaz, sağlayıcı çağrılmaz.
- LLM: `skipped_by_flag` (bilinçli), `not_run_missing_key` (başarısızlık), `not_run_prerequisite_failed`, `ok`/`failed`.
  Senaryo yalnız terminal `done` + boş olmayan yanıt + kayıtlı sağlayıcı çağrısı (`llm_usage.calls ≥ 1`) ile başarılı;
  ilk başarısızlıktan sonra kalan senaryolar çalıştırılmaz.
- `overall.exit_code` = süreç çıkış kodu; `failures`, `llm_provider_verified`, `drugbank_data_present`.
  Hatalar yalnız istisna türüyle; rapor şifre/anahtar/URL içermez. Mevcut bayraklar korundu.

Kontroller (2026-11-24, yerel; Windows 11, Python 3.12.12, uv 0.10.7):

| Kontrol | Sonuç |
|---|---|
| `tests/test_check_live_stack.py` (çevrimdışı, sentetik sahte DB/ajan/oturum; `monkeypatch` ile, sızıntı yok) | **37 geçti** |
| Aynı testler `git archive f4ab516` geçici kopyasındaki eski betiğe karşı | **37 başarısız**; dört denetim kusuru, boş `--only`, salt okunur kapalı ve eksik anahtar testleri `assert 0 == 1/2` (eski betik 0 döndürüyor) |
| Katı tam paket (`MEDICALLM_STRICT_TESTS=1`, bu çalışmaya ait sentetik PG) | **342 geçti, 0 atlandı** (305 + 37); 16 test modülü toplandı; `uv lock --check` ✔ |
| Frontend `npm ci`, `npm test`, `npm run build` | 53 test ✔, derleme ✔ |
| GitHub CI (yeni commit) | PR'da görülecek |

Sınırlı canlı kontrol (sentetik sonuçlardan ayrı):

| Kontrol | Sonuç |
|---|---|
| **Gerçek Groq**, `--only normal_chat` (hastasız, tıbbi olmayan selam), mevcut yetkili yerel yapılandırma yalnız süreç ortamına aktarıldı (anahtar yazdırılmadı, kalıcı ayar değişmedi) | **Çıkış 0.** Terminal `done`; `llm_usage`: 1 çağrı, 2.393 giriş / 69 çıkış token (sağlayıcı bildirimi); 1,1 sn; yanıt 184 karakter; sağlayıcı oran sınırı başlıkları alındı (`provider_limits_after`). Sağlayıcı `api.groq.com`, model `openai/gpt-oss-20b` (değiştirilmedi). Bu koşumda DB, bu çalışma için oluşturulmuş **boş** sentetik geliştirme DB'siydi (`drug_data: empty`, salt okunur `on`) |
| **Gerçek DrugBank DB** (`--skip-llm`) | **Çıkış 0.** `transaction_read_only = on`; `drugs` **17.430**, `drug_synonyms` **33.839**, `drug_interactions` **2.855.848** (üç tablo var, `drug_data: present`); LLM `skipped_by_flag` (`llm_provider_verified: false`). Ortam: mevcut yerel küme düzensiz kapanmıştı (eski `postmaster.pid`, süreç yok); sahibin onayıyla geçici olarak `127.0.0.1:55434`'te sunucu düzeyinde `default_transaction_read_only=on` ile başlatıldı — PostgreSQL olağan kurtarmayı yaptı (redo 0 kB, 3 buffer) — kontrol sonrası düzgün kapatıldı. Seed/reset/migration/import yok; kalıcı yapılandırma değişmedi. Sayılar yalnız verinin bulunurluğunu gösterir, klinik içerik doğruluğunu değil |
| Dokuz senaryonun tamamı, ilaç soruları, hasta analizi | Kapsam dışı / çalıştırılmadı |

Bu canlı sonuç yalnız sınırlı bir sağlayıcı yanıtını doğrular; ilaç sorularının kaynak doğruluğunu, hasta
analizini, C1 birleşik akışını (Kadir/Halil) veya M-01–M-06 oranlarını kanıtlamaz. Geri alma: bu PR'ın ayrı
revert PR'ı yeterli; uygulama/veri geri yükleme gerekmez.

### 7. Denetim R1-O1-D1 (PR #2, denetlenen `6350d0de6dd90f2cef4f999b925399e173bce4d6`)

Denetçi kararı: **düzeltme istendi**. Korunan kazanımlar (denetçi doğruladı): parola
değiştirme import hatası giderildi; hasta analizindeki iç/dış kimlik karışıklığı düzeltildi;
`resolve_patient_access` ortak politika; CI run 45280426778'de backend 240, frontend 53
test + derleme başarılı. Denetçi temiz kurulumu ve 18 API kontrolünü yeniden çalıştırmadı;
canlı Groq ve gerçek DrugBank doğrulaması eksik.

| Bulgu | Sorun (6350d0d) | Düzeltme | Kanıt |
|---|---|---|---|
| D1 Test DB hedefi | Koruma URL'yi `urlparse` ile okuyordu; `…/audit_synth?dbname=unapproved_app` ve `…?host=unapproved.example.invalid` kabul ediliyordu, sürücü ise başka DB/host kullanıyordu (yeniden üretildi) | `synthetic_data.resolve_reset_target`: denetim psycopg2 lehçesinin `create_connect_args` çıktısı üzerinde; URL sorgu seçenekleri tamamen reddedilir; `PGHOSTADDR`/`PGSERVICE` tanımlıysa ret; yalnız `postgresql`/`postgresql+psycopg2`; doğrulanan URL nesnesiyle bağlanılır; bağlantıdan sonra `current_database()` onaylanan adla aynı olmalı. Önceki ad/loopback/onay/envanter korumaları aynen | 14 reddedilen URL + 2 ortam değişkeni testinde `create_engine`/`drop_all`/`create_all` hiç çağrılmıyor; sürücü hedefi = denetlenen hedef (3 URL); izinli sentetik DB sıfırlanmaya devam ediyor |
| D2 72 bayt | `ChangePasswordRequest` 73+ baytlık parolayı kabul ediyor, bcrypt 5 hash'te hata → 500 | `auth/models.py`: yeni parola UTF-8'de 72 baytı aşarsa doğrulama hatası (422, mesajda "72 bytes"); kesme yok, algoritma/migration yok | ASCII 72 bayt ve 38 karakter/72 bayt (`ü`) uçtan uca 200, eski parola 401, yeni 200, son karakter eksikken 401; 73/74 bayt 422, kayıt değişmiyor; birim: 3 kabul, 3 ret (2 ve 3 baytlık karakterler) |
| D3 `userId`siz token | `verify_token` `payload["userId"]` → `KeyError` → change-password 500 (hız sınırlayıcının anahtar fonksiyonunda da aynı yol) | `verify_token`: yalnız JWT hataları ve eksik/null/boş/boşluk/metin olmayan `userId` → `ValueError("Invalid token")` → 401. Kimlik biçimi daraltılmadı; diğer istisnalar gizlenmiyor | 8 bozuk iddia biçimi × (verify_token, change-password, analyze-patient): 401, parola/analiz servisi ve DB oturumu çağrılmıyor; geçerli/süresi geçmiş/yanlış imzalı token davranışı aynı |

Ek (uygulayıcının kendi bağımsız 3 ajanlı adversarial incelemesi, salt okunur):
- D1 için `reset_and_seed`'in bağlantı sonrası `current_database()` denetimini gerçekten
  çalıştırdığını gösteren test eksikti → eklendi (sahte bağlantı başka DB bildirince
  DROP/CREATE yok, yalnız okuma sorgusu).
- JSON'da eşsiz UTF-16 vekil karakter (`"\ud800"`) içeren parola alanı, FastAPI'nin
  varsayılan 422 işleyicisi girdiyi geri yansıtırken UTF-8 kodlayamadığı için **500**
  veriyordu (yeniden üretildi; uygulama genelinde, doğrulama hatası olan her alan için).
  `src/main.py`: aynı durum kodu ve gövdeyle (`{"detail": jsonable_encoder(exc.errors())}`)
  ama ASCII-kaçışlı JSON üreten `RequestValidationError` işleyicisi → 422. Ayrıştırılan veri
  varsayılanla aynı; diğer 422 testleri değişmeden geçiyor.
- Anahtarla imzalanmış `exp`/`nbf` = sonsuz token PyJWT'de `OverflowError` → 500 (önceden
  vardı, yalnız imza anahtarına sahip biri üretebilir) → `verify_token` bunu "Invalid token"
  sayar → 401. Diğer istisnalar 401'e çevrilmedi.
- İnceleyicinin denediği ve **sorun bulmadığı** yollar: yüzde kodlama, userinfo hileleri,
  IPv6/`0.0.0.0`/`localhost.`, unix soketi, çoklu host, `PGHOST`/`PGDATABASE`
  (açık değerler önceliklidir), boş `PGSERVICE`; 4 baytlık emoji ve birleşik karakterlerle
  72 bayt sınırı; NUL içeren parola (bcrypt 5 kesmiyor); 100 baytlık mevcut parola → 400.

Regresyon kanıtı: yeni testler `git archive 6350d0d` ile ayrı geçici kopyaya alınıp
çalıştırıldı → **49 başarısız** (D1 15, D2 7, D3 22, inceleme ekleri 5; 74 geçti —
eski sürümün zaten doğru olduğu sınır durumları). Düzeltilmiş ağaçta katı mod
(`MEDICALLM_STRICT_TESTS=1`, sentetik PG): **305 geçti, 0 atlandı** (240 + 65 yeni).
`uv lock --check` ✔; frontend `npm ci`, 53 test, derleme ✔. Kilit/bağımlılık/CI değişmedi.
Not: kayıt (`/verification-code`) ve parola sıfırlama akışları 72 baytı aşan parolada
500 değil 400 döner (hata kod adımında yakalanıyor); bu turda değiştirilmedi.

### M02-O1 — Kaynaklı zaman verileri ve bağımsız API (teslim; bağımsız denetim bekliyor)

**Sahiplik kararı (kullanıcı, 2026-11-24):** M-02 (Form A, s.5) Onur Kılıç'a verildi.
Onur'a ayrılan sonraki alanlar: `backend/src/timing/**`, `frontend/src/features/timing/**`,
`frontend/src/pages/MetabolismTiming.jsx` (ortak `frontend/src/main.jsx` yönlendirmesi
Halil'de; gerekince entegrasyonda koordine edilir). Kadir (R1-K1/C1) ve Halil (R1-H1)
işlerine dokunulmadı. Form A hâlâ imzasız "Before Edit With Client" taslağıdır.

| Alan | Değer |
|---|---|
| Dal / taban | `feat/onur/m02-timing`, `c86dcc121047fe94a87b38245e8f467045afdb07`'den açıldı (entegrasyon ucu aynıydı; dal yoktu) |
| Bu teslim | Salt okunur `POST /api/timing/compare` + kural tabanlı ayrıştırıcı + ≈5× yarılanma ömrü nesnesi + salt okunur envanter betiği |
| Sözleşme | `backend/src/timing/API.md` (`m02-timing-compare/1`), kurallar `backend/src/timing/RULES.md` (`m02-text-parser/1`), OpenAPI |
| Değişmeyen | Şema/migration, bağımlılık/kilit, CI, frontend, `drugs/`, auth, ortak fixture'lar, C1–C3 |
| M-02 tamam mı? | **Hayır.** Ekran (ortak zaman çizelgesi), kaynaklı zaman aralığı önerileri (ilaç–gıda örnekleri dahil, ör. kalsiyumdan etkilenen antibiyotik), sohbet bağlantısı ve Form A ≥%90 uzman kabulü yapılmadı |

Önemli kararlar: (1) LLM yok; nesnel düzenli ifade kuralları, kural dışı metin değer
değil inceleme kalemi olur (güven yüzdesi yok). (2) `get_user_by_id` DB hatasını
"kullanıcı yok"a çevirdiği ve `drugs.service.get_drug` hataları `None` yaptığı için M-02
kendi küçük okuma yolunu kullanır (`timing/repository.py`): her okuma `SET TRANSACTION
READ ONLY`, yalnız gereken sütunlar ve satır içi belirteçle eşleşen referans satırları;
her DB hatası 503. Yetki: mevcut Bearer + `verify_token`, profesyonel = doktor profili
(mevcut `is_doctor` tanımı); yeni rol yok. (3) Değer ile türetilmiş süre ayrı nesneler;
aralık sınırları ayrı çarpılır; Tmax eklenmez. (4) `timing_advice.status=not_evaluated`,
`advice=[]`.

**Kanıt (2026-11-24, Windows 11, Python 3.12.12, uv 0.10.7, PostgreSQL 16.2 portatif;
bu çalışma için açılan geçici küme `127.0.0.1:55440`, `medicallm_m02_synth`):**

| Kontrol | Sonuç |
|---|---|
| Taban `c86dcc1`, katı mod, sentetik PG | 342 geçti, 0 atlandı (önceki kayıtla aynı) |
| Önceden kaydedilmiş beklenen sonuç tabloları (`tests/fixtures/m02_cases_*.json`, 94 sentetik durum) | Yalnız RULES.md + tipli sözleşmeden, uygulamayı görmeyen iki bağımsız ajan yazdı; ilk koşudan **önce** SHA-256 alındı (`0d872a9e…`, `f9587908…`) ve sonra değişmedi. İlk koşu 87/94: 3 gerçek uygulama hatası + kurallarda olmayan 1 sessiz "iyileştirme" bulundu; uygulama düzeltildi, tablolar değil |
| Bağımsız adversarial inceleme, 1. tur (3 mercek + doğrulayıcı) | 23 bulgunun 21'i yeniden üretildi ve gerçek kusur sayıldı (Unicode tire aralıkları, boşluksuz `.[A1]`, `AUC0–24h`, "from X to Y" değişimi, sayı listeleri, başka olay süreleri, koşul kayması, referans paylaşımı, ASCII olmayan kimlik, OpenAPI zorunlu alanları …). Hepsi düzeltildi; regresyon testleri `test_m02_review_regressions.py` |
| 2. tur (düzeltmelerin getirdiği hatalara odaklı + ön bilgisiz mercek, doğrulayıcı) | 19 bulgunun 19'u yeniden üretildi (saat yazımı `1:30`, olumsuz karşılaştırma, değişim fiilleri, `1 h 30 min`, eşli ölçüm listeleri, başka olay cümlecikleri, eşgüdümlü koşullar, giriş ifadesinin karşıt gruba taşınması, parantez içi `;`, 0'a yuvarlanma/`inf`, `i.v.` sonrası cümle sonu …). Genel kurallarla düzeltildi (RULES.md 8a); regresyon testleri `test_m02_review_round2.py`. Üçüncü tur çalıştırılmadı |
| M-02 testleri | Birim: ayrıştırıcı/hesap/model (94 önceden kayıtlı + görev örnekleri + regresyonlar); entegrasyon: HTTP → yetki → servis → sentetik PG (200 kaynaklı / eksik veri / bilinmeyen / tümü bilinmeyen / 10 sınırı, 401 ×6, 403 ×2, 422 ×14, 503 ×3 [kullanıcı okuması, ilaç okuması, sorgu hatası], salt okunur işlem ve yazma yok, LLM çağrısı yok, OpenAPI) ve envanter betiği |
| Katı tam paket (`MEDICALLM_STRICT_TESTS=1`), `uv lock --check` | **612 geçti, 0 atlandı** (342 + 270 M-02); kilit temiz |
| Frontend `npm ci`, `npm test`, `npm run build` (değiştirilmedi) | 5 dosya, 53 test geçti; derleme başarılı (yalnız mevcut npm 11 `allow-scripts` uyarısı; kilit dosyası değişmedi) |
| README'deki 5 adım, ayrı `medicallm_demo_synth` ile birebir | Uygulama açıldı (`/health` db ok); iki ilaç: Tmax 0,5–1 sa (uygulamadan sonra), yarılanma ömrü 4–6 sa, ayrı türetilmiş 20–30 sa `includes_tmax=false`; diğer ilaç `tmax=placeholder`, 1,5 sa (sağlıklı yetişkin) ve 3 sa (böbrek yetmezliği) ayrı; token'sız 401, yinelenen kimlik 422, doktor profili olmayan 403 |
| GitHub CI (`6776fac`) | Run 45452132496, geçici PR birleşimi `469b43f…` (ebeveynler `c86dcc1` + `6776fac`, ağaç = teslim head ağacı `a5ee95b…`): katı backend **612 geçti**; frontend 53 test + derleme ✔ (denetçi kaydı) |

**Gerçek veri envanteri — tarihsel, `m02-text-parser/1`** (bu sayılar `6776fac`'teki
ayrıştırıcıya aittir; M02-O1-D1'deki `m02-text-parser/2` için gerçek küme **yeniden
sayılmadı**, aşağıdaki sayılar yeni sürüm için doğrulanmış değildir). (Sahibin onayıyla; mevcut yerel küme kapalıydı,
geçici olarak yalnız `127.0.0.1:55434`'te sunucu düzeyinde `default_transaction_read_only=on`
ile açıldı — önceden düzgün kapatılmıştı, kurtarma gerekmedi — `scripts/audit_m02_data.py`
ile okundu, sonra düzgün kapatıldı. Ayrıştırıcı düzeltmelerinden sonra aynı prosedürle bir
kez daha açılıp kapatıldı; kapanış kontrol noktaları 0 ve 3 tampon, WAL mesafesi her ikisinde
0 kB (salt okunur okumada oluşabilen ipucu bitleri; veri değiştiren işlem yok). Seed, reset,
migration, uygulama açılışı yok; kullanıcı/hasta/sohbet tabloları okunmadı; metin, ad,
URL rapora/Git'e girmedi). Sayılar ayrıştırıcının son sürümüyle (`parser.py` SHA-256
`70ce1569…`, `calc.py` `10693aca…`):

| | `half_life` | `absorption` |
|---|---|---|
| Toplam ilaç | 17.430 | 17.430 |
| Boş / yer tutucu / metin var | 14.959 / 10 / 2.461 | 14.910 / 1 / 2.519 |
| Olası kesilme (tam 1000 karakter) | 3 (1000'i aşan 0) | — (Text) |
| Alan durumu: `parsed` / `parsed_needs_review` / `unparsed_needs_review` / `no_statement_found` | 1.854 / 127 / 480 / — | 597 / 48 / 691 / 1.183 |
| Yapılandırılan ölçüm (incelemeli) | 2.671 (372) | 802 Tmax (124) |
| Ölçüm tabanı: değer sözcüğü / cümle sözcüğü / yalnız alan | 1.870 / 233 / 568 | 755 / 47 / — |
| Anahtar sözcük geçen alan / bunlardan ölçümsüz | 1.614 / 201 | 843 / 198 |
| Ölçüm referans durumu: eşleşen / belirteçsiz / kısmen / eşleşmeyen | 1.377 / 1.257 / 4 / 33 | 325 / 461 / 4 / 12 |
| Koşul taşıyan ölçüm | 1.551 | 589 |
| Çelişki grubundaki ölçüm | 218 | 83 |

≈5× yarılanma ömrü: 1.928 hesaplandı, 743 hesaplanmadı (gerekçeler raporda; ör. çelişki
218, çok fazlı belirsizlik 178, paralel liste 97, metabolit 87 + başka yerde metabolit 90,
`respectively` 83, koşul atfı belirsiz 73, insan dışı/in vitro 45, fiziksel bozunma 23).
Yalnız sayılan alanlar (ayrıştırılmadı): `metabolism` metin 2.408, `clearance` 1.666,
`route_of_elimination` 2.072. Referans satırı olan ilaç: 4.525.

Sayım yöntemi: her satır `parse_field` ile işlendi; "ayrıştırılabilir" = kuralların
inceleme işareti olmadan değer ürettiği durum; anahtar sözcük sayısı kullanılabilir Tmax
sayısı değildir. **Bu sayılar doğruluk ölçümü değildir.** Uygulayıcının yerel nokta
kontrolü (uzman değil; sabit tohumlu 4 rastgele örnek × 60 ölçüm, her biri önceki
düzeltmelerden sonra çekildi; metinler kayda alınmadı): yanıltıcı çıktı (yanlış ölçüm
türü, başka değere taşınmış koşul veya uygulanamaz ≈5×) örnek 1'de 7, örnek 2'de 3,
örnek 3'te 4, örnek 4'te 2 (Tmax 0/30; yarılanma ömrü: sözlükte olmayan hayvan türü ve
radyoaktif "physical half-life"). Hepsi kurala bağlanıp regresyon testi eklendi; örnek 4
düzeltmesinden sonra yeni örnek çekilmedi. Bu sayılar tek kişinin küçük örnekte
yargısıdır; gerçek doğruluk oranı **bilinmiyor**. Sayısal değer/birim dönüşümü hatası
örneklerde görülmedi; kalan bilinen zayıflık koşul atfıdır (sözlükte olmayan hasta
grupları/türler, karmaşık karşılaştırma cümleleri) — kural belirsizlikte değeri işaretler
veya incelemeye bırakır, bu da bazı doğru değerlerin inceleme gerektirmesine yol açar.

**Açık işler / sonraki teslim önerisi:** (1) Uzmanın önceden sabitlediği referans ilaç
kümesi; doğru / yanlış / yanıtsız / veri kapsamı ayrı sayılır, eksikler paydadan sessizce
çıkarılmaz. (2) Kaynaklı yönlü zaman önerileri (`timing_advice`), Form A'daki ilaç–gıda
örnekleri dahil; "arandı ama uygun kanıt yok" durumu ayrı tanımlanacak. (3) Onur'un
`MetabolismTiming` ekranı (Halil ile yönlendirme). (4) Birleşik kabul.
Ortak dosya talebi: yok. Geri alma: bu PR'ın revert'i yeterli (yalnız yeni modül,
`main.py`'de 2 satır, README/STATUS bölümü); veri değişikliği yok, geri yükleme gerekmez.

#### M02-O1-D1 — Bağımsız denetim düzeltmeleri (Astra, denetlenen `6776fac`; düzeltme teslimi, yeniden denetim bekliyor)

Denetçi kararı: düzeltme gerekli (D1–D6). Hepsi önce `6776fac`'te yeniden üretildi
(HTTP → gerçek router/yetki/servis/yanıt; yalnız DB okuma sınırı sentetik satırlarla
değiştirildi; D6 sahte yapılandırmayla yeni PowerShell sürecinde), sonra düzeltildi.

| Bulgu | `6776fac` (gözlenen) | Şimdi | Değişen |
|---|---|---|---|
| D1 olumsuzlama | `is not 4 hours`, `has not been established`, `Tmax was not 2 hours` → temiz değer (≈5× 20 sa); `without renal impairment` → `renal impairment` | Olumsuz/belirlenmemiş değer ölçüm değil (`negated_value`, `undetermined_statement`); koşul metni olumsuzlamayla korunur (`without renal impairment`) + `negated_condition`, ≈5× yok. `not less than`/`no more than` sınırları aynen | parser |
| D2 bağlam | `dogs`, `extended-release` (ayrı cümle), `burn patients` kayboluyor; temiz, 20 sa | Değersiz cümledeki formülasyon/nüfus/tür kapsamı → `field_context_unattributed`; alanda insan dışı tür → `non_human_context_in_field`; ≈5× yok. Aynı cümlecikteki sözlük dışı grup yakalanır (`burn patients`, temiz). Değer kendi koşulunu söylüyorsa taşınmaz/işaretlenmez | parser |
| D3 özne | Drug B'nin 10 sa'i Drug A ölçümü, ≈5× 50 sa | Karşılaştırma yapısı (`unlike`, `compared with` …) → `subject_unresolved_comparison`; kayıt adı dışındaki büyük harfli özne (`half-life of Drug B`, `for Drug B`) → `subject_not_record_drug`; değer üretilmez. Metabolit, eş zamanlı ürün ve koşul sözcükleri özne sayılmaz | parser, service (kayıt adı) |
| D4 referans | `…; duration of effect … 9 hours.[A2]` → 4 sa'e A2, `sentence_single_value`, doğrulanmış | Belirteç kendi `;` cümleciğine ait: `sentence_other_clause`, bağlanmaz, `nearby_reference_tokens`; aynı cümlecikte başka iddia → `sentence_shared`. `primary_reference_verified` → `stored_reference_attributed` (saklı eşleme; dış kaynak doğrulaması değil) | parser, models, service |
| D5 yayılım | `4 ± 1 hours` → türetilmişte yayılım yok; `4 ± 9…9 days` → JSON'da `null` yayılım, temiz, 480 sa | ≈5× nesnesi `dispersion {statistic: not_stated, value_hours: 5}` taşır (yorum yok); sonlu olmayan/0'a yuvarlanan yayılım → inceleme, değer yok; türetilmişte `invalid_dispersion` | parser, calc, models |
| D6 README | Yeni terminalde `$env:DO_POSTGRES_URL = $env:DEMO_URL` değişkeni siliyor, ayar `.env`'deki uygulama DB'sine dönüyor | 4. adım kendi başına: hedefi açıkça yazar, `uv run python -m src.timing.demo_guard` (yalnız süreç ortamı; tanımlı, loopback, sorgusuz, `_synth` = `M02_DEMO_CONFIRM`, salt okunur bağlanıp `current_database()` ve sentetik olmayan kullanıcı yokluğu) çıkış 0 vermeden `run.py` çalışmaz | README, `src/timing/demo_guard.py` |

Sürüm: `m02-text-parser/2`, `m02-timing-compare/2` (alan adı değişikliği ve yeni alanlar;
tüketici notu `backend/src/timing/API.md` → "Sürüm 2 değişiklikleri"). Şema, migration,
bağımlılık, CI, frontend, `main.py` değişmedi.

Değişen eski test beklentileri (gerekçeli): (1) sürüm dizeleri `/1` → `/2`;
(2) `primary_reference_verified` → `stored_reference_attributed`; (3) `test_m02_core`:
`in elderly patients` artık `elderly` değil metindeki tam grup `elderly patients`.
Bu turda kendi yazdığım iki beklenti sözleşmeye göre değişti: `… is unknown but may be
about 4 hours` artık atılmıyor, `hedged_value` ile işaretli tutuluyor; `Similar to other
agents …, the half-life is 6 hours` değeri tutulup `comparison_in_clause` ile işaretleniyor
(yalnız karşılaştırılanın ilgi cümleciğindeki değer atılıyor).
Önceden kaydedilmiş 94 durumluk tablolar değişmedi ve geçiyor.

Kanıt (2026-11-25, yerel; ayrı sentetik PG `127.0.0.1:55440`, `medicallm_m02_synth`):

| Kontrol | Sonuç |
|---|---|
| Yeniden üretim betiği (13 sentetik metin, HTTP yolu) `6776fac` → son kod | Önce 13/13 bulgudaki davranış; sonra D1 a–c değer yok, d işaretli (`without renal impairment`); D2 a–b işaretli, c `burn patients` koşuluyla temiz; D3 değer yok (`subject_unresolved_comparison`); D4 a–b `sentence_other_clause`, olumlu örnekte yalnız A1; D5 a yayılım ×5 taşınıyor, b değer yok (`invalid_value`) |
| Yeni testler | `test_m02_audit_d1_d6.py` (olumlu / yakın / olumsuz örnekler, demo doğrulayıcı, yeni süreçte `.env`'ye dönmeme, README sırası), `test_m02_audit_round3.py` (bağımsız incelemenin iki yönü), `test_m02_audit_http_pg.py` (HTTP → sentetik PG; D1–D6), `test_m02_api_doc.py` (API.md tam örneği = gerçek çıktı) |
| Bağımsız inceleme turu (2 mercek + doğrulayıcı; düzeltmelerin bypass'ı ve aşırı reddi) | 19 bulgunun 19'u yeniden üretildi. Aşırı ret 9 (en önemlisi: `administration` içindeki `rat` alt dizesi eş zamanlı kullanım cümlelerini insan dışı sayıyordu; `No dose adjustment … as the half-life is 4 hours` reddediliyordu; değersiz sıradan cümleler bağlam sayılıyordu). Bypass 10 (`isn't`, kapalı fiil listesi, başka özne kalıpları, birimden sonra ya da adla yazılan yayılım, `PGHOSTADDR`/`PGSERVICE`). Hepsi genel kurallarla düzeltildi (RULES.md 8b); `test_m02_audit_round3.py` iki yönü de sınıyor (20 açık cümle temiz kalmalı, 34 varyant temiz olmamalı). Bu düzeltmelerden sonra ayrı bir inceleme turu çalıştırılmadı |
| Katı tam paket (`MEDICALLM_STRICT_TESTS=1`), `uv lock --check` | **722 geçti, 0 atlandı** (taban 342 + M-02 380); kilit temiz; önceden kaydedilmiş fixture özetleri değişmedi |
| README 4. adım, yeni PowerShell süreçleri | Değişken yok → `REFUSED … not set in this terminal`; sentetik olmayan hedef → `REFUSED … does not end with '_synth'`; doğru hedef → `OK …`; ardından uygulama açıldı, 5. adım: `schema=m02-timing-compare/2`, Tmax 0,5–1 sa, yarılanma ömrü 4–6 sa, ≈5× 20–30 sa `includes_tmax=false`, ikinci ilaç 1,5 sa (healthy adults) / 3 sa (patients with renal impairment) |
| Frontend (değişmedi) | Bu turda yerelde çalıştırılmadı; frontend dosyası değişmedi, sonuç CI'dan |
| GitHub CI (`51b2d56`) | Run 45550798857 (denetçi kaydı): katı backend **722 geçti**, frontend 53 test + derleme ✔; checkout `aadff34…` (geçici PR birleşimi, ağaç = teslim head'i) |

Çalıştırılmayanlar: gerçek DrugBank kümesi bu turda başlatılmadı/yeniden sayılmadı
(sayılar `parser/1`'e ait, tarihsel); uzman kabulü yok; başarı yüzdesi üretilmedi;
bu turdaki son düzeltmelerden sonra ayrı bağımsız inceleme turu yapılmadı.

Kalan bilinen sınırlamalar: genel ilaç adı tanıma yok (küçük harfle yazılmış başka ilaç
adı yakalanmaz; marka adı kayıt ilacından ayırt edilemez → incelemeye düşer); kural
listesi dışındaki olumsuzlama/belirsizlik kalıpları ve sözlük dışı tür/grup adları
kaçabilir; değer dışı bağlam yalnız açık kapsam cümlelerinde tanınır. Kural
belirsizlikte değeri işaretler ya da atar; bu da bazı doğru değerlerin incelemeye
düşmesine yol açar.

Kadir/Halil için: C1 ve mevcut ekranlar değişmedi. M-02 tüketicisi ileride
`stored_reference_attributed`'ı "kaynak doğrulandı" diye göstermemeli; alan değişiklikleri
`backend/src/timing/API.md` → "Sürüm 2 değişiklikleri". Ortak dosya talebi yok. Geri alma:
bu düzeltme commit'inin revert'i (veri/şema değişikliği yok).

#### M02-O1-R2 — Yeniden denetim düzeltmeleri (Astra, denetlenen `51b2d56`; teslim, yeniden denetim bekliyor)

Not: PR #5 açıklamasındaki "612 test" ilk teslimin (`6776fac`) özetidir; güncel durum bu
bölümdedir. Denetçi kararı: D1–D4 kısmen açık; D5/D6 kapalı. Dört bulgu önce `51b2d56`'te
yeniden üretildi (gerçek router → token/yetki → servis → JSON; yalnız repository okuma sınırı
sentetik satırlarla değiştirildi; kayıt adı `[SYNTHETIC] Drug A`, saklı referanslar A1/A2),
sonra düzeltildi.

| Bulgu | `51b2d56` (HTTP çıktısı) | Şimdi (HTTP çıktısı) |
|---|---|---|
| D1 üst cümlecik | `There is no evidence that …`, `It is not known whether …`, `If … were 4 hours` → temiz 4 sa, ≈5× 20 sa; `It has not been established that Tmax is 2 hours` → temiz 2 sa | Ölçüm yok; `undetermined_statement` / `hypothetical_or_open_question` inceleme kalemi, metin korunuyor. `No dose adjustment … as the half-life is 4 hours`, `not less than 4 hours`, açık değerler temiz |
| D2 tür kapsamı | `In dogs, elimination was studied. The half-life is 4 hours.` → `other=[]`, temiz, 20 sa | `field_context_unattributed` + `non_human_context_in_field`, ≈5× yok. `These data were obtained in dogs. In humans, …` temiz (`other=["humans"]`); P-gp gibi başka konudaki tür cümlesi değeri etkilemiyor |
| D3 küçük harfli özne | `The half-life of drug b …`, `drug b has a half-life …` → Drug A altında temiz 10 sa, ≈5× 50 sa | Ölçüm yok, `subject_unresolved`. `The half-life of drug a/Drug A is 4 hours`, `the drug`, `elimination`, formülasyon, metabolit, `co-administered with drug c` korunuyor |
| D4 iddia içi atıf | Pencere içindeki başka iddianın A2'si → `inline_reference_tokens=[A2]` / `[A1, A2]`, `value_window`, `stored_reference_attributed=true` | A2 yalnız `nearby_reference_tokens`; A1 açıkça değerin iddiasındaysa `value_window` ve yalnız `[A1]`. `4 hours.[A1]` ve önceki `;` düzeltmesi aynen |

Tasarım kararı: yeni NLP/LLM yok. Mevcut cümlecik sınırları kullanıldı. (1) Değeri açan
bağlaç (`that`/`whether`/`if`) ve onu yöneten üst cümlecik okunuyor. (2) Tür + farmakokinetik
sözcüklü değersiz cümle kapsam sayılıyor. (3) Özne konumları harf büyüklüğünden bağımsız
okunuyor, kayıt adıyla karşılaştırılıyor. (4) Belirteç, değerin kendi iddia aralığı
içindeyse bağlanıyor. Ayrıntı RULES.md 8c.

Sürüm: ayrıştırıcı `m02-text-parser/3`; API yapısı değişmediği için sözleşme
`m02-timing-compare/2` kaldı (yalnız yeni gerekçe kodları; tüketici notu API.md
"Ayrıştırıcı 3"). Şema, bağımlılık, CI, frontend, `main.py`, D5/D6 kodu değişmedi.

Değişen eski beklentiler: (1) `… 4 hours and adverse events are described elsewhere.[A2]`:
`sentence_shared` + A2 değerin listesinde → `sentence_other_clause` + A2 `nearby` (D4'ün
istediği ayrım). (2) Sürüm dizeleri `parser/2` → `/3`. Ayrıca `half-life of elimination` artık
yarılanma ömrü ifadesi sayılıyor (eskiden `elimination` rakip ölçüm sayılıp değer
düşüyordu). Önceden kaydedilmiş 94 durum değişmedi ve geçiyor.

Kanıt (2026-11-25, yerel; ayrı sentetik PG `127.0.0.1:55440`):

| Kontrol | Sonuç |
|---|---|
| Yeniden üretim (20 sentetik metin, HTTP) `51b2d56` → son kod | Önce D1 1–4, D2.1, D3 1–2, D4 1–3 hatalı (11/11); sonra hepsi düzeltilmiş; olumlu 9 kontrol aynı |
| D4/D5 eski örnekleri (`repro_d1_d6`) | D4 `;` örnekleri `sentence_other_clause`; olumlu `[A1]` `sentence_single_value`; D5 `4 ± 1` → 20 ± 5 sa, taşan yayılım incelemede |
| Yeni testler | `test_m02_audit_r2.py` (D1–D4 olumlu / olumsuz / yakın + birleşik örnek), `test_m02_audit_r2_http_pg.py` (HTTP → sentetik PG: kimlik, gerekçe, koşul, alıntı/ofset, atıf listeleri, derived; D5 korunuyor) |
| Katı tam paket (`MEDICALLM_STRICT_TESTS=1`) | **757 geçti, 0 atlandı** (taban 342 + M-02 415) |
| GitHub CI | Son commit için PR sayfasında; bu kayıt CI sonucu için ayrıca güncellenmeyecek |

Bilinen sınırlar: kayıt adının eşanlamlısı/markası özne olarak yazılırsa incelemeye düşer;
kural listesi dışındaki yöneten fiiller ve sözlük dışı türler kaçabilir. Uzman kabulü yok;
gerçek veri bu turda açılmadı. Geri alma: bu R2 commit'inin revert'i.

#### M02-O1-R3 — Üçüncü denetim düzeltmeleri (Astra, denetlenen `844f3bb`; teslim, yeniden denetim bekliyor)

Önceki tur (R2, `844f3bb`) için CI: çalıştırma 45625761298 başarılı (backend 757,
frontend 53 + build). Checkout SHA `4bec90ba03173efb07e8a42b55ea7a486d588684` (PR birleştirme
önizlemesi).

Denetçinin kararı: D1, D3 ve D4'te açık yollar var. Sekiz sentetik örneğin hepsi önce
`844f3bb`'de yeniden üretildi, sonra düzeltildi. Yol gerçek router → token/yetki → servis →
JSON; yalnız repository okuma sınırı sentetik satırlarla değiştirildi (kayıt adı
`[SYNTHETIC] Drug A`, saklı referanslar A1/A2).

| Örnek | `844f3bb` (HTTP) | Şimdi (HTTP) |
|---|---|---|
| D1.1 `There is no evidence that, in adults, the half-life is 4 hours.` | temiz 4 sa, `population=[adults]`, ≈5× 20 sa | ölçüm yok, `undetermined_statement` |
| D1.2 `… that the half-life, measured in adults, is 4 hours.` | temiz 4 sa, 20 sa | ölçüm yok, `undetermined_statement` |
| D1.3 `Studies failed to establish that the half-life is 4 hours.` | temiz 4 sa, 20 sa | ölçüm yok, `undetermined_statement` |
| D1.4 `It is not known whether, after oral administration, Tmax is 2 hours.` | temiz Tmax 2 sa | ölçüm yok, `hypothetical_or_open_question` |
| D3.1 `drug b's half-life is 10 hours.` | Drug A altında temiz 10 sa, 50 sa | ölçüm yok, `subject_unresolved` |
| D3.2 `For drug b, the half-life is 10 hours.` | temiz 10 sa, 50 sa | ölçüm yok, `subject_unresolved` |
| D4.1 `The half-life is 4 hours (adverse events are described elsewhere [A2]).` | `inline=[A2]`, `value_window`, `stored_reference_attributed=true` | `inline=[]`, `references=[]`, `nearby=[A2]`, `none`, `false` |
| D4.2 `The half-life is 4 hours: adverse events are described elsewhere [A2] in the report.` | aynı hata (A2 bağlı) | aynı düzeltme (A2 yalnız `nearby`) |

Olumlu eşler hem önce hem sonra temiz ve aynı kaldı:
- `Studies have shown that, in adults, …` → 20 sa, `adults`;
- `No dose adjustment … as the half-life is 4 hours`;
- `not less than 4 hours` (alt sınır);
- `drug a's` / `For drug a,` ile büyük harfli eşleri;
- `4 hours.[A1]`, `4 hours, in adults.[A1]`, `4.5 hours.[A1]` → `[A1]`,
  `sentence_single_value`, `true`;
- A1 ile ilgisiz cümledeki A2 ayrı kalıyor.

Büyük ve küçük harfli `Drug B's` / `drug b's` ile `For Drug B,` / `For drug b,` artık aynı
davranıyor: ikisinde de ölçüm yok.

Birleşik örnekler:
- `There is no evidence that, for drug b, the half-life (measured in adults) is 4 hours
  [A2].` → ölçüm yok.
- `Studies have shown that, for drug a, the half-life is 4 hours (adverse events are
  described elsewhere [A2]).[A1]` → temiz, 20 sa; A2 bağlanmıyor, A1 ayrı iddiadan sonra
  geldiği için `sentence_other_clause`.
- `drug b's half-life is 10 hours: adverse events … [A2]. drug a's half-life is 4 hours.[A1]`
  → 10 sa düşüyor, 4 sa kalıyor; A2 bağlanmıyor.

Bağımsız çürütme taraması: ilk düzeltmeden sonra ayrı ajanlar parser'ı yürüterek açık
aradı (D1/D3/D4 merceği). Doğrulanan yollar aynı turda genel kurallarla kapatıldı ve
testlere eklendi:
- D1:
  - `, however, that`;
  - `failed, despite …, to establish`;
  - ara ifade içindeki `never confirmed` / `possibly` / `if confirmed`;
  - zincirleme `that`;
  - `remains to be shown`, `is false/mistaken`;
  - soru cümlesi;
  - `never shorter than` (önceden yanlışlıkla üst sınır okunuyordu).
- D3: `compound a`, `For drug b and drug c,`, `comparator drug's`, çoğul `drugs'`, `ʼ`/`` ` ``
  kesmeleri, başka ilacın metaboliti, `drug b reaches peak …`, aynı cümlede öznesiz ikinci
  değer.
- D4: `(rash is common) [A2]`; `(e.g. …)`, `(n = 12, SD 1.1)`, `(Smith et al. [A1])`
  içinde/sonrasında A1'in kaybolması.
- İlk düzeltmenin getirdiği aşırı ret: `…, but in children, 4 hours`, `For oral
  administration,`, `drug a hydrochloride`, `Japanese subjects`, `ER tablets`.

D3 doğrulayıcılarının bir kısmı kullanım sınırına takıldı; o bulgular burada yürütülerek
doğrulandı. İkinci bir ajan taraması yapılamadı.

Tasarım kararı: yeni NLP/LLM yok; kurallar RULES.md 8d'de.
- (1) Virgüllü ara ifadeler cümlecik çözümlemesinde boşlanır, içerikleri ayrıca okunur.
  Bağlaç sözcüğüyle başlayan parça ara ifade sayılmaz.
- (2) Özne adayları her harf büyüklüğünde, kalıntı ada indirgenerek kayıt adıyla
  karşılaştırılır. Önce pencereye bakılır; pencerede özne yoksa cümlede önceki özneye.
- (3) Ayraç ve `: ` içeriği `annotation` / `claim` / `unclear` olarak sınıflanır.
  Yalnız `annotation` değerin iddiasına girer; `unclear` belirsizlik olarak raporlanır
  (`sentence_shared`, `stored_reference_attributed=false`).

Temiz kabul edilenler: açık iddia, kayıt ilacı ya da genel özne, koşul/istatistik ayracı.
İncelemeye bırakılanlar: olumsuz/şüpheli yöneten ya da ara ifade, soru, kayıt dışı özne.

Sürüm: ayrıştırıcı `m02-text-parser/3` → `/4` (davranış değişti). API yapısı, alanlar,
kapsam değerleri ve gerekçe kodları değişmediği için sözleşme `m02-timing-compare/2` kaldı
(tüketici notu API.md "Ayrıştırıcı 4"). Şema, bağımlılık, CI, frontend, `main.py`, ortak
fixture ve D5/D6 kodu değişmedi; önceden kaydedilmiş 94 durum değişmeden geçiyor.

Değişen eski beklentiler: yalnız sürüm dizesi (`parser/3` → `/4`, iki entegrasyon testinde).

Kanıt (2026-11-25, yerel; ayrı sentetik PG `127.0.0.1:55440`, `medicallm_m02_synth`):

| Kontrol | Sonuç |
|---|---|
| Yeniden üretim (26 sentetik metin, HTTP) `844f3bb` → son kod | Önce 8/8 hatalı, sonra 8/8 düzeltilmiş; olumlu eşler aynı |
| R2 örnekleri (20) ve D1–D6 örnekleri (13), HTTP | R2 sonucuyla birebir aynı (yalnız ayrıştırıcı sürümü farklı) |
| Çürütme yoklamaları (75) ve sıradan cümleler (33) | 75/75 beklenen; 33 cümlenin 31'i temiz, 2'si bilinçli işaretli (`no hepatic impairment` → `negated_condition`; `range, 3 to 5` → çelişki; ikisi de önceki kural) |
| Yeni testler | `test_m02_audit_r3.py` (D1/D3/D4 olumlu / olumsuz / yakın / birleşik + çürütme yolları), `test_m02_audit_r3_http_pg.py` (HTTP → sentetik PG: sekiz örnek, olumlu eşler, A1/A2 ayrımı, birleşik örnekler) |
| Birim | **651 geçti** |
| Katı tam paket (`MEDICALLM_STRICT_TESTS=1`) | **867 geçti, 0 atlandı** (86 sn). Bir ara koşu 67. testte durdu; artakalan süreç, PG oturumu ya da kilit yoktu, aynı dosya tek başına ve tam paket yeniden koşunca geçti (nedeni açıklanamadı, tekrarlanmadı) |
| GitHub CI | Son commit için PR sayfasında |

Bilinen sınırlar:
- Kural listesi dışındaki yöneten fiiller, yanlışlama sözcükleri ve çizgi (`—`) ile
  ayrılan ara ifadeler kaçabilir.
- Genel ilaç adı tanıma yoktur: eşanlamlı/marka adı incelemeye düşer.
- `Patients who did not eat had a Tmax …` önceki gibi `negated_value` verir.
- `Pharmacokinetics:` başlığı incelemeye düşer.

Uzman kabulü yok; gerçek veri bu turda açılmadı. Geri alma: bu R3 commit'inin revert'i
(veri/şema değişikliği yok).

Kadir/Halil için: C1, ajan, frontend ve ortak dosyalar değişmedi; ortak dosya talebi yok.
M-02 tüketicisi `sentence_shared` / `sentence_other_clause` belirteçlerini "değerin
kaynağı" diye göstermemeli.

#### M02-O1-R4 — Kalan iki bulgu (Astra, denetlenen `d18b591`; teslim, yeniden denetim bekliyor)

Önceki tur (R3, `d18b591`) için CI: çalıştırma 45675916399 başarılı. Katı backend 867 testi
geçti, atlanan yok; frontend 53 test ve derleme başarılı. Gerçek checkout
`b4539bf489ba8eecdf3f11f88b16b08998609e80`, dosya ağacı `e8bb2f41…` (denetçinin doğrulaması).
Denetçinin kararı: D1, D2, D5 ve D6 kapalı. Açık kalanlar D3 (temizleme özneyi siliyor) ve
D4 (uzun çizgide atıf).

Üç bulgu önce `d18b591`'de yeniden üretildi, sonra düzeltildi. Yol gerçek router →
JWT/yetki → servis → JSON; yalnız repository okuma sınırı sentetik. Her istekte iki kayıt
gönderildi: `[SYNTHETIC] Drug A` ve zaman alanları boş `[SYNTHETIC] Drug B`. Saklı
referanslar A1/A2.

| Örnek | `d18b591` (HTTP) | Şimdi (HTTP) |
|---|---|---|
| D3 `The half-life of magnesium sulfate is 10 hours.` | Drug A altında temiz 10 sa, `computed` 50 sa | ölçüm yok, `subject_unresolved`, metin korunuyor |
| D3 `For drug b in overdose, the half-life is 10 hours.` | temiz 10 sa, 50 sa | ölçüm yok, `subject_unresolved` |
| D4 `The half-life is 4 hours — adverse events are described elsewhere [A2].` | `inline=[A2]`, `references=[A2]`, `value_window`, `true` | `inline=[]`, `references=[]`, `nearby=[A2]`, `none`, `false` |

Yakın örnekler de `d18b591`'de hatalıydı, şimdi düzeltildi:
- `For drug b in patients with renal impairment,`, `For drug b hydrochloride in
  overdose,`, `In overdose of drug b,` ve `The half-life of sodium chloride …` → Drug A
  altında temiz 10 sa idi;
- `–`, `--` ve ` - ` çizgileri ile `— … —` arasındaki iddia → A2 kesin bağlanıyordu.

Olumlu kontroller önce de sonra da temiz ve aynı:
- `For drug a in overdose`, `For drug a hydrochloride`, `The drug's half-life` → 20 sa;
- sentetik kayıt adı `magnesium sulfate` iken `The half-life of magnesium sulfate …` →
  temiz;
- `4 hours.[A1]`, `4 hours [A1] (… [A2])` ve `4 hours (in adults) [A1]` → yalnız A1;
- `4-6 hours [A1]` ve `extended-release` → A1 korunuyor.

Kök neden ve karar (en küçük değişiklik, yalnız `parser.py`):
- (1) D3 temizleme: tuz atılınca boşalan aday "kayıt" sayılıyordu. Aday artık tuzlu ve
  tuzsuz kalıntıyla değerlendiriliyor. Boşalma kayıt eşleşmesi sayılmıyor; yalnız ad
  sözcüğü içermeyen aday `ignore` oluyor. Tuz adlı madde yalnız kayıt adına eşitse kayıt
  sayılıyor.
- (2) D3 çerçeve: tek bir ortam sözcüğü (`overdose`) bütün `For …,` öbeğini atlatıyordu.
  Artık yalnız ilk edattan önceki baş öbek ve durum sözcüğünün `of` tümleci aday oluyor.
- (3) Aynı incelemede bulunan kök neden: `half-life of X` adayı sözcük ortasında
  kesiliyordu (`sulf|ate` → `at`). Bitiren sözcük artık bütün sözcük, en çok 6 sözcük.
- (4) D4: çizgiler 8d'deki iki nokta kuralına katıldı. İlk `annotation` olmayan parça
  iddiayı bitiriyor; değerden önceki çizgi de önceki iddiayı bitiriyor. Sözcük içi tire ve
  sayısal aralık hariç.

Ayrıntı RULES.md 8e'de.

Sürüm: ayrıştırıcı `m02-text-parser/4` → `/5` (davranış değişti). API sözleşmesi
`m02-timing-compare/2` aynı kaldı (tüketici notu API.md "Ayrıştırıcı 5"). Veri, şema,
bağımlılık, CI, frontend, `main.py` ve ortak fixture değişmedi. Önceden kaydedilmiş 94 durum
değişmeden geçiyor.

Değişen eski beklentiler: yalnız sürüm dizesi. İki entegrasyon testi `/4` → `/5`;
`test_m02_audit_r3.py`'deki sürüm kontrolü tam `/4` yerine "en az 4" oldu, tam değeri
`test_m02_audit_r4.py` denetliyor.

Kanıt (2026-11-25, yerel; ayrı sentetik PG `127.0.0.1:55440`, `medicallm_m02_synth`):

| Kontrol | Sonuç |
|---|---|
| Yeniden üretim (27 sentetik metin, HTTP) `d18b591` → son kod | Önce 3/3 bulgu ve 7 yakın örnek hatalı; sonra 27/27 beklenen |
| R3 (26), R2 (20) ve D1–D6 (13) örnekleri, HTTP | Önceki çıktılarla birebir aynı (yalnız ayrıştırıcı sürümü farklı) |
| R4 yakın tarama (323 sentetik metin) | 323/323 beklenen. Yabancı öznelere 8 koşul eklenip çıkarıldı, kayıt adı ve tuzlu kayıt adı denendi, 6 çizgi türü × 4 iddia; A1 korunuyor; aralık ve tire değişmiyor |
| R3 çürütme yoklamaları (75) ve sıradan cümleler (33) | Değişmedi (75/75; 31/33, 2'si önceki kural gereği işaretli) |
| Yeni testler | `test_m02_audit_r4.py` (D3/D4 olumlu / olumsuz / yakın / birleşik, koşul ekle-çıkar, çizgi türleri), `test_m02_audit_r4_http_pg.py` (HTTP → sentetik PG, iki kayıtlı istek; inline/nearby/references/scope/attributed birlikte) |
| Birim | **712 geçti** |
| Katı tam paket (`MEDICALLM_STRICT_TESTS=1`) | **930 geçti, 0 atlandı** (55 sn); takılma tekrarlanmadı |
| GitHub CI | Son commit için PR sayfasında |

Koşulamayanlar: gerçek PostgreSQL/DrugBank akışı (kurala göre açılmadı). İkinci bağımsız ajan
taraması kullanım sınırı nedeniyle yapılamadı; yerine yürütülen 323 metinlik yakın tarama
kullanıldı. Uzman kabulü yok.

Bilinen sınırlar:
- Genel ilaç/marka adı tanıma yoktur.
- Tuz listesi sınırlıdır.
- Çerçevede `of` tümleci yalnız durum sözcüklerinden sonra okunur.
- D1 ara ifade kuralı çizgili ara ifadeye uygulanmaz.

Geri alma: bu R4 commit'inin revert'i (veri/şema değişikliği yok). Kadir/Halil için ortak
dosya talebi yok.

#### M02-O1-R5 — Özne ve kaynak sınırları (Astra, denetlenen `91789f3`; teslim, yeniden denetim bekliyor)

Önceki tur (R4, `91789f3`) için CI: çalıştırma 45681604304 başarılı. Katı backend 930 testi
geçti, atlanan yok; frontend 53 test ve derleme başarılı. Checkout
`9958b83239c3c3c47418633b2287aec57a75d18c`, dosya ağacı `1ce5c9e9…` (denetçinin log
doğrulaması). Denetçinin kararı: D1, D2, D5 ve D6 kapalı; D3 ve D4 açık. SDP formu
(`SDP_Project_Forms_Enhanced_Medikallm.docx.pdf`, 6 Kasım tarihli dosya) R4'teki ile
aynı; M-02 kısmı her değerin kaynağını ve özgün metnini istiyor, kapsam değişmedi.

Altı bulgu önce `91789f3`'ün ayrı kopyasında (`git archive`, çalışma dalı geri
alınmadan) yeniden üretildi, sonra düzeltildi. Yol gerçek router → JWT/yetki → servis →
JSON; yalnız repository okuma sınırı sentetik. Her istekte ikinci kayıt olarak zaman
alanları boş `[SYNTHETIC] Drug B` gönderildi.

| Örnek (kayıt adı) | `91789f3` (HTTP) | Şimdi (HTTP) |
|---|---|---|
| D3-A `For drug b monotherapy, …` (Drug A) | temiz 10 sa, `computed` 50 sa | ölçüm yok, `subject_unresolved`, metin korunuyor |
| D3-A `In overdose of drug b in adults, …` (Drug A) | temiz 10 sa, 50 sa | ölçüm yok, `subject_unresolved` |
| D3-B `The half-life of magnesium is 10 hours.` (magnesium sulfate) | temiz 10 sa, 50 sa | ölçüm yok, `subject_unresolved` |
| D3-B `The half-life of magnesium sulfate is 10 hours.` (magnesium) | temiz 10 sa, 50 sa | ölçüm yok, `subject_unresolved` |
| D4 `4 hours - 10 patients developed rash [A2]` | `inline=[A2]`, `references=[A2]`, `value_window`, `true` | `inline=[]`, `references=[]`, `nearby=[A2]`, `none`, `false` |
| D4 aynı cümle, `–` (U+2013) ile | aynı hata | aynı düzeltme |

Olumlu kontroller önce de sonra da temiz:
- `For drug a monotherapy`, `In overdose of drug a in adults`, `For drug a in overdose`,
  `The drug's half-life` ve `For oral administration` → 20 sa;
- `magnesium sulfate` ↔ `magnesium sulfate` ve `drug a hydrochloride` ↔ Drug A → temiz;
- kayıt adı `sodium chloride` iken `magnesium sulfate` metni → `subject_unresolved` (önce
  de öyleydi);
- `4-6 hours`, `4 – 6 hours` ve `4 hours - 6 hours` aralık olarak kalıyor, A1 bağlı;
- `[A1] — in adults — … [A2]`, `— in adults [A1] — … [A2]`, `(in adults) [A1]` ve
  `.[A1]` → yalnız A1, A2 `nearby`'da.

Önceden yazılan beklentilerden biri ek bir aşırı reddi gösterdi ve düzeltildi: `The
elimination half-life of the extended-release form is 4 hours [A1].` önceden
`subject_unresolved` veriyordu (`form` ad sayılıyordu).

Kök neden ve karar (yalnız `parser.py`): çözülemeyen aday altı yolda sessizce "özne yok"
ya da "kayıt eşleşti" oluyordu:
- çerçevede tek ortam sözcüğü;
- adayın içinde herhangi bir grup adı;
- adaydaki rakam;
- küçük harfli yolda kısmi örtüşme;
- büyük harfli yolda baştan örtüşme;
- rakamla başlayan her çizgi sonrası parça.

Sözcük listesi büyütmek yerine karar kuralı tek yerde düzeltildi (RULES.md 8f):
- aday ilk edat koşulundan ya da ilgi cümleciğinden önceki baş öbektir;
- `ignore` yalnız miktar, metabolit kodu ve son sözcüğü topluluk adı olan öbek içindir,
  ya da hiç ad sözcüğü kalmadığında;
- kayıt eşleşmesi yalnız normalize edilmiş adların eşitliğidir; tuz ana adı aynıysa
  eşittir, ad tuzdan oluşuyorsa tuzlarıyla tam eşitlik gerekir;
- diğer her aday çözülememiştir → inceleme, 5× yok;
- çizgi sonrasında süre (sayı + zaman birimi) geliyorsa aralıktır; başka sayılı ifade
  ayrı iddiadır.

Sürüm: ayrıştırıcı `m02-text-parser/5` → `/6` (davranış değişti). API sözleşmesi
`m02-timing-compare/2` aynı kaldı (tüketici notu API.md "Ayrıştırıcı 6"). Veri, şema,
bağımlılık, CI, frontend, `main.py`, ortak fixture, service, calc ve models değişmedi.
Önceden kaydedilmiş 94 durum değişmeden geçiyor.

Değişen eski beklentiler:
- Sürüm dizesi: iki entegrasyon testi `/5` → `/6`; `test_m02_audit_r4.py`'deki sürüm
  kontrolü tam `/5` yerine "en az 5" oldu, tam değeri `test_m02_audit_r5.py` denetliyor.
- RULES.md 8d/8e'deki kısmi eşleşme, baş öbek atlama ve "rakam gelmiyorsa" cümleleri
  `[R5: 8f ile değişti]` diye işaretlendi (geçmiş korunuyor).
- Davranış testleri gevşetilmedi.

Kanıt (2026-11-25, yerel; ayrı sentetik PG `127.0.0.1:55440`, `medicallm_m02_synth`):

| Kontrol | Sonuç |
|---|---|
| Yeniden üretim (22 sentetik metin, HTTP), `91789f3` kopyası → son kod | Önce 6/6 bulgu ve 1 aşırı ret hatalı; sonra 22/22 beklenen |
| R4 (27), R3 (26), R2 (20), D1–D6 (13) örnekleri, HTTP | Önceki çıktılarla birebir aynı (yalnız ayrıştırıcı sürümü farklı) |
| Çapraz matris (347 sentetik metin, beklenti çalıştırmadan önce yazıldı) | `91789f3`'te 72 hatalı (35 yabancı özne, 18 kısmi ad, 16 çizgi sonrası iddia, 2 `--` aralık); şimdi 345/347. Kalan 2: `4 hours -- 6 hours` değer ayrıştırmada aralık sayılmıyor (önceki davranış, aşağıda sınırlarda) |
| Önceki taramalar (R3 75 yoklama, R4 323 yakın örnek, 33 sıradan cümle) | Değişmedi |
| Yeni testler | `test_m02_audit_r5.py` (özne × 9 koşul × 3 kalıp, kayıt/yabancı; tam/kısmi ad × 3 koşul; 5 çizgi × 4 sayılı iddia; aralıklar; A1/A2; birleşik), `test_m02_audit_r5_http_pg.py` (altı örnek ve olumlu eşleri, HTTP → sentetik PG) |
| Birim | **850 geçti** |
| Katı tam paket (`MEDICALLM_STRICT_TESTS=1`) | **1071 geçti, 0 atlandı** (56 sn) |
| GitHub CI | Son commit için PR sayfasında |

Koşulamayanlar: gerçek PostgreSQL/DrugBank akışı (kurala göre açılmadı). Bağımsız ajan
taraması kullanım sınırı nedeniyle yapılamadı; yerine 347 metinlik çapraz matris
kullanıldı.

Bilinen sınırlar:
- Genel ilaç/marka adı ve kimyasal eşdeğerlik tanıma yoktur: eş ad ya da farklı yazım
  incelemeye düşer.
- `4 hours -- 6 hours` iki çelişen değer olarak incelemeye düşer.
- Kesen edat ve ortam sözcüğü listeleri sınırlıdır; listede olmayan ortam sözcüğü
  incelemeye düşürür.

Teknik testler uzman kabulü değildir. Klinik değerlendirme, gerçek veri kapsamı, ekran ve
kaynaklı zaman aralığı tamamlanmış sayılmaz. Teknik yeniden denetimi Astra yapacak.
Geri alma: bu R5 commit'inin revert'i. Kadir/Halil için ortak dosya talebi yok.

---

# Tarihsel raporlar (değiştirilmedi)

## Aşama 0 — Sohbet ve etkileşim akışının güvenilirliği (2026-11-17/18)

> Bu aşama M-06'nın çalışan sohbet temelini ve M-01/M-05'in güvenilir sorgu
> temelini destekler. **Hiçbir MVP'nin (M-01…M-06) klinik kabulü tamamlanmadı.**
> Uzman ve önceden kararlaştırılmış test setleri ayrıca gereklidir. Test
> başarıları klinik doğruluk yüzdesi değildir.

### 1. Ne yapıldı; önceki ve yeni kullanıcı davranışı

| Durum | Önce | Şimdi |
|---|---|---|
| SSE: yalnız `error` olayı | Hata `handleChunk` içinde fırlatılıp JSON-ayrıştırma `catch`'inde yutuluyordu → **"No response received"** başarılı yanıt gibi | "Yanıt tamamlanamadı" kartı: yerelleştirilmiş neden (kod), referans kimliği, uygunsa **Yeniden dene** |
| SSE: kısmi metin + hata | Kısmi metin **başarılı yanıt** olarak kalıyordu | Hata kartı; kısmi metin katlanmış ve "tamamlanmamış — yanıt değildir" etiketli; kaydedilmez |
| SSE: boş `done` / `done` olmadan kapanma | "No response received" / kısmi metin başarılı | `empty_response` / `stream_interrupted` hatası; kaydedilmez |
| Sessiz bağlantı / sağlayıcı takılması | LLM istemcisinde zaman aşımı yok (OpenAI varsayılanı 10 dk) | İstek zaman aşımı 60 sn, 15 sn'de bir kalp atışı, ön yüzde 60 sn sessizlik sınırı, toplam 180 sn → `stream_timeout` |
| Backend hata metni | `str(e)` doğrudan ekrana (sağlayıcı yükü, kuruluş kimliği vb.) | Güvenli kod + mesaj + `request_id`; ayrıntı yalnız sunucu logunda |
| Araç öncesi "kontrol ediyorum" metni, son çağrı boş | Tamamlanmış yanıt olarak kaydediliyordu | Yalnız **son model çağrısının** metni yanıttır; boşsa `empty_response` |
| İlaç–ilaç / ilaç–gıda servisi | Sorgu hatası, bilinmeyen ilaç ve gerçek "kayıt yok" aynı: `[]`, `count=0`, `overall_severity=null` | `status`: `found` / `no_record` / `incomplete` / `unresolved` / `error`; çözümlenemeyen girdiler listelenir, kontrol edilen/toplam ikili sayısı |
| Ajan araçları | Hata veya bilinmeyen ilaçta "No documented interactions found…"; çözülemeyen adlar sessizce atılıyordu | Her çıktı `STATUS: …` satırı + ne yapılacağı ile başlar; eşleşme şekli (tam / yaklaşık / kombinasyon ürünü / aynı ilaç) açıklanır |
| Önem derecesi | Metin kalıbı sezgisi klinik etiket gibi: "This combination is **not** contraindicated." → 1.0 "Contraindicated"; boş metin → 0.5 "Moderate" | `severity=null`, `severity_status="not_rated"`; ekranlarda "derecelendirilmedi (kaynakta etiket yok)"; şiddet ölçeği/renkleri kaldırıldı |
| İlaç Matrisi | Başarısız istekte eski sonuç kalıyor, kayıt yoksa yeşil ✓, yeni seçime eski sonuç | Hücre durumları: kayıt var / kayıt yok (nötr, "güvenli anlamına gelmez") / kontrol yok / başarısız / yükleniyor; sonuç seçim anahtarına bağlı, eski istek iptal; hata bandı + yeniden dene |
| Hasta ekranları (doktor/hasta) | Hata → "etkileşim bulunamadı ✅"; "Önerilen/Güvenli Alternatifler" | Hata, eksik ilaç, yaklaşık eşleşme ve 10 ilaç sınırı açıkça; "doğrulanmamış adaylar" |
| Alternatifler | "safe alternatives"; sezgisel skor ≤0.5 olan **belgelenmiş etkileşimli** adaylar "önemli etkileşim yok" diye listeleniyordu | "Doğrulanmamış aday": herhangi bir etkileşim kaydı olan aday hariç, mevcut ilaç hariç, sınırlamalar yazılı; hasta analizinde **otomatik öneri yok** (gerekçe aşağıda) |
| Sistem yönergesi | "LAST RESORT: genel bilgiden yanıt", "✅ SAFE", "MAJOR/MODERATE/MINOR belirt", "uygun alternatif açıkla" | Boşluk doldurma yasak; STATUS kuralları; önem atama yasak; alternatifler yalnız istenirse ve doğrulanmamış; dozaj/kontrendikasyon/alerji "kontrol edilmedi" |
| Kaynaklar | Yalnız `done`'da; DrugBank kartında tıklanabilir bağlantı yok | Akış sırasında `sources` olayı; "Kaynak kaydını aç" (yalnız `https://`); atıf denetimi: kaynaksız numara, hiç atıf yok, satır içi kaynağı olmayan satır sayısı uyarıları |
| `/health` | `agent: ok` LLM'i doğrulamadan "hazır" izlenimi | Aynı `status`/`checks` + `llm.api_key_configured`, son **gerçek** LLM çağrısının sonucu ve `verifies` açıklaması (LLM çağrısı yapmaz) |
| Hasta bağlamı (güvenlik) | Yetki kontrolü başarısız olsa da istenen `patient_id` araç bağlamına konuyordu | Yalnız yetkili hasta bağlama alınır (mevcut erişim politikasının tutarlı uygulanması; politika genişletilmedi) |

### 2. Dosyalar, sürümler ve doğrulanabilir değişiklik

**Başlangıç (git yok; hash manifesti ile sabitlendi, 2026-11-17):**
- GitHub `main` başı `f7e1437d8cc044579c1bab1145e4621b66071503` (değişmemiş).
  Yerel kopya ile ortak 165 dosyanın 6'sı farklı; ek yerel dosyalar
  `backend/scripts/seed_tr_brands.py`, `compose.local.yml`, `start-local.cmd` (+ `.env`).
- Ek bulgu: yerel kopya GitHub'daki `local-run-support` dalına (`f695c74…`) daha
  yakın — yalnız `backend/pyproject.toml`, `backend/run.py`, `backend/uv.lock`
  (truststore / SSLKEYLOGFILE yerel düzeltmeleri) ve `start-local.cmd` farklı.
- `frontend/src/pages/Chat.jsx` başlangıç SHA-256 =
  `6612e9fd57d0322a437a622f146eb9863ae948e5584278beec437d42bafdb9ea` (denetlenen ile aynı).
- Yerel düzeltmeler korundu: `pyproject.toml`, `run.py`, `seed.py`,
  `sql_client.py`, `uv.lock` dokunulmadı; `config.py` yalnız ekleme aldı.
  `.env` değiştirilmedi (gizli; hash'lenmedi).

**Değişiklik paketi:** `STAGE0.patch` (proje kökünde). Başlangıç ağacına
`git -c core.autocrlf=false apply -p1 STAGE0.patch` ile uygulandığında teslim
ağacını **bayt düzeyinde** yeniden üretir (doğrulandı). 23 değişen + 15 yeni dosya.

| Dosya | Başlangıç SHA-256 (16) | Teslim SHA-256 (16) | Neden |
|---|---|---|---|
| backend/src/drugs/models.py | 6ff8608fe7896281 | ca53570fa3c0ac23 | Durum sözlüğü, ek alanlar (geriye uyumlu) |
| backend/src/drugs/service.py | 0cd9f91af52ca230 | 0a99aa37bf02b4cf | Açık durumlar, eşleşme türü, aday/duplikasyon/hasta analizi |
| backend/src/agent/tools.py | e1bdcc83f21eeb0d | a885e77d549dc165 | STATUS çıktıları, eşleşme şeffaflığı, şiddet/“safe” ifadeleri |
| backend/src/agent/langchain_agent.py | 8539ea46fc95b1e9 | bf4ee2dd803c7edb | Yönerge; LLM zaman aşımı/yeniden deneme |
| backend/src/session/session.py | 3ca967e6ce35914e | 5e78a2dfcda26c05 | Tek terminal olay, güvenli hata, kaydetme kuralları |
| backend/src/session/router.py | 981b21414c41215f | 2b7e797c6f2ef53c | Kalp atışı/zaman aşımı, hasta bağlamı, güvenli HTTP hataları |
| backend/src/main.py | 5a1e891c68e3cabc | 5fea883af9a6c31b | `/health` açıklaması |
| backend/src/config.py | 6c3be72a69ccf622 | 56492b2addc3c471 | 4 yeni ayar (varsayılanlı) |
| backend/tests/integration/conftest.py | 898f4032668b887d | e2c631f5be16d448 | Sahte ajanı belgelendiği gibi kur |
| frontend/src/pages/Chat.jsx | 6612e9fd57d0322a | 7c83b83307c4e8a5 | Yeni akış okuyucu, hata kartı, yeniden dene, kaynaklar |
| frontend/src/pages/DrugMatrix.jsx | 19d0c95529e6bc3d | 4d0dd2b5c4494d39 | Hücre durumları, anahtar/iptal, eşleşmeyen ilaçlar |
| frontend/src/pages/DrugSearch.jsx | 8c04c6fea7c90863 | 98e54bff5eb57f72 | Durum, şiddet ölçeği kaldırıldı, nötr "kayıt yok" |
| frontend/src/pages/doctor/PatientDetail.jsx | 498950e1ebe39786 | 955e2973c3c489b9 | Hata/eksik/yaklaşık eşleşme |
| frontend/src/pages/patient/PatientMedications.jsx | 01c8e4f511c51a31 | b1a5a75c7e827423 | Hata ≠ "etkileşim yok"; alternatif başlığı |
| frontend/src/i18n/strings/{chat,doctor,drugMatrix,patient}.js | 4880524f… / fcf4df78… / 5db2ba67… / 72b8670e… | cdc39c35… / 8d5b514a… / 90a23908… / 814a19f3… | Metinler (EN=TR anahtar eşitliği testli) |
| frontend/src/App.css, DrugMatrix.css | f11bd65d… / aac8dcbf… | 63bef57e… / 125601d9… | Hata kartı/uyarı stilleri |

Yeni: `backend/src/session/stream_errors.py`, `backend/src/agent/citations.py`,
`backend/src/agent/llm_status.py`, `backend/scripts/check_live_stack.py`,
`frontend/src/api/chatStream.js`, `frontend/src/components/FailedTurnCard.jsx`,
`frontend/src/pages/drugMatrixModel.js` ve testler (aşağıda). Tam liste ve
hash'ler `STAGE0.patch` içindedir.

### 3. Önemli kararlar ve gerekçeler
- **Durum sözlüğü veri katmanında**, pydantic `Literal`; varsayılan `"error"`: durumsuz kurulan bir yanıt asla "etkileşim yok" okunamaz. Eski alanlar korundu (çağıranlar kırılmadı).
- **Önem hiç sunulmuyor**: `drug_interactions` tablosunda önem sütunu yok, uzman değerlendirmesi yok. `calculate_severity.py` silinmedi (gelecekte uzman etiketleriyle karşılaştırma için) ama kullanılmıyor. Yeni sınıflandırıcı yazılmadı.
- **Alternatifler**: aday üretimi aynı (aynı DrugBank kategorisi). Herhangi bir etkileşim kaydı olan aday hariç; mevcut ilaç hariç. Hasta analizinde otomatik aday üretimi kapatıldı: doğrulanmış önem olmadan hangi çatışmanın ikame gerektirdiği belirlenemez. **M-05 "her major çatışmaya ≥1 alternatif" hedefi açık eksik**; önem etiketleri için uzman/kaynak kararı gerekiyor.
- **SSE**: ajan ayrı görevde çalışır, olaylar kuyrukla aktarılır → kalp atışı ve toplam zaman aşımı mümkün; context var'lar görev kopyasıyla araçlara ulaşır. Her akış tek terminal olayla biter; asistan mesajı yalnız `done` ile kaydedilir.
- **Ön yüz mantığı saf modüllerde** (`chatStream.js`, `drugMatrixModel.js`) → React'siz test edilebilir.
- **Ad çözümleme şeffaflığı**: arama sonucu `match_type` taşır; kombinasyon ürünü adı tek bileşene eşlendiğinde sonuç `incomplete`; aynı ilacın iki adı "aynı ilaç / mükerrer tedavi".
- **Token bütçesi**: `get_drug_info` alanları işaretli kırpılır (kaynak bağlantısı tam metni verir); yönerge eklemeleri sıkıştırıldı.
- Migration, yeni servis, yeni bağımlılık, toplu veri yükleme **yok**.

### 4. Veritabanı, veri kaynağı, bağımlılık, yapılandırma
- Şema/migration değişikliği yok. Uygulama veritabanına **yazma/silme yapılmadı**; ölçümler `default_transaction_read_only=on` oturumuyla.
- Yeni isteğe bağlı ayarlar (varsayılanlı; `.env` değişmedi): `LLM_REQUEST_TIMEOUT_SECONDS=60`, `LLM_MAX_RETRIES=2`, `CHAT_STREAM_TIMEOUT_SECONDS=180`, `CHAT_STREAM_HEARTBEAT_SECONDS=15`.
- API (ekleme): etkileşim yanıtında `status`, `checked_drugs`, `unresolved_drug_ids`, `pairs_checked/total`, `error`; kayıtta `severity_status`, `source`, `source_url`; arama sonucunda `match_type`; hasta analizinde `status`, `unresolved_medications`, `medication_matches`, `not_checked_over_limit`, `alternatives_note`; aşırı doz kontrolünde `status`; SSE'de `sources`, `error{code,message,retryable,request_id}`, `done{citation_check,persisted,request_id}`.
- Etkin yapılandırma (sırsız): kök `.env` yüklü; LLM ana makinesi `api.groq.com`, model `openai/gpt-oss-20b`, anahtar **mevcut**; DB `localhost:5432/medicallm`, SSL kapalı.
- **Salt okunur ölçüm (2026-11-17, yerel DB)**: `drugs` 17.430; `drug_synonyms` 33.839; `drug_interactions` 2.855.848 (önem sütunu yok); `drug_food_interactions` 2.512 satır / 1.423 ilaç; `drug_enzymes` 5.931 / 1.835; `drug_transporters` 3.517 / 1.145; `drug_carriers` 966 / 689; `drug_embeddings` **0** (anlamsal arama fiilen pasif). Serbest metin dolulukları: metabolism 2.413, half_life 2.471, absorption 2.520, route_of_elimination 2.075, clearance 1.674, protein_binding 1.983, volume_of_distribution 1.797, toxicity 2.548. Açılış göçünün ön koşulları mevcut, `email_canonical` boş kullanıcı 0 (açılış veri değiştirmez; sohbet yine de yazar).

### 5. Kabul kriterleri — durum ve kanıt
1. **Sürümler belirlenebilir — karşılandı.** Başlangıç hash manifesti + GitHub karşılaştırması; `STAGE0.patch` başlangıca uygulanınca teslimi bayt düzeyinde üretir.
2. **Çalışan akış — karşılandı (sınırlamalarla).** *Gerçek LLM + gerçek DB (salt okunur, kayıt yazılmadan)* `scripts/check_live_stack.py`, son tur (inceleme düzeltmelerinden sonra, 2026-11-18): normal sohbet tamam (≈1 sn); tek ilaç `get_drug_info` → `STATUS: FOUND`, DrugBank kaynağı [1] (≈45 sn); iki ilaç `check_drug_interactions` → `FOUND`, etkileşim kaydı kaynağı + "önem derecelendirilmedi" (≈41 sn); atıf denetimi: kaynaksız numara yok. İlk turda tek ilaç sorusu Groq **413 (TPM 8000 / istek 8186)** ile düştü; alan kırpma + yönerge sıkıştırma sonrası iki turda da geçti. *Taklit testler* ayrı (madde 3–6). *Arayüz uçtan uca (sentetik DB, gerçek Groq)*: kaynaklı etkileşim yanıtı + "Kaynak kaydını aç"; sağlayıcı hatası enjeksiyonu → hata kartı + referans → backend düzeltilince **Yeniden dene** başarılı; kalıcı kayıt 4 mesaj (başarısız tur yok, mükerrer soru yok).
   *Sınırlama*: model, kaydın söylemediği öneriler ekliyor (kayıt yalnız aspirinin varfarinin antikoagülan etkisini artırabileceğini söylüyor; yanıtlar "kanama riski", "INR izlemi" ekledi — son turda model bunu "veritabanı kaydına değil standart uygulamaya dayanıyor, atıf yok" diye kendisi işaretledi). Yönerge yasaklıyor ama gpt-oss-20b tam uymuyor; bu "satır içi kaynağı olmayan N satır" uyarısıyla **görünür**, engellenmiyor. Tek ilaç yanıtında da 8 satır satır-içi atıfsız (endikasyon maddeleri tek [1] ile özetlenmiş).
3. **Sentetik durum ayrımı — karşılandı.** Birim (sahte DB sınırı) + gerçek PostgreSQL (sentetik veri): sorgu hatası `error`, bilinmeyen ilaç `unresolved`, kısmi liste `incomplete` (eksikler listeli), başarılı-boş `no_record`; REST, araç metni ve ekran testleri.
4. **SSE senaryoları — karşılandı.** Ön yüz 15 test (normal, yalnız hata, kısmi+hata, boş done, done'suz kapanma, parçalı/CRLF, bozuk olay, kalp atışı, sessizlik zaman aşımı, ağ hatası, eski biçim hata, akış sırasında kaynak, yeniden deneme). Backend: tek terminal olay, kalp atışı, toplam zaman aşımı, `done` sonrası ikinci terminal yok, ham hata sızmaz, boş/araç-öncesi metin kaydedilmez. Eski ayrıştırıcının birebir yeniden üretimi: yalnız hata → "No response received"; kısmi+hata → kısmi metin başarılı.
5. **Matris/ilgili ekranlar — karşılandı.** Model + bileşen testleri ve tarayıcıda: başarı (kayıt var / kayıt yok, 3/3 ikili) → DB durdurulunca yeni seçim "Başarısız" + bant, ✓ yok, eski sonuç taşınmadı → DB açılınca yeniden dene.
6. **Önem/alternatif/kaynak — kısmen.** Kod ve metinler doğrulanmamış önem/alternatif sunmuyor (testli); kaynaklar parçalı ve son yanıtta korunuyor. Modelin ek tavsiye uydurması uyarıyla görünür ama önlenmiyor (madde 2).
7. **Testler ve derleme — karşılandı.** Bkz. 6. bölüm.
8. **Veri ölçümü — karşılandı.** Bkz. 4. bölüm (salt okunur).

### 6. Çalıştırılan komutlar ve sonuçlar
- Başlangıç: backend tüm paket **49 geçti / 3 kaldı** (`/health` 503 ve gövde biçimi; `change-password` import hatası). Ön yüz 15 test.
- Teslim: backend birim `pytest tests/unit` → **95 geçti**; tüm paket (sentetik PG ile, `MEDICALLM_SYNTHETIC_PG_URL=…_synth`) → **121 geçti, 1 kaldı** (önceden var olan, kapsam dışı `change-password` import hatası). Ön yüz `npx vitest --run` → **47 geçti**; `vite build` başarılı (yalnız önceden var olan paket boyutu uyarısı).
- Gerçek kontrol: `uv run python scripts/check_live_stack.py --pause 65` (3 tur; sonuçlar madde 5.2).
- Bağımsız 4 açılı inceleme (backend sözleşmesi, SSE, ekranlar, iddia/gizlilik) → bulguların kapsam içindekiler düzeltildi; kalanlar 8. bölümde.
- Çalıştırılamayan/önerilen: klinik doğruluk (uzman + önceden belirlenmiş setler gerekir); gerçek kullanıcı oturumuyla uygulama DB'sinde sohbet (yazma gerektirdiği için yapılmadı); Docker/üretim nginx üzerinden SSE (yerelde Docker yok); 10+ eşzamanlı kullanıcı yük testi.

### 7. Nasıl çalıştırılır ve kontrol edilir
- Başlatma değişmedi: `start-local.cmd` (veya `backend`: `uv run python run.py`, `frontend`: `npm run dev`).
- Normal kontrol: sohbete "Warfarin ile aspirin arasında belgelenmiş bir etkileşim var mı?" → kaynak kartı, "Kaynak kaydını aç", "önem derecelendirilmedi"; İlaç Matrisi'ne 3 ilaç ekle → "Kayıt var / Kayıt yok" (✓ yok).
- Hata kontrolü: backend'i geçici olarak `LLM_BASE_URL=http://127.0.0.1:9/v1` ile başlat → soru → "Yanıt tamamlanamadı / sağlayıcıya ulaşılamadı" kartı; normal ayarla yeniden başlat → **Yeniden dene**. `/health` → `llm.last_call` başarısız turu gösterir.
- Gerçek LLM kontrolü (yazma yok, LLM kotası harcar): `cd backend && uv run python scripts/check_live_stack.py --pause 65 --out live_check.json`.
- Testler: `cd backend && uv run pytest tests/unit`; sentetik PG ile tüm paket: adı `_synth` ile biten **ayrı** bir veritabanı URL'si → `MEDICALLM_SYNTHETIC_PG_URL=… uv run pytest` (testler o veritabanını siler/yeniden kurar; ad koruması var). `cd frontend && npx vitest --run`.

### 8. Bilinen eksikler, riskler, geri alma
- **Groq ücretsiz/on-demand sınırı (en önemli risk):** gpt-oss-20b TPM 8.000 (RPM 30, TPD 200K — Groq belgeleri). Her LLM çağrısının sabit yükü ≈6.746 token (yönerge+10 araç şeması; değişiklik öncesi 6.379). Büyük araç çıktısı tek istekte 413'e, iki çağrılı turlar dakika penceresi nedeniyle 40–100 sn gecikmeye yol açıyor (geçmiş loglarda 413 ve 401 hataları da var). Seçenekler: daha yüksek Groq planı (ücretli — karar sizin), araç şemalarını/yönergeyi küçültme veya tur başına araç kümesini daraltma (mimari iş).
- LLM'in kayıtta olmayan tavsiye eklemesi sürüyor (uyarıyla görünür). Kalıcı çözüm: M-06'da araç bulgularının LLM'siz yapılandırılmış özeti veya doğrulayıcı.
- Atıf denetimi sezgiseldir (kaynağın iddiayı desteklediğini doğrulamaz).
- İstemci zaman aşımından sonra backend yanıtı kaydetmişse yeniden deneme soruyu çoğaltabilir (nadir; kalp atışı bunu büyük ölçüde önler).
- `drug_embeddings` boş → anlamsal arama pasif. `seed_tr_brands.py` ATC öneki yedeği ile bağlanan TR markaları "tam marka eşleşmesi" görünebilir.
- **Önceden var olan, bu aşamada düzeltilmeyen sorunlar:** `POST /api/auth/change-password` import hatası (test kalıyor); doktorun `analyze-patient` çağrısında `DoctorPatientAssociation.doctor_id/patient_id` alanları yok → 500 (ekran artık "kontrol yapılamadı" gösteriyor; yetki sorgusu düzeltmesi erişim politikası kararı); `PatientAnalysis.jsx` yanlış istek gövdesi; `Patients.jsx` var olmayan `/api/session/analyze-patient`'i çağırıyor; INFO loglarında kullanıcı e-postası; hasta adı/doğum tarihi/notları barındırılan LLM'e sistem yönergesinde gidiyor; terminoloji düzeltme kuralı model bilgisine dayanıyor.
- **İçerik kararı gerekenler:** açılış sayfası metinleri hâlâ "şiddet seviyeleri ve güvenli alternatif önerileri" vaat ediyor ve demo diyaloğu "daha güvenli" ilaç öneriyor (`frontend/src/pages/landingStrings.js`); dokunulmadı.
- **Geri alma:** `git -c core.autocrlf=false apply -R -p1 STAGE0.patch` (proje kökünde) ya da başlangıç zip/manifestindeki dosyaları geri kopyalama. Veri/migration geri alması gerekmez.

### 9. Sıradaki adım önerisi
1. Groq sınırı kararı (plan yükseltme mi, yönerge/araç daraltma mı) — güvenilirliğin ön koşulu.
2. Form 3.5'teki adlı hekim/eczacı ile önceden kararlaştırılmış test setleri (M-01 %90, M-03 %90, M-05 50 uyarıda %85, M-06 10 sorunun 8'i) ve önem etiketleme yöntemi kararı.
3. Doktor `analyze-patient` yetki sorgusu ve `change-password` hatası için ayrı, açık bir düzeltme.
4. M-01 ayrı ekranına geçmeden önce gıda/hastalık–gıda kaynak verisi (TürKomp, kılavuzlar) ve kaynak/orijinal metin/birim saklama şeması.

---

## Aşama 0.1 — Groq ücretsiz katman sınırına uyum (2026-11-18 … 11-23)

> Aşama 0 / 9. bölüm / 1. adım. Model (`openai/gpt-oss-20b`), sağlayıcı (Groq), anahtar ve
> Groq planı **değişmedi**. Hiçbir MVP'nin (M-01…M-06) klinik kabulü bu aşamada da tamamlanmadı.

### 1. Ne yapıldı; önceki ve yeni davranış

| Durum | Önce | Şimdi |
|---|---|---|
| Her LLM çağrısının sabit yükü (Groq'un sayımı) | 6.200 token (yönerge ≈3.900 + 10 araç şeması) | **2.393** (hekim rolü, hasta yok: yönerge 1.328 + 9 araç şeması 1.483, tiktoken) |
| Tek araçlı ilaç sorusu (dakika kotası doluyken değil) | 41–45 sn (2. çağrı dakika kotasında ~35 sn bekliyordu) | **1,2–3,8 sn** (canlı, 7 ilaç sorusu) |
| Tek istek 8.000 token'ı aşınca | 413 (loglarda 8.186 / 8.804 / 9.260) | İstek bütçesi denetimi (tahmini 7.000): önce eski geçmiş atılır (model bilgilendirilir), sonra bu turun en büyük araç çıktısı işaretli kısaltılır; yine sığmazsa sağlayıcıya gönderilmeden `llm_request_too_large`. Canlıda 413 yok |
| PubMed çıktısı (sahte makalelerle ölçüm) | 10 makale 6.468 token, açık erişimli tam metinle 35.688 → yanıt çağrısı hep 8.000'i aşıyordu (hesap) | 5 makale ≈1.800, 10 makale ≈2.600–2.800; tam metin, tam özet ve ayrıntılı ölçütler yalnız kaynak kartında (metin bunu söyler) |
| PubMed özet kırpma | — | Bölüm duyarlı: SONUÇ, sonra BULGULAR korunur; işaret, gösterilmeyen bölümleri adlandırır ve "gösterilmeyen bulguyu söyleme" der |
| Çoklu PubMed sorgusu | Yalnız güven puanına göre ilk N → zorunlu alt grup alt sorgusu düşebiliyordu | Alt sorgular sırayla harmanlanır; her makalede alt sorgu etiketi; sonuç vermeyen alt sorgu bildirilir |
| Etkileşim kayıt listeleri | Sınırsız (10 ilaçta 45 kayıt ≈4K token) | İlk 15 kayıt DrugBank metniyle, sonrakiler ad + atıf numarasıyla (metinsiz); sorulan ilacın kayıtları önce; hepsi atıf yapılabilir, arayüzde atıf yapılan kart görünür |
| Dakika kotası beklemesi | Sessiz bekleme | "Sağlayıcının dakikalık sınırı dolu; yanıt yaklaşık N sn içinde devam edecek" (yalnız istemci gerçekten bekleyecekse; canlıda art arda soruda 11 sn göründü) |
| Günlük kota (TPD/RPD) | "rate limited, retry" + 2 boşuna yeniden deneme | `llm_daily_quota`: yeniden denemeden; kartta yaklaşık yenilenme süresi, "Yeniden dene" düğmesi yok |
| Sohbet geçmişi | 20 tura kadar, boyut sınırsız | En yeni 1.000 token (güncel soru her zaman gider) |
| Hasta aracı şeması | Her çağrıda | Yalnız hasta bağlamı varken |
| Token kullanımı | Bilinmiyor | Her yanıtın sağlayıcı sayımı loglanır, `done.llm_usage` ve mesaj debug'ında |
| `/health` | Son çağrı sonucu | + `llm.provider_limits` (son limit başlıkları, son 429) ve `llm.token_estimator` |
| `get_drug_info` (`detail="high"`) — önceden var olan iki hata | İlişki koleksiyonlarına sınırlı alt küme atanıyordu → her okumada sınır ötesi satırlar için DELETE (oturum commit edilmediği için geri alınıyordu; salt okunur oturumda hata); altı koleksiyonun tek SELECT'te birleşmesi → bir sorgu ~160 sn | Okuma yolunda yazma yok; koleksiyonlar ayrı sorgularla → varfarin/parasetamol/ibuprofen 0,0–0,2 sn (salt okunur doğrulandı) |

### 2. Dosyalar ve sürümler

Başlangıç = Aşama 0 teslimi (2026-11-18 anlık görüntüsü, 188 dosyalık hash manifesti; `STATUS.md` 4e23d072…, `STAGE0.patch` 671d7601…).
Değişiklik paketi: **`STAGE0_1.patch`** (Aşama 0 teslimine `git -c core.autocrlf=false apply -p1 STAGE0_1.patch` ile uygulanır; bayt düzeyinde doğrulandı). 21 değişen + 7 yeni dosya; `.env` değişmedi.

| Dosya | Önce (16) | Sonra (16) | Neden |
|---|---|---|---|
| backend/src/agent/langchain_agent.py | bf4ee2dd803c7edb | 466d8450a44fa84e | Sıkıştırılmış yönerge; istemci kancası; bütçe ara katmanı |
| backend/src/agent/tools.py | a885e77d549dc165 | 54f7d44a4d0d9b82 | Araç açıklamaları; PubMed ve kayıt listesi sınırları |
| backend/src/drugs/service.py | 0a99aa37bf02b4cf | 1f7dd05f09d74211 | `get_drug(high)`: yazma yok, ayrı sorgular |
| backend/src/pubmed/models.py, service.py | 4b779652… / 99411166… | 9ebdf6da… / c1a524b2… | Makaleye alt sorgu etiketi (`source_query`) |
| backend/src/session/session.py, router.py | 5e78a2df… / 2b7e797c… | 8e4e6154… / fd7af2ef… | Geçmiş bütçesi, kullanım, `status` olayı |
| backend/src/session/stream_errors.py | 9c1f9fb838b4bbf6 | 9b8972db479d42c8 | `llm_daily_quota`, `retry_after_seconds` |
| backend/src/main.py, config.py | 5fea883a… / 56492b2a… | 2013d668… / cbc1ea2e… | `/health` ekleri; 2 ayar |
| backend/scripts/check_live_stack.py | 726132e0a12d7f23 | fd6e10fc320d9cee | 9 soru, çağrı başına kullanım, bekleme bildirimleri |
| frontend/src/api/chatStream.js, pages/Chat.jsx | 6e62c23a… / 7c83b833… | 86b9eb26… / 7d34d4f9… | `status` bildirimi, kaydırma |
| frontend/src/components/FailedTurnCard.jsx, i18n/strings/chat.js, App.css | 297b5d3d… / cdc39c35… / 63bef57e… | a0cd5e51… / ea844e05… / 1fee6038… | Günlük kota, bekleme süresi, metinler (EN=TR) |
| testler (değişen 5) | — | — | test_chat_stream_backend, test_stream_errors_and_citations (CI'da `openai` yoksa atlanır), test_tool_status_outputs, chatStream.test, FailedTurnCard.test |

Yeni: `backend/src/agent/provider_limits.py` (c13d1b03…), `request_guard.py` (af0f0b2d…), `token_budget.py` (e5d6acee…); testler `test_provider_limits_and_budget.py`, `test_pubmed_output_budget.py`, `test_prompt_contract.py`, `test_review_followups.py`.

### 3. Önemli kararlar ve gerekçeler
- **Önce ölçüldü (2026-11-18, yeniden deneme kapalı sondalar):** Groq aynı ilk isteği 6.200 token saydı; dakika kotası 8.000'lik, sürekli dolan bir kova (≈133 token/sn); hemen tekrarlanan istek 429 "≈34 sn sonra" aldı. Belgelerdeki "önbellekteki token limite sayılmaz" bu hesapta görülmedi (`cached_tokens` yok, dakikalar sonra aynı istek de tam sayıldı) → önbelleğe güvenilmedi.
- **Yönerge sıkıştırma:** üç bağımsız taslak (kuralları koruyan sade / araç merkezli / öncelik sıralı), üç yargıç (kapsam, davranış riski, bütçe), sentez. Kapsam yargıcının envanterindeki **168 kuralın her biri** yeni metinde bir yere yerleştirildi: genel ilkeler, STATUS, önem, alternatif, atıf, biçim → yönerge; "hangi araç ne zaman" kuralları → araç açıklamaları; PubMed sentez kuralları (alt tür/popülasyon ayrımı, düşük ilgi, çelişkili bulgu, yakın kopya, sınırlılıklar) → PubMed çıktısının başı ("HOW TO USE"). STATUS ve önem yönergeleri zaten araç çıktılarında. **Bilerek kaldırılan:** "the DrugBank record mentions monitoring INR" örneği (Aşama 0'daki desteklenmeyen INR önerisini tetiklemiş olabilir). **Eklenen:** ilaç adı verilmeden hasta analizi (`additional_drugs=[]`); "her [N], o iddiayı söyleyen kaynak olmalı" (eski PubMed altbilgisindeki kuralın geri kazanımı). Güvenlik kuralları testlerde tam cümle olarak sabit.
- **Bütçe:** çağrı başına tahmini 7.000 (Groq tek istek sınırı 8.000; tiktoken tahmini Groq'tan biraz yüksek); geçmiş 1.000; 15 metinli kayıt; PubMed varsayılan 5, en fazla 10 (6–10 makalede özet 550 karakter).
- **429:** OpenAI istemcisi `retry-after` ≤60 sn'yi zaten bekliyor; kanca yalnız istemcinin gerçekten bekleyeceği süreyi duyurur (son denemede duyurmaz; süre yalnız gövdede yazıyorsa başlığa taşır). Günlük kota için `x-should-retry: false`.
- **Kullanım sayımı:** `stream_options.include_usage` istenince Groq kullanımı iki parçada gönderiyor, LangChain topluyordu (2.393 yerine 4.786) → istenmiyor; Groq son parçada zaten gönderiyor (ham akış ve limit başlıklarıyla doğrulandı).
- **Tahmin yedeği:** tiktoken yüklenemezse 3,6 karakter/token ve 10 dk'da bir arka planda yeniden deneme.
- **`get_drug` düzeltmesi kapsam içi:** yeni araç açıklaması yan etki/farmakokinetik için `detail="high"`i doğru biçimde gösteriyor; bu yol artık sık kullanılacak. Hatalar salt okunur canlı kontrolde ortaya çıktı.

### 4. Veritabanı, bağımlılık, yapılandırma
- Şema/migration yok. **Uygulama veritabanına yazma yok:** canlı kontroller ve doğrulamalar `default_transaction_read_only=on` ile; "kayıt yok" çifti (Amoxicillin + Loratadine) salt okunur sorguyla seçildi. Yazan testler ayrı `_synth` veritabanında.
- Yeni ayarlar (varsayılanlı; `.env` değişmedi): `LLM_REQUEST_TOKEN_BUDGET=7000`, `CHAT_HISTORY_TOKEN_BUDGET=1000`.
- Yeni bağımlılık yok (tiktoken langchain-openai ile zaten kurulu; ilk kullanımda kodlama dosyasını indirebilir, indiremezse yedek tahmin). `PubMedArticle`'a isteğe bağlı `source_query` alanı (varsayılan boş).
- CI yapılandırmasına dokunulmadı (bkz. 8. bölüm).

### 5. Plan hedefleri — durum ve kanıt
| Hedef | Sonuç | Kanıt |
|---|---|---|
| Sabit yük ≤3.200 token | **2.393** (Groq) | Ham akış sondası ve ajan yolu, 2026-11-23 |
| Tek araçlı ilaç sorusu ≤10 sn | **1,2–3,8 sn** | Canlı kontrol (2. tur, aşağıda) |
| 413 yok | Canlıda yok; aşılma durumunda sağlayıcıya gönderilmeden açık hata | Bütçe denetleyicisi birim testleri; hasta bağlamlı PubMed turu yedek tahminde bile sığıyor |
| Bekleme ekranda | Var | Birim + uç testleri; canlıda art arda soruda 11 sn bildirimi |
| Günlük kapasite ≈25 soru | ≈30–38 tek araçlı soru (hesap: 200K TPD ÷ canlıda soru başına 5.200–6.600 token; önce ≈14) | Canlı kullanım değerleri |

### 6. Çalıştırılan komutlar ve sonuçlar
- Backend birim `pytest tests/unit` → **167 geçti**. Tüm paket, sentetik PG ile (`MEDICALLM_SYNTHETIC_PG_URL=…_synth`) → **193 geçti, 1 kaldı** (önceden var olan `change-password` import hatası). Ön yüz `npx vitest --run` → **53 geçti**; `vite build` başarılı.
- Canlı kontrol (gerçek Groq + salt okunur yerel DB; `scripts/check_live_stack.py --pause 50`, 2026-11-23). Süre; çağrı başına giriş token'ı (Groq):

  | Soru | Süre | Araç durumu | Çağrılar (giriş) |
  |---|---|---|---|
  | Selamlaşma | 0,8 sn | — | 2.393 |
  | Varfarin nedir | 2,2 sn | FOUND | 2.392 + 3.897 |
  | Varfarin + aspirin | 1,3 sn | FOUND | 2.392 + 2.625 |
  | Aynı sohbette takip ("kaynak ve önem") | 1,2 sn | FOUND | 2.496 + 2.729 |
  | "Xyzzyl" + varfarin | 2,9 sn | FOUND (yaklaşık eşleşme Levocetirizine; yanıt bunu söyleyip onay istedi) | 2.395 + 2.657 |
  | Amoxicillin + Loratadine | 2,1 sn | NO_RECORD ("güvenli anlamına gelmez") | 2.394 + 2.579 |
  | PubMed 3 makale | 11,4 sn | 3 makale | 2.401 + 3.680 |
  | Parasetamol (art arda 1.) | 3,8 sn | FOUND | 2.387 + 3.718 |
  | İbuprofen (art arda 2.) | 12,5 sn | FOUND; **11 sn bekleme bildirimi** | 2.387 + 3.781 |

  Bilinmeyen kaynak numarası hiçbir yanıtta yok.
- İlk canlı tur (aynı gün, düzeltmelerden önce) üç sorunu ortaya çıkardı: `get_drug(high)` hataları/yavaşlığı ve iki kat sayılan kullanım. Üçü de düzeltildi ve ikinci turda doğrulandı.
- Bağımsız inceleme (4 boyut, iki mercekle doğrulama): 33 bulgu. Doğrulanan ya da elle teyit edilenler düzeltildi: kayıt sınırında gizlenen kayıtlar, PubMed özet kırpma, çoklu sorguda alt grup kaybı, hasta bağlamında 10 makalenin bütçeyi aşması, yedek tahminin fazla tutuculuğu, bildirimin görünür alana kaydırılmaması, gerçekleşmeyecek beklemenin duyurulması, süre biçimi, eksik testler. Doğrulayıcıların bir kısmı kota nedeniyle çalışamadı; o bulgular kod okunarak teyit edildi.

### 7. Nasıl çalıştırılır ve kontrol edilir
- Başlatma değişmedi. Bekleme bildirimi: iki ilaç sorusunu art arda sorun → ikincisinde "Sağlayıcının dakikalık sınırı dolu…" satırı.
- `/health` → `llm.provider_limits` (`tokens_per_minute_remaining`, `requests_per_day_remaining`, son 429) ve `llm.token_estimator`.
- Canlı kontrol (yazma yok, Groq kotası harcar, ≈50K token): `cd backend && uv run python scripts/check_live_stack.py --pause 50 --out live_check.json` (`--only` ile tek soru).

### 8. Bilinen eksikler, riskler, geri alma
- **Model hâlâ zaman zaman kayıtta olmayan bilgi ekliyor:** 9 canlı yanıttan birinde (parasetamol) "en fazla 4 g/24 saat" doz üst sınırı, DrugBank kaydında olmadığı halde yazıldı ve sona DrugBank atfı kondu (kayıt metinlerinde "4 g" yok; doz tablosu modele gönderilmiyor). Yönerge bunu açıkça yasaklıyor; arayüz "atıfsız 7 satır" uyarısı gösteriyor ama engellemiyor. Aşama 0'daki INR örneğiyle aynı sınıf; kalıcı çözüm yanıt sonrası doğrulayıcı veya yapılandırılmış özet (M-06).
- **Ücretsiz katman tavanı sürüyor:** kuruluş genelinde dakikada ≈1–2 ilaç sorusu, günde ≈30–38. Form 3.5 test setleri (ör. M-05'in 50 uyarısı) birkaç güne yayılmalı ya da ücretli plan gerekir.
- Kısalan yönerge 9 canlı soru ve sözleşme testleriyle kontrol edildi; geniş davranış değerlendirmesi (uzman setleri) yapılmadı. Terminoloji düzeltme kuralı model bilgisine dayanıyor (özgün yönergeden kalan gerilim).
- PubMed yanıtları kırpılmış özetlere dayanır; tam metin yalnız kaynak kartında.
- Başlık üretimi kendi LLM istemcisini kullanıyor (limit kaydı/bildirimi yok).
- **CI:** `.github/workflows/ci.yml` `openai`/`langchain` kurmuyor; bu yüzden ajanla ilgili birim testleri CI'da çalışmaz (artık hata vermez, atlanır). Gerçek bağımlılıkların CI'a eklenmesi ayrı bir karar.
- Geri alma: proje kökünde `git -c core.autocrlf=false apply -R -p1 STAGE0_1.patch` (Aşama 0'a döner). Veri/migration geri alması gerekmez.

### 9. Sıradaki adım önerisi
1. Ücretli plan kararı (sizin): önce Groq konsolunda Settings → Limits sayfasında `gpt-oss-20b` limitleri görülmeli. Fiyat: giriş $0,075/M, çıkış $0,30/M → soru başına ≈$0,0006.
2. Yanıt sonrası doğrulayıcı (kayıtta olmayan doz/öneri cümlelerini işaretleme veya engelleme) — M-06 ile birlikte.
3. Aşama 0'daki 2–4. adımlar geçerli (uzman test setleri, `analyze-patient` yetki ve `change-password` hataları, M-01 veri şeması).
