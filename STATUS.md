# MedicaLLM — Durum kaydı

Bu dosya projenin **tek durum kaydıdır**; sonraki aşamalar buraya eklenir.
`report.md` önceki ekibin 2. dönem proje raporudur, güncel hedeflerin veya
tamamlanmış işlerin kanıtı değildir. Kapsam kaynağı: *SDP Project Forms A/B*
(Form A "Before Edit With Client" — imzasız taslak; onaylı sözleşme sayılmaz).

---

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
