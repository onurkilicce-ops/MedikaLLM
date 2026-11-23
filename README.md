# MedikaLLM — ekip deneme sürümü

Bu dal, 23 Kasım 2026 tarihinde yerel MedicaLLM projesinden alınan güncel geliştirme kopyasıdır. Tamamlanmış ürün veya klinik olarak doğrulanmış sürüm değildir. Amaç ekip arkadaşlarının kendi bilgisayarlarında kurulum ve temel işlevleri deneyebilmesidir. **Şifre değiştirme akışında doğrulanmış bir hata vardır.** Güncel kontroller: [23 Kasım inceleme notu](REVIEW_2026-11-23.md).

Dal: `team-test/2026-11-23-stage-0-1`. `main` dalına yükleme veya bir sunucuya dağıtım yapılmaz. Claude'un yerel çalışma klasörü değiştirilmemiştir; bu kopyadan sonra yaptığı değişiklikler bu commit'e dahil değildir.

## Başlangıç

```powershell
git clone --branch team-test/2026-11-23-stage-0-1 --single-branch https://github.com/onurkilicce-ops/MedikaLLM.git
cd MedikaLLM
Copy-Item .env.example .env
```

Gerekenler: Git, Node.js 20+, Python 3.11+ (kilitli bağımlılıklar için Python 3.13 tercih edilebilir), uv ve çalışan Docker Desktop. Alternatif olarak `vector` ve `pg_trgm` uzantıları kurulu yerel PostgreSQL kullanılabilir.

`.env` dosyasını yerel editörde açın:

- `DO_MODEL_ACCESS_KEY`: kendi Groq anahtarınız.
- `JWT_SECRET`: kendinizin oluşturduğu uzun, rastgele bir değer. Örneğin `python -c "import secrets; print(secrets.token_urlsafe(48))"` çıktısı.
- `ADMIN_PASSWORD`: yönetici panelini kullanacaksanız kendinize ait bir parola; boşsa yönetici girişi devre dışıdır.
- Veritabanı örneği aşağıdaki yerel Docker servisiyle uyumludur. 5432 portu zaten kullanılıyorsa mevcut veritabanını durdurmayın; port ve bağlantı adresini kendi ortamınıza uygun ayarlayın.

Anahtarları, `.env` dosyasını veya kullanıcı verilerini GitHub'a göndermeyin.

### 1. Veritabanı

Proje kökünde:

```powershell
docker compose -f compose.local.yml up -d
docker compose -f compose.local.yml ps
```

Veritabanı `healthy` olduktan sonra:

```powershell
cd backend
uv sync --locked
uv run python scripts/init_tables.py
uv run python run.py
```

`init_tables.py` boş tabloları ve gerekli uzantıları oluşturur; DrugBank verisini yüklemez. Başlangıçta embedding modeli indirilebilir; ilk açılış uzun sürebilir. Terminalde `Application startup complete` mesajını bekleyin.

### 2. Arayüz

İkinci terminalde, klonladığınız projenin kökünden:

```powershell
cd frontend
npm ci
npm run dev
```

Arayüz: http://localhost:3000

API durumu: http://localhost:8000/health

API belgeleri: http://localhost:8000/docs

Bu ekip denemesinde `start-local.cmd` yerine yukarıdaki komutları kullanın; eski başlatıcı önceden kurulmuş özel bir PostgreSQL klasörüne dayanır. Eski `compose.yml`/`compose.prod.yml` dağıtım ayarları bu kurulumun parçası değildir.

## Neyi deneyebilirsiniz?

1. Arayüz açılıyor mu, backend başlangıcı tamamlanıyor mu?
2. Kayıt/giriş akışı çalışıyor mu? Bu örnek ayarda e-posta hizmeti yoktur; doğrulama kodu backend terminaline `[AUTH] No email backend configured` satırında yazılır. Yerel denemede bu kodu kullanın; kodu veya logları herkese açık paylaşmayın, gerçek hasta verisi kullanmayın.
3. Kendi Groq anahtarınızla basit bir sohbet yanıtı geliyor mu? `/health` tek başına gerçek LLM yanıtını doğrulamaz.
4. Eksik veride anlaşılır bir uyarı geliyor mu? Boş DrugBank tablolarında ilaç sonucu çıkmaması beklenir; bu, ilaçların güvenli olduğu anlamına gelmez.

## DrugBank verisi ayrı

Bu depoda DrugBank XML/arşivi, veritabanı dökümü, gerçek kullanıcı/hasta/sohbet kayıtları ve API anahtarları yoktur. İlaç sorgularını tam denemek için ekip içinde erişim yetkisi olan verinin ayrı aktarılması gerekir. Veri dosyalarını issue veya commit'e eklemeyin. Büyük XML aktarımını, veri olmadan açılış denemesinden ayrı planlayın.

## Bu kopyanın durumu

- Sohbet hata kartları, yeniden deneme, veri bulunamadı/hata ayrımı ve kaynak bağlantıları mevcut.
- Son çalışma: Groq istek boyutu kontrolü, bekleme/kota mesajları, sistem yönergelerinin ve araç açıklamalarının küçültülmesi.
- `STATUS.md`, uygulayıcının Aşama 0 ve 0.1 raporudur; raporlanan canlı sonuçlar bağımsız incelemede yeniden ölçülmedi.
- Güncel bağımsız test sonuçları: [REVIEW_2026-11-23.md](REVIEW_2026-11-23.md). Önceki 22 Kasım kopyasının geçmiş kaydı: [TEAM_CHECKPOINT.md](TEAM_CHECKPOINT.md).
- Eski otomatik sunucu dağıtımı ve sağlık izleme workflow'ları bu daldan çıkarıldı. CI dosyası tarihsel olarak korunmuştur; mevcut tetikleyicisi `main`/PR içindir, bu ilk test dalı push'u otomatik CI başarısı anlamına gelmez.

Bir sorun bildirirken işletim sistemi, bu commit'in kimliği (`git rev-parse --short HEAD`), çalıştırdığınız adım, beklediğiniz sonuç ve kişisel bilgileri temizlenmiş hata metnini yazın.

## Kaynak proje

Bu çalışma [IsmailEsadKilic/MedicaLLM](https://github.com/IsmailEsadKilic/MedicaLLM) projesinin devamıdır. İlk ekibin katkıları korunur. Yerel kaynak klasörde `.git` bulunmadığından bu ilk commit eski Git geçmişini içermez; bağımsız bir durum kaydıdır. Bu depoya yeni bir açık kaynak lisansı atanmadı.
