# MedikaLLM — ekip geliştirme sürümü

MedicaLLM, hekim ve eczacı gibi sağlık profesyonellerinin ilaç etkileşimlerini kaynaklarıyla incelemesine yardımcı olan bir web uygulamasıdır (React/Vite arayüz, Python/FastAPI arka uç, PostgreSQL/DrugBank, araç kullanan sohbet ajanı). Bu depo tamamlanmış ürün veya klinik olarak doğrulanmış sürüm **değildir**. Testlerin geçmesi klinik kabul anlamına gelmez; "kayıt yok" sonucu "güvenli" demek değildir.

- Ortak entegrasyon dalı: `team-test/2026-11-23-stage-0-1` (başlangıç `f549e597e41539704e9b39a5ff0e30e6af7c8cd8`). `main` dalına yükleme veya sunucuya dağıtım yapılmaz.
- Güncel ilerleme kaydı: [STATUS.md](STATUS.md) → "Tur 1" bölümü (görev sınırları, sözleşmeler C1–C3, kabul edilen PR/SHA'lar). Bağımsız inceleme: [REVIEW_2026-11-23.md](REVIEW_2026-11-23.md). Geçmiş kayıt: [TEAM_CHECKPOINT.md](TEAM_CHECKPOINT.md).
- Parola değiştirme (`POST /api/auth/change-password`) ve hekimin hasta analizi (`POST /api/drugs/analyze-patient`) hataları R1-O1 görev dalında düzeltildi; entegrasyon dalına alınıp alınmadığını STATUS "Tur 1" tablosundan kontrol edin.

## Ön koşullar

| Araç | Sürüm | Not |
|---|---|---|
| Git | herhangi güncel | |
| Python | **3.12** (CI ile aynı) | `uv` gerekirse 3.12'yi kendisi indirir |
| [uv](https://docs.astral.sh/uv/) | 0.10.x (CI: 0.10.7) | bağımlılıklar `backend/uv.lock` ile kilitli |
| Node.js | 20+ (CI: 20) | npm 11 kurulum betiklerini onay bekletebilir; aşağıya bakın |
| PostgreSQL 16 | `vector` (pgvector) ve `pg_trgm` uzantılarıyla | Docker Desktop **veya** bu uzantılara sahip yerel kurulum |

Eski `start-local.cmd` başlatıcısı yalnız bir geliştiricinin bilgisayarındaki özel PostgreSQL klasörüne dayanır; **ön koşul değildir**, kullanmayın. `compose.yml`/`compose.prod.yml` dağıtım dosyalarıdır, yerel kurulumun parçası değildir.

## Temiz kurulum (verisiz geliştirme kurulumu)

Mevcut bir klasörün üzerine klonlamayın; yeni, boş bir klasör seçin.

```powershell
git clone --branch team-test/2026-11-23-stage-0-1 https://github.com/onurkilicce-ops/MedikaLLM.git MedikaLLM
cd MedikaLLM
git rev-parse HEAD
Copy-Item .env.example .env
```

`.env` dosyasını yerel editörde açın (bu dosya Git'e girmez, kimseyle paylaşmayın):

- `JWT_SECRET`: kendinizin ürettiği uzun rastgele değer, örn. `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
- `DO_POSTGRES_URL`: kendi yerel veritabanınız. Docker örneği varsayılan değerle uyumludur. 5432 doluysa çalışan veritabanını durdurmayın; başka port seçip URL'yi ona göre değiştirin. `DB_SSLMODE=disable` yerel PostgreSQL içindir.
- `DO_MODEL_ACCESS_KEY`: kendi Groq anahtarınız (isteğe bağlı). Boşsa uygulama açılır, kayıt/giriş/hasta ve ilaç ekranları çalışır, ama sohbet yanıtı üretilemez. `LLM_BASE_URL`, `DO_LLM_MODEL_ID` sağlayıcı/model ayarlarıdır; bu turda değiştirilmez.
- `ADMIN_PASSWORD`: yönetici paneli gerekiyorsa kendi parolanız; boşsa yönetici girişi kapalıdır.

### 1. Veritabanı

Docker ile (proje kökünde):

```powershell
docker compose -f compose.local.yml up -d
docker compose -f compose.local.yml ps
```

Docker yoksa: `vector` ve `pg_trgm` uzantıları olan yerel PostgreSQL 16'da boş bir veritabanı oluşturup `DO_POSTGRES_URL`'yi ona yöneltin.

### 2. Backend

```powershell
cd backend
uv sync --locked --python 3.12
uv run python scripts/init_tables.py
uv run python run.py
```

- `uv sync --locked`, `uv.lock` dosyasıyla tam aynı paketleri kurar; kilit dosyası güncel değilse durur (sessizce değiştirmez).
- `init_tables.py` uzantıları ve **boş** tabloları oluşturur, veri yüklemez, var olan tabloları silmez.
- İlk açılışta embedding modeli Hugging Face'ten indirilir; ilk başlangıç 1–2 dakika sürebilir. `Application startup complete` satırını bekleyin.
- `run.py` geliştirme sunucusudur (otomatik yeniden yükleme). Yalnız yerel ağda kullanın.

### 3. Arayüz

İkinci terminalde, proje kökünden:

```powershell
cd frontend
npm ci
npm run dev
```

npm 11 `allow-scripts` uyarısı (esbuild postinstall) gösterebilir; test ve derleme bu uyarıyla çalışır.

- Arayüz: http://localhost:3000
- API durumu: http://localhost:8000/health
- API belgeleri: http://localhost:8000/docs

### 4. Sentetik kontrol (gerçek kişi/hasta verisi kullanmayın)

1. http://localhost:3000/register üzerinden "Sağlık profesyoneli" hesabı açın. E-posta hizmeti yapılandırılmadığından doğrulama kodu backend terminalinde `[AUTH] No email backend configured` satırında görünür. Kodu/logu paylaşmayın.
2. Giriş yapın; Hastalar ekranından uydurma bir hasta ve ilaç adları ekleyin.
3. **Backend API kontrolü (hasta analizi):** http://localhost:8000/docs → `POST /api/auth/login` ile token alın, "Authorize" ile ekleyin, `POST /api/drugs/analyze-patient` gövdesi `{"patient_id": "<hastanın patient_id'si>"}`. Atanmış hekim 200 alır; verisiz kurulumda `status` `unresolved` olur (ilaçlar veritabanında bulunamadı). Bu beklenen sonuçtur ve "etkileşim yok/güvenli" anlamına gelmez. Başka bir hekim hesabıyla 403, olmayan `patient_id` ile 404 beklenir.
   - Bu adım yalnız **backend sözleşmesini (C2)** doğrular. Arayüzdeki hekim hasta analizi ekranının (`doctor/PatientDetail.jsx`) yanıtı doğru göstermesi Halil'in R1-H1 görevidir ve henüz kabul edilmedi; arayüzde görünen sonuç bu kontrolün kanıtı sayılmaz.
4. Ayarlar → "Şifreyi değiştir": eski parolayla giriş reddedilmeli, yenisiyle kabul edilmelidir. Yeni parola en fazla 72 **bayt** olabilir (UTF-8; Türkçe karakterler 2 bayt sayılır); daha uzun parola 422 ile reddedilir, kesilmez.
5. `/health` içindeki `llm.api_key_configured` yalnız anahtarın tanımlı olduğunu gösterir; **LLM'in gerçekten yanıt verdiğini doğrulamaz**. Bunun için sohbette basit bir soru sorun.

## Verisiz kurulum ile DrugBank içeren kurulumun farkı

| | Verisiz geliştirme kurulumu (bu README) | DrugBank içeren kurulum |
|---|---|---|
| İlaç tabloları | Boş (`init_tables.py`) | Lisanslı DrugBank içe aktarımıyla dolu (geçmiş raporda 17.430 ilaç; bu klonda doğrulanmadı) |
| İlaç arama/etkileşim | Sonuç yok; hasta ilaçları `unresolved` | Kayıtlar, kaynak bağlantıları |
| Kayıt/giriş/parola/hasta yetkisi | Çalışır | Aynı |
| Testler | Birim testleri + sentetik PostgreSQL testleri yeterli | Gerçek veri testleri ayrıca planlanır |
| Nasıl elde edilir | Bu README | Ekip içinde erişim yetkisi olan kişiden ayrı aktarım. DrugBank XML/arşivi, veritabanı dökümü, gerçek kullanıcı/hasta/sohbet kaydı ve API anahtarı **bu depoda yoktur ve eklenmez** |

Mevcut bir veritabanını yeniden içe aktarmayın veya silmeyin; büyük XML aktarımını verisiz açılış denemesinden ayrı planlayın.

## Testler

Backend (`backend/` içinde, kilitli kurulumdan sonra):

```powershell
uv run pytest tests -p no:cacheprovider -q -ra
```

Yerelde PostgreSQL ve tokenizer verisi yoksa ilgili testler **atlanır** ve `-ra` çıktısında nedenleriyle listelenir. Atlanan test geçmiş sayılmaz.

Tam paket (CI ile aynı, hiçbir atlamaya izin vermeyen katı mod):

1. Yalnız bu iş için **yeni, boş** bir veritabanı oluşturun; adı `_synth` ile bitsin ve yerel (`127.0.0.1`/`localhost`) olsun. Uygulama veritabanınızı kullanmayın.
2. Ortam değişkenleri (PowerShell):

```powershell
$env:MEDICALLM_SYNTHETIC_PG_URL = "postgresql://KULLANICI@127.0.0.1:PORT/medicallm_test_synth"
$env:MEDICALLM_SYNTHETIC_PG_CONFIRM = "medicallm_test_synth"
$env:MEDICALLM_STRICT_TESTS = "1"
uv run pytest tests -p no:cacheprovider -q -ra
```

Sentetik testler bu veritabanındaki tabloları siler ve yeniden kurar. Koruma, sürücünün (psycopg2) gerçekten kullanacağı hedefi denetler: ad `_synth` ile bitmeli, sunucu yerel (`127.0.0.1`/`localhost`/`::1`) olmalı, `MEDICALLM_SYNTHETIC_PG_CONFIRM` aynı adı içermeli, URL'de `?` ile başlayan hiçbir bağlantı seçeneği bulunmamalı (`?host=`, `?dbname=` vb. hedefi değiştirebilir), `PGHOSTADDR`/`PGSERVICE` ortam değişkenleri tanımlı olmamalı, bağlandıktan sonra sunucunun bildirdiği `current_database()` onaylanan ad olmalı ve veritabanında sentetik olmayan kullanıcı/ilaç bulunmamalı. Aksi halde bağlanmadan (ya da yalnız okuyup) hiçbir şey silinmeden durur. Katı modda eksik paket, eksik veritabanı adresi, eksik tokenizer verisi (`tiktoken` `o200k_base`, ilk kullanımda indirilir) veya hiç test toplamayan test modülü hata verir.

Frontend (`frontend/` içinde): `npm test` ve `npm run build`.

CI (`.github/workflows/ci.yml`): her PR'da backend için `uv lock --check`, `uv sync --locked`, gerçek paketlerin içe aktarılması, sentetik PostgreSQL servisiyle katı modda tüm testler; frontend için `npm ci`, `npm test`, `npm run build`. Ücretli sağlayıcı, API anahtarı ve gerçek DrugBank verisi gerekmez. Otomatik dağıtım/sağlık izleme workflow'u yoktur.

## M-02 ekranı: seçim, çizelge ve kaynaklı zamanlama

Hekim hesabıyla giriş yaptıktan sonra paneldeki **M-02 · Zamanlama**
bağlantısını veya `/timing` yolunu açın. 2–10 farklı ilaç seçin. Tmax, yarı ömür
ve uygun değerlerde yaklaşık 5× süre aynı saat ekseninde, koşulları ayrı satırlarda
gösterilir. Eksik/inceleme gereken değer çizilmez; metni ve gerekçesi kartta kalır.
Çizelge kişisel konsantrasyon eğrisi veya güvenli ilaç alma takvimi değildir.

Zaman aralığı önerileri ayrı `/api/timing/advice` çağrısıyla, yalnız seçilen ürün
profili ve açık kaynak eşleşince gösterilir. Profil seçilmemesi, katalogda kural
olmaması ve teknik hata ayrıdır. Kaynak kapsamı [SOURCES.md](backend/src/timing/SOURCES.md),
alan sözleşmeleri [API.md](backend/src/timing/API.md)'dedir. Kadir'in ajanı/C1 ve
Halil'in hasta ekranı bu akışın ön koşulu değildir.

**M-03 (aynı ekran): organlar, enzimler ve taşıyıcılar.** Karşılaştırmadan sonra
ekranın altında "Organlar, enzimler ve taşıyıcılar (M-03)" bölümü dolar. M-02
sonuçlarını beklemez ve geciktirmez. Her ilaç için gösterilenler:

- **Organlar:** hangi organların temizlediğini söyleyen kayıt cümleleri, birebir alıntıyla.
  Organa yüzde atanmaz; yüzdeler alıntıda okunur.
- **Proteinler:** DrugBank'in listelediği enzim, taşıyıcı ve taşıyıcı proteinler. İlacın
  her birini kullanıp kullanmadığı (substrat), yavaşlatıp yavaşlatmadığı (inhibitör) ya
  da hızlandırıp hızlandırmadığı (indükleyici) gösterilir.

Her ilaç çifti için ortak bir insan proteini üzerinden açıklama yapılır (ör. "A, B'yi
işleyen enzimi yavaşlatır; B kanda birikebilir"). DrugBank'in kendi etkileşim metni de
yanında gösterilir. Ortak protein yokluğu "etkileşim yok" değildir. Uç
`POST /api/mechanism/compare`; kurallar [RULES.md](backend/src/mechanism/RULES.md),
sözleşme [API.md](backend/src/mechanism/API.md).

### Baştan sona sentetik deneme (gerçek DrugBank verisi gerekmez)

Ön koşul: yalnız test için ayrılmış, çalışan yerel PostgreSQL ve yeni boş
`medicallm_m02_synth` veritabanı; `vector` ve `pg_trgm` uzantıları kullanılabilir
olmalı. Aşağıdaki `--seed` yalnız bu onaylanmış test veritabanını yeniden kurar.
Mevcut uygulama/DrugBank veritabanı veya veri klasörü kullanılmaz; betik bir
PostgreSQL kümesi başlatmaz. `KULLANICI` ve `PORT` kendi ayrı test sunucunuzundur.

Backend terminali, `backend/` içinde:

```powershell
uv sync --locked
$env:DO_POSTGRES_URL = "postgresql://KULLANICI@127.0.0.1:PORT/medicallm_m02_synth"
$env:M02_DEMO_CONFIRM = "medicallm_m02_synth"
$env:MEDICALLM_SYNTHETIC_PG_CONFIRM = "medicallm_m02_synth"
$env:DB_SSLMODE = "disable"
$env:JWT_SECRET = "m02-local-synthetic-only-not-production"
$env:ADMIN_PASSWORD = "m02-local-synthetic-only"
$env:LLM_BASE_URL = "http://127.0.0.1:9/v1"
$env:DO_MODEL_ACCESS_KEY = ""
uv run python scripts/m02_synthetic_demo.py --seed --serve
```

Bu M-02 test sunucusu `127.0.0.1:18102` üzerinde gerçek kimlik/yetki, router,
servis ve PostgreSQL kullanır. Yalnız uygulama başlangıcındaki LLM, periyodik işler
ve migration başlatması devre dışıdır; üretim başlatıcısı değildir. İki mevcut
sentetik hedef koruması geçmeden veri yazılmaz. `.env` değiştirilmez. Gerçek anahtar
gerekmez. Betik yeni terminalde de hedef ve iki onay değişkenini ister.

Ayrı frontend terminali, `frontend/` içinde:

```powershell
npm ci
$env:VITE_BACKEND_URL = "http://127.0.0.1:18102"
npm run dev
```

1. `http://localhost:3000/login` açın. Yalnız demo hesabı:
   `synthetic.doctor.a@synthetic-medicallm.org`, parola `Synth-Pass-1!`.
2. `/timing` açın; `[SYNTHETIC] Ciprofloxacin` ve `[SYNTHETIC] Sucralfate`
   ekleyip karşılaştırın. Sentetik ilk ilaçta Tmax **0,5–1 sa**, yarı ömür
   **4–6 sa**, ayrı yaklaşık 5× **20–30 sa** beklenir; Tmax eklenmez.
   Kaynak kartını açın, alıntıyı/konumu görün. Bunlar gerçek ilaç PK değerleri değildir.
3. Demo için ilk ilaçta UK 500 mg tablet, ikincide oral sucralfate profilini
   seçin; yeniden karşılaştırın. Kaynağın iki ayrı yönünü görün: ilk ilaç
   diğerinden **1–2 sa önce** veya **en az 4 sa sonra**. Bu profiller gerçek
   kullanımda yalnız ürün gerçekten eşleşiyorsa seçilir.
4. İlk ilaçta Ciproxin UK süspansiyon profilini ve öğün dışında süt ürününü
   seçin. İlaç–gıda kaynağı görünmeli. Öğünün parçası süt ürününe geçince bu
   sayısal kural uygulanmamalı. Levothyroxine + Empty agent seçimi, US tablet
   profili ve kahvaltı ile yalnız **0,5–1 sa önce** yönünü gösterir.
5. Uncertain agent + Empty agent seçin: yanlış ilaca bağlanmış değer/5× yok;
   inceleme ve eksik veri mesajları var. İlaç çıkarılınca eski sonuç silinir.
   Hasta demo hesabı (`synthetic.patient2@synthetic-medicallm.org`, aynı test
   parolası) 403 alır. Backend kapalıysa hata görünür, boş/güvenli sonuç görünmez.

Otomatik gerçek HTTP akışı (yukarıdaki sentetik sunucu açıkken, `frontend/`):

```powershell
npx vitest run --config vite.m02.config.js
```

Bu test React DOM → gerçek HTTP → kimlik/yetki → servis → sentetik PG yoludur;
mock API veya görsel tarayıcı testi değildir. CI aynı akışı kendi geçici PG
servisinde çalıştırır. Normal frontend testleri `npm test`, derleme `npm run build`.
Çıkışta iki terminali Ctrl+C ile kapatın; ayrı test PostgreSQL'inizi kendi yönetim
yönteminizle durdurun. Gerçek DrugBank kümesini bu deneme için açmayın.

Uzman kabul kümesi ve henüz yapılmamış değerlendirme:
[docs/M02_Uzman_Kabul.md](docs/M02_Uzman_Kabul.md).

## M-02 zaman verisi API'si (`POST /api/timing/compare`) — deneme

2–10 DrugBank kimliği için saklanan metindeki Tmax (`absorption`) ve yarılanma ömrü (`half_life`) ifadelerini kaynak alıntısı, koşulları ve satır içi referansıyla; ayrıca ayrı bir "≈5 × yarılanma ömrü" nesnesiyle döndürür. Salt okunur; LLM çağırmaz; hasta/doz almaz. **Klinik öneri değildir**, zaman aralığı önerisi üretmez (`timing_advice.status = "not_evaluated"`), uzman kabulü yapılmamıştır. Tipli sözleşme ve tam örnekler: [backend/src/timing/API.md](backend/src/timing/API.md); ayrıştırma kuralları: [backend/src/timing/RULES.md](backend/src/timing/RULES.md).

Ayrı, **sentetik** bir veritabanıyla 5 adımda deneme (uygulama veya gerçek DrugBank veritabanınızı kullanmayın; bu adımlar seçtiğiniz `_synth` veritabanını siler ve yeniden kurar). PowerShell, `backend/` içinde:

1. Yerel PostgreSQL'de yeni, boş bir veritabanı oluşturun (adı `_synth` ile bitsin, ör. `medicallm_demo_synth`; `vector` ve `pg_trgm` uzantıları kurulu olsun).
2. Sentetik hesapları ve ilaç satırlarını yükleyin:
   ```powershell
   $env:DEMO_URL = "postgresql://KULLANICI@127.0.0.1:PORT/medicallm_demo_synth"
   $env:MEDICALLM_SYNTHETIC_PG_CONFIRM = "medicallm_demo_synth"
   uv run python -m tests.integration.synthetic_data $env:DEMO_URL
   ```
3. İki sentetik kayda **sentetik** zaman metni ekleyin (herhangi bir SQL istemcisiyle, yalnız bu veritabanında):
   ```sql
   UPDATE drugs SET name = '[SYNTHETIC] Timing Agent A',
     absorption = '[SYNTHETIC] Peak plasma concentrations are reached within 0.5-1 hours after oral administration.',
     half_life  = '[SYNTHETIC] The elimination half-life is 4-6 hours.' WHERE drug_id = 'DB00006';
   UPDATE drugs SET name = '[SYNTHETIC] Timing Agent B', absorption = 'Not Available',
     half_life  = '[SYNTHETIC] The half-life is 90 minutes in healthy adults and 3 hours in patients with renal impairment.'
     WHERE drug_id = 'DB00316';
   ```
4. Backend'i **yeni bir terminalde**, `backend/` içinde başlatın. Bu blok kendi başına yeterlidir: hedefi bu terminalde açıkça yazar ve uygulamayı ancak hedef doğrulanırsa açar. `.env` dosyasını değiştirmez. Değişken unutulursa uygulama `.env`/`POSTGRES_URL`'deki veritabanına geri dönmez; doğrulayıcı durur. `KULLANICI`/`PORT` değerlerini 2. adımdakiyle aynı yazın.
   ```powershell
   $env:DO_POSTGRES_URL = "postgresql://KULLANICI@127.0.0.1:PORT/medicallm_demo_synth"
   $env:M02_DEMO_CONFIRM = "medicallm_demo_synth"
   $env:DB_SSLMODE = "disable"
   uv run python -m src.timing.demo_guard
   if ($LASTEXITCODE -eq 0) { uv run python run.py } else { Write-Host "Durdu: demo hedefi dogrulanmadi; uygulama baslatilmadi." }
   ```
   `src.timing.demo_guard` yalnız bu terminalin ortam değişkenlerini okur, `.env`'yi okumaz. Şunları ister: `DO_POSTGRES_URL` tanımlı olmalı; yerel (`127.0.0.1`/`localhost`) ve sorgu seçeneksiz bir PostgreSQL adresi olmalı; veritabanı adı `_synth` ile bitmeli ve `M02_DEMO_CONFIRM` ile aynı olmalı. Ardından salt okunur bağlanıp sunucunun bildirdiği veritabanını ve sentetik olmayan kullanıcı bulunmadığını doğrular. Aksi halde çıkış kodu 2 olur ve hiçbir şey başlatılmaz.
5. Sentetik hekim hesabıyla token alıp iki ilaçla deneyin (parola yalnız bu sentetik veritabanındaki test değeridir, `tests/integration/synthetic_data.py`):
   ```powershell
   $login = Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/auth/login -ContentType application/json -Body '{"email":"synthetic.doctor.a@synthetic-medicallm.org","password":"Synth-Pass-1!"}'
   $r = Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/timing/compare -ContentType application/json -Headers @{Authorization = "Bearer $($login.token)"} -Body '{"drug_ids":["DB00006","DB00316"]}'
   $r.drugs | Select-Object requested_id, lookup_status, data_status
   $r.drugs[0].measurements | Select-Object measure_type, @{n='hours';e={$_.hours}}, @{n='quote';e={$_.source.quote}}
   $r.drugs[0].derived | Select-Object status, @{n='hours';e={$_.hours}}, includes_tmax
   $r.drugs[0].measurements | Select-Object @{n='ref';e={$_.source.reference_scope}}, @{n='stored_ref';e={$_.source.stored_reference_attributed}}
   ```
   Beklenen: `DB00006` için Tmax 0,5–1 sa (uygulamadan sonra), yarılanma ömrü 4–6 sa ve ayrı `derived` 20–30 sa (`includes_tmax = false`); `DB00316` için `data_status.tmax = placeholder`, 1,5 sa (sağlıklı yetişkin) ve 3 sa (böbrek yetmezliği) ayrı değerler. Doktor profili olmayan hesap 403, token'sız istek 401, aynı kimlik iki kez 422 alır.

Gerçek veri envanteri (yalnız sayım, salt okunur; okumadan önce `transaction_read_only = on` doğrulanır, metin/URL yazmaz): `uv run python scripts/audit_m02_data.py --out m02_inventory.json` (bağlantı `M02_AUDIT_DB_URL` veya `DO_POSTGRES_URL`). Çıkış 0 = tamam, 1 = bağlanılamadı/salt okunur doğrulanamadı.

## Canlı yığın kontrolü (`backend/scripts/check_live_stack.py`)

Kendi yapılandırmanızla (veritabanı + LLM sağlayıcısı) yığının gerçekten çalışıp çalışmadığını **hiçbir şey yazmadan** denetler. Veritabanına salt okunur bağlanır; sohbet kayıtları belleğe yazılır, veritabanına değil. LLM senaryoları gerçek sağlayıcı çağrısı yapar ve kotadan düşer.

```powershell
cd backend
uv run python scripts/check_live_stack.py --skip-llm                 # yalnız DB; sağlayıcı çağrısı yok
uv run python scripts/check_live_stack.py --only normal_chat         # tek, tıbbi olmayan selam senaryosu
uv run python scripts/check_live_stack.py --only normal_chat --out live_check.json
```

`--only` virgülle ayrılmış senaryo adları alır (`normal_chat`, `single_drug`, `two_drug_interaction`, `follow_up_same_conversation`, `unknown_drug`, `no_record_pair`, `pubmed_three_articles`, `back_to_back_first`, `back_to_back_second`). Boş değer, boş öğe veya bilinmeyen tek bir ad bile tüm isteği **bağlantı kurulmadan** reddeder; hiçbir zaman "kısmen çalıştır" ya da "hepsini çalıştır"a dönüşmez. Bayrak verilmezse dokuz senaryonun hepsi çalışır (kota harcar).

**Çıkış kodları** (raporun `overall.exit_code` alanı her zaman süreç çıkış koduyla aynıdır):

| Kod | Anlamı |
|---|---|
| 0 | İstenen **her** kontrol çalıştı ve başarılı oldu. `--skip-llm` ile LLM `skipped_by_flag` olarak raporlanır; bu, sağlayıcının çalıştığının kanıtı **değildir** (`overall.llm_provider_verified: false`). |
| 1 | İstenen bir kontrol başarısız oldu ya da çalıştırılamadı: DB'ye bağlanılamadı, `transaction_read_only` `on` doğrulanamadı, tablo yok/okunamadı, API anahtarı yok, ajan kurulamadı, sağlayıcı hatası, terminal `done` olayı gelmedi, boş yanıt ya da kayıtlı sağlayıcı çağrısı yok. Başarısız ön koşuldan sonraki aşamalar `not_run_*` olarak raporlanır, başarılı sayılmaz. |
| 2 | Geçersiz çağrı (ör. bilinmeyen/boş `--only`); veritabanına ve sağlayıcıya hiç dokunulmadan reddedilir. |

**Rapor alanları** (JSON, `report_version: 2`):

- `database.status`: `ok` / `error` / `read_only_not_confirmed`. Okuma sırası: bağlantı (`connected`) → `transaction_read_only` (`on` değilse başka hiçbir şey okunmaz) → tablo başına `exists` ve `count`. Gerçek sıfır `0`, okunamayan sayı `null` + `error` olarak gösterilir; ikisi asla karışmaz.
- `database.drug_data`: `present` (üç tablo da dolu) / `empty` / `partial` / `unknown`. Boş geliştirme DB'si DB aşamasını geçer ama `overall.drugbank_data_present: false` olur — DrugBank verisinin doğrulanması değildir. Satır sayıları klinik içeriğin doğruluğunu kanıtlamaz.
- `agent.status`: `ok` / `error` / `not_attempted` (ör. `--skip-llm`, DB veya anahtar ön koşulu yok).
- `llm.status`: `ok` / `failed` / `skipped_by_flag` (bilinçli atlama) / `not_run_missing_key` (anahtar yok — başarısızlık) / `not_run_prerequisite_failed`. Senaryo başına `status`, `failure_reason` (`terminal_error`, `no_terminal_done`, `empty_answer`, `no_provider_call_recorded`), `terminal_event`, `llm_usage` (sağlayıcının bildirdiği çağrı/token sayısı) ve `provider_limits_after`. İlk başarısız senaryodan sonra kalanlar `not_run_after_failure` olur (kota boşa harcanmaz).
- `overall`: `status`, `exit_code`, `failures`, `llm_provider_verified`, `drugbank_data_present`.

Rapor şifre, API anahtarı, yetki başlığı veya bağlantı URL'si içermez; hatalar yalnız tür adıyla (`ConnectionError` vb.) yazılır. Bir senaryonun başarılı olması o yanıtın tıbbi doğruluğunu kanıtlamaz; "etkileşim kaydı yok" güvenli anlamına gelmez.

## Dal adlandırma

Depoda yalnız şu dal biçimleri kullanılır:

| Dal | Ne için |
|---|---|
| `main` | Varsayılan, kararlı dal |
| `feat/<kisa-ozellik-adi>` | Yeni özellik (ör. `feat/m03-mechanism`) |
| `fix/<kisa-hata-adi>` | Hata düzeltmesi (ör. `fix/r1-live-check`) |
| `chore/<kisa-bakim-adi>` | Bakım, CI, ara anlık görüntü (ör. `chore/stage-0-1-snapshot`) |
| `docs/<kisa-dokuman-adi>` | Yalnız belge (ör. `docs/r1-o1-kabul-kaydi`) |

Adlarda kişi adı ya da tarih yoktur; kısa, küçük harfli ve tireyle yazılır. Her dal bir
pull request ile birleştirilir; CI pull request üzerinde çalışır.

**Not:** Bir pull request açıkken onun kaynak dalını GitHub'da yeniden adlandırmak o
PR'ı kapatır. Gerekirse yeni adla yeni bir PR açılır.

**28 Kasım 2026'daki geçiş.** Eski dallar yeni adlara taşındı:

- `team-test/2026-11-22-checkpoint` → `main`
- `team-test/2026-11-23-stage-0-1` → `chore/stage-0-1-snapshot`
- `feat/onur/m02-timing` → `feat/m02-m03-timing-mechanism`
- `feat/onur/m03-mechanism` → `feat/m03-mechanism`
- `docs/onur/r1-o1-kabul-kaydi` → `docs/r1-o1-kabul-kaydi`
- `fix/onur/r1-live-check` → `fix/r1-live-check`
- `feat/onur/r1-baseline` → `feat/r1-baseline`

Açık PR'lar #1, #3, #5 ve #7 bu yüzden kapandı; yerlerine #8, #9, #10 ve #11 açıldı.

Daha önce klonladıysanız bir kez çalıştırın:

```powershell
git fetch --prune origin
```

```powershell
git remote set-head origin -a
```

Ardından yerel dallarınızı yeni adlarına taşıyın:

```powershell
git branch -m <eski-ad> <yeni-ad>
```

```powershell
git branch -u origin/<yeni-ad> <yeni-ad>
```

## Sorun bildirme

İşletim sistemi, `git rev-parse --short HEAD`, çalıştırdığınız adım, beklediğiniz sonuç ve kişisel bilgileri/anahtarları temizlenmiş hata metni.

## Kaynak proje

Bu çalışma [IsmailEsadKilic/MedicaLLM](https://github.com/IsmailEsadKilic/MedicaLLM) projesinin devamıdır. İlk ekibin katkıları korunur. Yerel kaynak klasörde `.git` bulunmadığından ilk commit eski Git geçmişini içermez. Bu depoya yeni bir açık kaynak lisansı atanmadı.
