# M-02 — Astra uygulama teslimi ve Claude bağımsız denetimi

Tarih: 27 Kasım 2026. Görev sahibi: Onur Kılıç. Bu görevde uygulayıcı: Astra.
**Bağımsız denetçi: Claude; henüz denetim yapmadı. Uzman kabulü yapılmadı.**

## 1. Kapsam ve gerçek durum

Önceden yalnız compare API'si vardı; D3 yanlış ilaç aidiyeti açıktı. Bu teslim,
M-02'nin bağımsız ekranını, aramasını, ortak süre çizelgesini, kaynak kartlarını,
ürün/koşul eşleşmesine bağlı zamanlama önerilerini ve D3 bağlam düzeltmesini ekler.
Mevcut sohbet ajanı/C1, hasta ekranı, doz hesabı veya başka MVP geliştirilmedi.

Başlangıçta okunan kaynaklar: güncel `STATUS.md`, `timing/RULES.md`, `API.md`,
ilgili kod/testler, `MedicaLLM_M02_O1_Denetim.md` üstteki R7 kararı ve
`SDP_Project_Forms_Enhanced_Medikallm.docx.pdf` (M-02, sayfa 5).
Form A imzasız “Before Edit With Client” taslağıdır. Eski R8 parser-only sınırını
bu göreve taşımayan, kullanıcının açık yeni M-02 tamamlama yetkisidir.

**Teslim kararı: doğrulama ve GitHub'a aktarım engelli.** Yerel kod, 1444 testlik
katı backend/PostgreSQL kontrolü ve 64 frontend testi hazır. Birleşik HTTP akışı
ve yeni sürüm CI sonucu aşağıda ayrı kaydedilir; başarılı kabul edilmez.
Kod mevcut taslak PR'a henüz aktarılmadı. Bu rapor ve değişiklik paketi yerel
çalışma ağacını tarif eder; uzak `c0910da` commit'inin bu özellikleri içerdiğini
iddia etmez.
Görsel tarayıcı kabulü, gerçek DrugBank kapsamı ve uzman değerlendirmesi yapılmış
sayılmaz. Bu rapor bağımsız teknik kabul kararı değildir.

## 2. Sürüm ve erişim kaydı

| Alan | Değer |
|---|---|
| Depo / PR | [onurkilicce-ops/MedikaLLM #5](https://github.com/onurkilicce-ops/MedikaLLM/pull/5), açık taslak |
| Görev dalı | `feat/onur/m02-timing` |
| Başlangıç tam SHA | `c0910da6657c50bbed526f7a19c8a65540d9fa50` |
| Hedef dal | `team-test/2026-11-23-stage-0-1` |
| Doğrulanan base SHA | `c86dcc121047fe94a87b38245e8f467045afdb07` |
| Son uygulama commit SHA | **Oluşturulamadı.** Kod, yukarıdaki başlangıcın üzerindeki yerel/stage edilmiş değişikliklerdir; başlangıç SHA'sı teslim SHA'sı değildir. |
| Uzak PR head (27 Kasım kontrolü) | `c0910da6657c50bbed526f7a19c8a65540d9fa50`; yeni kod gönderilmedi |
| CI / checkout SHA | **Yeni sürüm yok; CI çalıştırılamadı.** Eski R7 CI'ı bu teslimin kanıtı değildir. |
| Yerel teslim kimliği | Paketteki `manifest.json`: başlangıç SHA, staged Git tree SHA, değişen her dosyanın SHA-256'sı ve patch SHA-256'sı |

Çalışma kopyası `Documents/ChatGPT/Medikallm/m02-work` altında izole edildi.
Eski masaüstü proje ağaçlarına yazılmadı. PR #1/#3 ve diğer ekip dalları değişmedi.
Başlangıç kontrolünde uzak head/base yukarıdaki SHA'larla aynıydı. Geçmiş R7
yeşil CI sonucu yeni kod için kullanılmadı. `AGENTS.md`'de ek kod talimatı yoktu.

## 3. Gereksinim bazında kabul tablosu

| Gereksinim | Önce / yapılan iş | Doğrulama ve sınır |
|---|---|---|
| Yetkili profesyonel 2–10 ilaç seçer | Bağımsız `/timing` ekranı ve salt okunur isim/eş ad/kimlik araması | Frontend testleri; 2–10/401/403/422/503 backend regresyonları; yeni PG testi |
| Tmax, yarı ömür ve uygun 5× ortak eksende | Aralık/sınır/± ve koşulları ayrı satırlar, doğrusal/log ölçek | `Timeline`, frontend testleri; süre hesapları eski backend suite |
| Doğru ilaç ve kaynak | D3 bağlamı korunur; kaynak alıntısı/konumu, saklı referans ve yakındaki belirteç ayrımı | 13 olumsuz + 8 olumlu HTTP; yeni 10 sınır; eski D4 kontrolleri |
| Belirsizlik ve eksik veri | İnceleme değerleri çizilmez; metin ve gerekçe kartta, eksik sıfır olmaz | Frontend birim ve birleşik akış senaryoları |
| Kaynaklı ilaç–ilaç önerisi | Açık ürün profiliyle iki asimetrik yön | `test_m02_advice.py`, SOURCES.md; uzman kabulü değil |
| Kaynaklı ilaç–gıda önerisi | Öğün dışı süt ürünü/içecek ve kahvaltı; öğün istisnası | Aynı testler; ters yön uydurulmuyor |
| Kanıt yok / koşul eksik / teknik hata ayrımı | Coverage satırları ve ayrı advice hata alanı | Backend ve frontend olumsuz testleri |
| Gerçek backend → API → ekran | React DOM'dan gerçek HTTP ve PG'ye opt-in test | Çalıştırılma durumu bölüm 7; jsdom görsel tarayıcı değildir |
| Tam regresyon / son SHA CI | Mevcut katı suite + yeni M-02 akış adımı | Sonuç bölüm 7; eski yeşil koşu kabul edilmez |
| En az %90 kaynak/uzman uyumu | Hedef korunuyor; aday küme ve kayıt yöntemi hazır | **Ölçülmedi**; `M02_Uzman_Kabul.md`, uzman onayı bekliyor |

## 4. Dosyalar ve kararlar

- `backend/src/timing/parser.py`: sayı penceresi dışında kaybolan özne bağlamı;
  parser `/8` → `/9`. Genel NLP veya LLM eklenmedi.
- `advice.py`, `advice_models.py`: küçük, sürümlü birincil kaynak kataloğu ve
  ürün/koşul sözleşmesi. PK hesabından klinik ara üretmez.
- `repository.py`, `router.py`: `GET /api/timing/drugs` ve
  `POST /api/timing/advice`. Mevcut profesyonel yetkisi ve `READ ONLY` işlemi;
  SQL hatası 503, boş veriyle karışmaz.
- `models.py`: compare içindeki `not_evaluated` açıklaması ayrı advice ucunu
  gösterir. Compare veri şekli `m02-timing-compare/2` olarak korunur.
- `frontend/src/timing/**`: seçim, ortak çizelge, kaynaklar, ürün/öğün koşulları,
  hata/belirsizlik, yüklenme ve eski yanıtı geçersizleştirme. Seçim değişince
  önceki yanıt iptal edilir; başka seçim altında görünmez. Türkçe bağımsız ekran.
- Ortak frontend değişikliği: `main.jsx` iki satır route/import;
  `pages/Chat.jsx` yalnız dört satır hekim menü bağlantısı. Halil'in sohbet/hasta
  mantığı ve ortak API istemcisi/stil/çeviri dosyaları yeniden yazılmadı.
- Yeni testler: `test_m02_ownership_completion.py`, `test_m02_advice.py`,
  `test_m02_completion_pg.py`, `TimingPage.test.jsx`, `e2e/timing.flow.jsx`.
- Üç eski testte yalnız parser sürümü `/9`; davranış eşiği gevşetilmedi.
  Önceden sabitlenmiş 94 örnek değiştirilmedi.
- `scripts/m02_synthetic_demo.py`: yalnız açıkça onaylanan ayrı `_synth` DB için
  seed/yerel sunucu. Gerçek router/auth/SQL; LLM ve başlangıç işleri kapalı.
- `.github/workflows/ci.yml`: mevcut geçici PG hizmetinden yararlanarak React
  DOM → gerçek API → PG kontrolü. Yeni paket/servis veya ücretli hizmet yok.
- README, API/RULES/SOURCES, bu rapor, uzman aday kümesi ve STATUS güncellendi.

Şema, migration, mevcut veriler, `pyproject.toml`, `uv.lock`, `package.json`,
`package-lock.json`, auth, ajan/C1 değişmedi. Üretim isteği hiçbir kayıt yazmaz.
Advice sözleşmesi `m02-timing-advice/1`; kaynak kimliği/metni/yön/koşul gelecekte
C1/M-06'ya eşlenebilir, entegrasyon yapılmış gibi gösterilmez.

## 5. D3: kök neden, karar sınırı ve sonuç

Kök neden: eski kod değerin dar penceresindeki adayları incelerken virgüllü
açıklama, parantez, başlık veya önceki cümle gerçek özneyi pencerenin dışına
taşıyordu. Boş aday listesi genel/kayıt ilacı varsayımına dönebiliyordu.

Yeni sınır: açık özne kayıt adıyla eşleşmeli; genel veya basit PK ifadesi
kayda ait alan bağlamında ve desteklenen cümle yapısında kalmalı. Öncesindeki
çözülemeyen/yabancı konu bu bağlamı geçersiz kılar. Genel özne, önceki yabancı
özneyi kendiliğinden sıfırlamaz. Açık kayıt eşleşmesi sıfırlayabilir. Olumsuzluk,
koşul, alıntı konumu ve kaynak sınırlarının eski kontrolleri ayrıca devam eder.

13 olumsuz örnek `c0910da` üzerinde yeniden üretildi. Aşağıdaki sonuçlar yeni
sürümde gerçek router → JWT/yetki → servis → JSON yolundandır; bu yerel koşuda
yalnız repository okumaları sentetik satırlarla değiştirildi. **PG kanıtı değildir.**

| No | Yapı (kayıt Drug A) | Yeni sonuç |
|---|---|---|
| 1 | `drug b, a synthetic agent, has a half-life ...` | Aidiyet çözülemedi, ölçüm/5× yok |
| 2 | `drug b, given orally, has a half-life ...` | Aynı |
| 3 | `The tablet (drug b) has a half-life ...` | Aynı |
| 4 | `For the tablet (drug b), ...` | Aynı |
| 5 | `The tablet, which contains drug b, ...` | Aynı |
| 6 | `The formulation of drug b was studied and it ...` | Aynı |
| 7 | `The formulation of drug b was studied. Its ...` | Aynı |
| 8 | `Regarding drug b, ...` | Aynı |
| 9 | `As for drug b, ...` | Aynı |
| 10 | `drug b: the half-life ...` | Aynı |
| 11 | `drug b half-life ...` | Aynı |
| 12 | `Regarding drug b, Tmax ...` | Aidiyet çözülemedi, Tmax ölçümü yok |
| 13 | `drug b, a synthetic agent, has a Tmax ...` | Aynı |

Tam metinler yeni unit testinde sabittir. Her olumsuzda kaynak alıntısı/konumu ve
`subject_unresolved` korunur. **13 yanlış temiz sonuç → 0; 13 çekimser sonuç.**

Sekiz olumlu: Drug A + açıklama; Drug A + oral açıklama; “the drug” + renal
yan cümle; tablet + oral parantez; sağlıklı yetişkin `(n=12)`; basit yarı ömür;
`For 20% drug a`; doğrudan Drug A. **8/8 temiz 4 saat ve 20 saat 5× korundu**;
yanlış temiz veya gereksiz çekimser sonuç yok. Ek 10 sınır örneği beklentileri
uygulamadan önce yazıldı. Bunlar seçilmiş sentetik sayılardır, klinik oran değil.

## 6. Başlatma ve ekran denemesi

README'deki **M-02 ekranı** bölümünü izleyin. Gerekenler: kilitli bağımlılıklar,
ayrı yerel `_synth` PostgreSQL ve `vector`/`pg_trgm`; hiçbir gerçek ilaç verisi,
hasta veya API anahtarı gerekmez. Test metinlerinin ve demo kimlik eşlemesinin
sentetik olduğu ekranda ve betikte açıkça belirtilir.

Beklenen akış: sentetik hekimle giriş → iki ilaç seç → karşılaştır → aralıklar ve
ayrı 5× → kaynak kartı → ürün koşullarını doğrula → iki yönlü kaynaklı öneri.
Ardından ilaç–gıda/öğün koşulunu değiştir; eski sonuç temizlenmeli. Uncertain
agent ve Empty agent seçiminde yanlış ölçüm yerine inceleme/eksik veri görülmeli.
Hasta hesabı 403, bozuk token 401; backend kesilirse hata görünmeli.

`npm test` HTTP'yi taklit eden UI testidir. `npx vitest run --config
vite.m02.config.js` ayrı sentetik sunucu açıkken **gerçek HTTP/PG** kullanır.
Her ikisi de jsdom'dur; görünür tarayıcı, CSS yerleşimi ve gerçek tarayıcı CORS
uygulaması bunlarla doğrulanmış sayılmaz.

## 7. Gerçek kontroller ve çalıştırılmayanlar

| Kontrol | Gerçek sonuç |
|---|---|
| Backend `python -m pytest tests/unit -q --tb=short -p no:cacheprovider` | **1213 geçti**; yerel mevcut venv, gerçek paketler |
| M-02 unit alt kümesi | **1040 geçti**; sonrasında tam unit suite yukarıda |
| D3 13+8 HTTP kontrolü | **21/21**; repository ikamesi, PG değil |
| Frontend `npm test` | **64 geçti**, 6 dosya; 53 eski + 11 yeni. 27 Kasım'da aynı `vitest run` komutu yeniden başarılı (5,94 s) |
| Frontend `npm run build` | 27 Kasım'da aynı `vite build` yeniden başarılı (1,44 s); mevcut büyük bundle uyarısı engelleyici değil |
| Katı tam backend + ayrı PostgreSQL | **1444 geçti**, 0 atlandı, 72,34 s; kesintiden önce tamamlanan `astra_strict_pg2.txt` kaydı 27 Kasım'da okundu |
| React DOM → gerçek HTTP → ayrı PostgreSQL | 27 Kasım yerel denemesi **6 başarısız**: `connect EACCES 127.0.0.1:18102`; bu oturumun bağlantı kısıtı. Başarılı akış sayılmadı; kod yüklendikten sonra CI'da ayrıca çalıştırılmalı |
| Son commit GitHub CI | **Çalıştırılamadı**: GitHub tree yazması 403; yerel commit de çalıştırma izninde durdu. Yeni commit ve yeni CI sonucu yok |

İlk tam unit koşusunda 1 test, ortamın SOCKS proxy ayarı ve eksik `socksio`
nedeniyle başarısızdı (1212 geçti). Yalnız test sürecindeki proxy değişkenleri
kaldırıldı; uygulama/dependency değiştirilmeden 1213 geçti. Tiktoken önbelleği
mevcut kamusal tokenizer verisiyle sağlandı; LLM URL'si kapalı yerel porta ayarlandı.
Yerel frontend bağımlılıkları aynı kilit dosyasına sahip mevcut kurulumdan alındı;
bu, temiz `npm ci` kanıtı olarak sunulmaz. Temiz kilitli kurulum CI'da aranmalıdır.

**Çalıştırılmayanlar:** gerçek DrugBank envanteri/doğruluk oranı (küme açılmadı),
ücretli/canlı LLM (M-02 gerektirmez), görünür tarayıcı kabulü ve uzman değerlendirmesi.
Bu oturumda bağlı tarayıcı denetimi bulunmadığından görsel doğrulama engellidir.
Önceki oturumda GitHub yazma bağlantısı 403 vermişti. 27 Kasım'da PR tekrar
okundu: head/base değişmemiş, açık ve taslak. Yeni dosya ağacını yazma denemesi
tekrar `403 Resource not accessible by integration` döndü; uzak depo değişmedi.
Yerel `git commit` ise Git'in `sh.exe` sürecindeki `NtCreateDirectoryObject`
`0xC0000022` hatasında durdu. Commit oluşmadı ve buna bağlı push adımı
çalıştırılmadı. Çalışma dosyaları ve Git index'i korundu; force push veya merge yok.
Yerel HTTP denemesindeki altı başarısızlık rapordan çıkarılmadı; bağlantı
kurulamadığından uygulama davranışının geçtiğini veya bozulduğunu kanıtlamaz.
Başarılı PostgreSQL koşusunun kodu ile bu oturum başındaki kod aynıydı;
çalışma ağacındaki bekleyen ek farklar README/API açıklaması ve iki UI testiydi.

Yerel test komutları:

```powershell
# backend/: yalnız ayrı, adı onaylanmış sentetik PostgreSQL ile
$env:MEDICALLM_STRICT_TESTS = "1"
# MEDICALLM_SYNTHETIC_PG_URL ve MEDICALLM_SYNTHETIC_PG_CONFIRM aynı ayrı DB'yi göstermeli.
python -m pytest tests -p no:cacheprovider -q --tb=short -ra
# frontend/: kurulu ve kilit dosyasıyla eşleşen bağımlılıklarla
.\node_modules\.bin\vitest.cmd run
.\node_modules\.bin\vite.cmd build
.\node_modules\.bin\vitest.cmd run --config vite.m02.config.js
```

Son üç komut devam oturumunda doğrudan çalıştırıldı. İlk komutun başarılı
sonucu kesintiden önceki kayıttandır; bu oturumda PostgreSQL'e yeniden
bağlanılmış gibi sunulmaz. Tekrar kurulumu için README ve CI'daki tüm ortam
değişkenleri esas alınmalı; gerçek uygulama veritabanına yönlendirilmemeli.

## 8. Zamanlama önerilerinin kanıtı

Tam kaynak/ürün/bölüm ve kontrol yöntemi [SOURCES.md](../backend/src/timing/SOURCES.md).
Üç birincil etiket gerçekten açıldı: emc 4346 §4.5, emc 885 §4.5/4.2 ve DailyMed
levotiroksin §2.1. Aynı bölümler 27 Kasım devam oturumunda tekrar doğrulandı.
API özgün kısa alıntıyı, bölüm/URL ve ilk kontrol tarihini döndürür.
Profil bilinmiyorsa süre üretilmez; seçilen profil sunucuda kayıt adına karşı
denetlenir. UK/US ürünü Türkiye ürünüyle otomatik eşdeğer sayılmaz.
Katalogda olmayan çiftte kanıt bulunamadığı belirtilir, güvenlik sonucu çıkarılmaz.
Tam metin yön anlatımı sorunlu bir US ciprofloxacin etiketi dışarıda bırakıldı.

## 9. Açık işler ve sınırlar

- **Teslim doğrulaması için gerekli:** yeni commit CI sonucu ve gerçek API'li
  UI akışı; yerelde katı PostgreSQL geçti, birleşik akış bağlantı kısıtında kaldı.
- **Aktarım engeli:** GitHub bağlantısının bu depoda içerik yazma yetkisi yok
  (403); yerel Git commit'i de oturumun süreç izninde durdu. Kod yalnız yerelde.
  Erişim düzelmeden PR'da yeni kod varmış gibi denetim yapılmamalı.
- **Doğrulama engeli:** görünür tarayıcı aracı yok; README akışı tarayıcıda
  ayrıca denenmeli. jsdom sonucu bunun yerine yazılmaz.
- **Bağımsız kabul bekliyor:** Claude bu raporu kanıt saymadan kodu incelemeli.
- **Uzman kabulü bekliyor:** ≥%90 hedefi ölçülmedi. Aday küme, sabitleme ve kayıt
  şablonu `M02_Uzman_Kabul.md`; uzman onaylı referans kümesi yok.
- Gerçek veri kapsamı yeni parser için sayılmadı; geçmiş sayılar aktarılmadı.
- Ayrıştırıcı sınırlı kurallardır; genel marka/eş ad/uzak bağlam NLP'si değildir.
  Her bilinmeyen dil yapısını doğru çözdüğü iddia edilmez.
- Engellemeyen takip: M02-N1 parantez içi atıf çekimserliği ve çift tireli aralık;
  temiz kesin değer üretmek yerine incelemeye bırakma korunur.
- Katalog küçüktür, kapsam dışı çiftler gerçek eksiktir; boş öneri tüm klinik
  literatürde etkileşim yokluğu veya güvenli kullanım anlamına gelmez.

## 10. Ekip etkisi ve geri alma

Onur: M-02 ekranı ve servisleri. Kadir'in ajan/C1 dosyaları değişmedi. Halil için
entegrasyon notu: yalnız ortak route ve hekim menüsüne küçük bağlantı eklendi;
eşzamanlı menü düzenlemesi varsa bu iki değişikliğin amacı korunmalı. Shared
model/migration, ortak frontend istemci/stil/çeviri veya bağımlılık değişikliği yok.

PR taslak kalır; merge/auto-merge/main push yapılmaz. Birleştirme gerekiyorsa
önce Claude teknik denetimi, sonra entegrasyon dalında birlikte kontrol gerekir.
Bu teslim henüz commit edilmedi; yerel değişiklikler yedeklenmeden silinmemeli.
İleride commit edilirse geri alma ayrı revert PR'ıdır; veri/migration geri alma
gerekmez. Test seed'i sadece seçilen ayrı sentetik veritabanını etkiler.

### Yerel paketi kullanma

`MedicaLLM_M02_Teslim_Paketi.zip` değişen 31 dosyayı `changed-files/` altında,
birleşik `MedicaLLM_M02.patch` dosyasını, manifesti ve gerçek test kayıtlarını
içerir. Paket, bağımlılık veya gerçek ilaç/hasta verisi içermez. Başlangıcı tam
`c0910da6657c50bbed526f7a19c8a65540d9fa50` olan temiz, ayrı bir kopyada
önce `git apply --check MedicaLLM_M02.patch`, sonra `git apply MedicaLLM_M02.patch`
uygulanabilir. Halihazırda değişikliklerin bulunduğu `m02-work` üzerine tekrar
uygulanmaz. Farklı/ilerlemiş dalda körlemesine uygulanmaz; diff incelenir.
Bu işlem commit/push/merge yapmaz. Sonraki adım yetkili dalda commit/push,
yeni CI ve gerçek tarayıcı kontrolüdür.

## BAĞIMSIZ DENETİM GÖREVİ

Claude, MedicaLLM M-02'nin bağımsız teknik denetçisisin. Astra bu görevde kodu
uyguladı; raporunu doğru varsayma. Depo `onurkilicce-ops/MedikaLLM`, taslak PR #5,
görev dalı `feat/onur/m02-timing`, hedef `team-test/2026-11-23-stage-0-1`.
**Mevcut teslim yereldir:** PR henüz eski `c0910da` kodunu taşıyor. Paketin
manifesti ve patch'i ya da `m02-work` çalışma ağacı olmadan yeni teslimi
denetlemiş sayılmazsın. Uzak PR'ı yeni uygulamayla karıştırma.

1. AGENTS, `git status`, yerel/uzak head ve base'i kontrol et. Bu rapordaki
   uygulama SHA'sı ve PR'ın son SHA'sı farklıysa farkı incele; eski CI'ı yeni
   sürüme mal etme. Başlangıç `c0910da6657c50bbed526f7a19c8a65540d9fa50`.
2. Formun M-02 maddesini, güncel STATUS, bu rapor, API/RULES/SOURCES ve gerçek
   diff'i oku. Tarihsel bulguları güncel hata gibi sunma. Bu tur yalnız parser
   değil, M-02 ekranı ve kaynaklı öneri akışını da içerir.
3. Kabul tablosundaki kritik kontrolleri bağımsız çalıştır. Özellikle 13 yabancı
   aidiyet ve 8 olumlu örnek, kaynak bağlama, aralık/±/koşul koruma, inceleme
   değerinden 5× üretmeme, zaman başlangıcı, yöndeki asimetri ve ürün eşleşmesi.
4. Üç kaynak sayfasını gerçekten aç; sayı, yön, ürün/formülasyon/öğün koşulunu
   koddaki kuralla karşılaştır. Kaynak yokluğunu güvenli kullanım sanma.
5. Gerçek router → kimlik/yetki → servis → JSON ve ayrı sentetik PG yolunu
   kontrol et. Mock/repository ikamesini PG kanıtı sayma. Gerçek DrugBank
   kümesini başlatma/değiştirme; lisanslı metin veya sır paylaşma.
6. README akışını mümkünse görünür tarayıcıda uygula: iki ilaç, ekle/çıkar,
   kaynak açma, eksik ve belirsiz veri, yüklenme/hata, 401/403 ve kaynaklı/kanıtsız
   öneri. DOM testini görsel tarayıcı kabulü diye sunma. Erişim engelini belirt.
7. Eski 94 sabit örnek, ilgili regresyonlar, tam katı suite, frontend test/derleme
   ve SON commit CI'ını incele. Test beklentileri geçsin diye gevşetilmesin.
8. Her bulguya tekrar adımı, beklenen/gerçek sonuç, önem ve dosya/konum kanıtı
   ekle. Yeni özellik veya kişisel mimari tercihini kabul engeline dönüştürme.
9. **İlk denetimde kod değiştirme.** Kanıta göre “Teknik kabul”, “Düzeltme gerekli”
   veya “Doğrulama engelli” kararı ver. Merge yapma. Kod denetimi uzman/klinik
   kabulünü ve formdaki ≥%90 hedefini tamamlamaz.
