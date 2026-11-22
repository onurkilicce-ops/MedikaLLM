# Ekip deneme kaydı — 22 Kasım 2026

## Kaynak ve sınır

Bu dal, `MedicaLLM-local-run-support` yerel çalışma klasörünün geliştirme anlık kopyasıdır. Kopyalama sırasında dahil edilen kaynak dosyalarının değişmediği ikinci okumayla doğrulandı. Bundan sonraki Claude değişiklikleri dahil değildir. Kaynak klasöre yazılmadı; testler ayrı kopyada çalıştırıldı. `backend/src` ve `frontend/src` dosyaları, alınan kaynak kopyasıyla SHA-256 karşılaştırmasında aynı kaldı.

## Bu kopyada yapılan hazırlıklar

- README: ekip için klonlama, veritabanı hazırlama, backend/frontend çalıştırma ve sorun bildirme adımları.
- `.env.example`: kişisel sır içermeyen Groq/yerel PostgreSQL örneği; eski örnek yönetici parolası kaldırıldı.
- `.gitignore`: özel yapılandırma, anahtar dosyaları, veritabanı/arşiv dosyaları ve üretilen dosyalar için ek dışlamalar.
- `compose.local.yml`: örnek PostgreSQL portu yalnızca `127.0.0.1` üzerinden açılır.
- Eski `deploy.yml` ve `health-monitor.yml` bu kopyaya alınmadı. Eski `STAGE0.patch`, kullanıcı ayarları, gerçek veri, bağımlılık klasörleri ve loglar alınmadı.

Uygulama iş mantığı değiştirilmedi. Eski `DEPLOYMENT.md`, `report.md`, `STATUS.md` tarihsel belgelerdir; yeni ekip çalıştırma adımlarında README esas alınmalıdır.

## Gerçekten çalıştırılan kontroller

| Kontrol | Sonuç |
|---|---|
| Backend `python -B -m pytest tests/unit -p no:cacheprovider -q` | **139 geçti** |
| Frontend `npm ci --ignore-scripts --no-audit --no-fund` | Başarılı |
| Frontend `npm test` | **53 geçti**, 5 test dosyası |
| Frontend `npm run build` | Başarılı |
| `uv lock --check --offline` (erişilebilir ayrı cache ve mevcut Python ile) | Başarılı; kilit dosyası değiştirilmedi |
| 190 kopya dosyada belirli API anahtarı/özel anahtar biçimleri ve yereldeki mevcut sır değerleri taraması | Eşleşme bulunmadı; kapsamlı güvenlik denetimi değildir |

Backend birim testleri mevcut Python 3.14.3 ortamının kurulu bağımlılıklarıyla çalıştırıldı; kendi veritabanına/LLM'e yönelmemesi için geçersiz yerel test adresleri kullanıldı. Sıfırdan backend bağımlılık kurulumu yapılmadı. Python/Pydantic uyumluluk uyarısı ve frontend paket boyutu/deprecation uyarıları alındı; komutlar başarılı tamamlandı.

## Henüz doğrulanmayanlar

- Ekip arkadaşının sıfırdan kurulmuş bilgisayarında uçtan uca açılış.
- Yeni boş PostgreSQL üzerinde kurulum/kayıt/giriş ve gerçek Groq sohbeti.
- DrugBank verisinin başka bilgisayara aktarılması ve gerçek verili ilaç sorguları.
- Tüm backend entegrasyon testleri ve klinik doğruluk.

Bunlar bu dalın ekip tarafından denenme amacıdır. Birim testleri ve derleme başarısı tam ürün/klinik kabul anlamına gelmez. İlaç verisi ayrıca yüklenmediyse boş sonuç beklenir.
