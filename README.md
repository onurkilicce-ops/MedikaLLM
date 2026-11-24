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

## Sorun bildirme

İşletim sistemi, `git rev-parse --short HEAD`, çalıştırdığınız adım, beklediğiniz sonuç ve kişisel bilgileri/anahtarları temizlenmiş hata metni.

## Kaynak proje

Bu çalışma [IsmailEsadKilic/MedicaLLM](https://github.com/IsmailEsadKilic/MedicaLLM) projesinin devamıdır. İlk ekibin katkıları korunur. Yerel kaynak klasörde `.git` bulunmadığından ilk commit eski Git geçmişini içermez. Bu depoya yeni bir açık kaynak lisansı atanmadı.
