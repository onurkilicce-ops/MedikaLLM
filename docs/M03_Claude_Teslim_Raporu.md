# M-03 — Organlar, enzimler ve taşıyıcılar: teslim raporu (Astra kontrolü için)

**Durum: M-03 ilk sürümü uygulandı, sentetik PostgreSQL üzerinde baştan sona sınandı ve
`feat/onur/m03-mechanism` dalına gönderildi. Teknik kabul Astra'nın bu rapordaki
kontrollerine, klinik kabul Form A ≥%90 uzman kabulüne bırakılmıştır. İkisi de
yapılmadı.**

- Tarih: 28 Kasım 2026
- Uygulayıcı: Claude (Onur Kılıç adına; git kimliği `onur kılıç`)
- Kontrol eden: Astra
- Kapsam: Form A M-03 metni. Bir profesyonel bir ilacın profilini açar ve şunları görür:
  - ilacı hangi organların temizlediği;
  - hangi enzim ve taşıyıcıların ilacı kullandığı, yavaşlattığı ya da hızlandırdığı;
  - iki ilaç aynı proteine dayanıyorsa etkileşimin o protein üzerinden açıklaması.

## 1. Sürüm

| Alan | Değer |
|---|---|
| Depo | `onurkilicce-ops/MedikaLLM` |
| Dal | `feat/onur/m03-mechanism`. M-02 dalının (`feat/onur/m02-timing`, PR #5, `85ad173`) üzerine kuruldu; M-02 birleştirilmeden birleştirilemez |
| Commit | bkz. `git log 85ad173..feat/onur/m03-mechanism` |
| Kullanıcı kararları | Dal M-02'nin üzerine kuruldu. M-03, M-02 ile **aynı ekranda** (`/timing`) gösterilir; ikisi birbirini tamamlar |

## 2. Ne yapıldı

**Backend** (`backend/src/mechanism/`, yeni paket):
- `POST /api/mechanism/compare`: 1–10 DrugBank kimliği alır; salt okunur çalışır; LLM ve
  dış kaynak çağırmaz.
- Erişim: M-02 ile aynı Bearer token ve doktor profili kontrolü. Veritabanı okunamazsa
  M-03'e özgü 503 döner.
- Okunan veriler, `READ ONLY` işlemde:
  - `drug_enzymes`, `drug_transporters`, `drug_carriers`;
  - `drugs.route_of_elimination`, `metabolism`, `clearance`;
  - istenen ilaçlar arasındaki `drug_interactions`.
- `main.py`'ye yalnız router kaydı eklendi (M-02 ile aynı biçimde).
- Şema, migration ve bağımlılık değişmedi.

**Kurallar** (`rules.py`, saf işlevler; ayrıntı [RULES.md](../backend/src/mechanism/RULES.md)):
- **Protein rolleri.** DrugBank `actions` alanı substrat, inhibitör (`inactivator`
  dahil), indükleyici ve "başka" olarak okunur. Ham metin ve `known_action` her zaman
  yanında gösterilir.
- **Organ yolları.** Serbest metinde organ sözcüğü yalnız bir *atılım yolu bölümünde*
  geçiyorsa sayılır. Her ifade birebir alıntı ve konumla döner.
  - **Organa yüzde/pay atanmaz.** İnceleme, yüzdenin yanlış organa bağlandığını gösterdi
    (`respectively`, `95% protein bound`).
  - Olumsuz/küçük pay, belirsiz, yalnız hasta durumu ya da başka konu olabilecek
    ifadeler işaretlenir.
  - Ekran işaretli ifadeleri temizleyen organ listesinden ayrı gösterir.
- **Çift açıklaması.** Açıklama yalnız aynı, tanımlanabilir insan proteini için yapılır.
  - Etken inhibitör, kurban substrat → "A, B'yi işleyen enzimi yavaşlatır; B kanda
    birikebilir".
  - İndükleyici → "daha hızlı temizlenebilir".
  - Taşıyıcıda yönün proteine bağlı olduğu yazılır. Plazma bağlanma proteini için yön
    verilmez.
  - Ortak substrat zayıf kanıttır.
  - İnhibitör+indükleyici çelişkisi "yön belirlenemez" olarak gösterilir.
  - Her açıklamanın uyarıları vardır: ön ilaç tersine döner, güç belirtilmemiş, başka
    yollar dengeleyebilir …
  - DrugBank'in kendi etkileşim metni ayrı kanıt olarak gösterilir.
  - Ortak protein yokluğu "etkileşim yok" anlamına gelmez; ekran bunu açıkça söyler.

**Ekran** (`frontend/src/timing/Mechanism.jsx`, `TimingPage.jsx`):
- M-02 karşılaştırmasının altında "Organlar, enzimler ve taşıyıcılar (M-03)" bölümü yer
  alır.
- M-03 isteği M-02'den bağımsızdır: M-02 sonuçlarını beklemez ve geciktirmez. M-03
  hatası, M-02 bölümlerinin yanında ayrı bir teknik hata olarak görünür.
- Tek ilaç seçiliyken "Organ ve protein profilini göster (M-03)" düğmesi var.
- Türkçe metinler; `known_action` "ilacın kendi etki mekanizmasının parçası mı" olarak
  açıklanır.
- Paylaşılan sohbet ekranı (`Chat.jsx`) değişmedi.

## 3. Çekişmeli inceleme

Beş tur bağımsız çekişmeli inceleme yapıldı. Her bulgu çalıştırılarak yeniden
üretilmeden sayılmadı. Bulunan ve düzeltilen örnekler:

| Tur | Bulgu | Engelleyici | Başlıca konu |
|---|---|---|---|
| 1 | 26 | 2 | Yol olmayan organ sözcükleri (`liver enzymes increased`); başka ilacın yolu |
| 2 | 25 | 2 | Yüzdenin yanlış organa bağlanması → **pay tamamen kaldırıldı** |
| 3 | 22 | 1 | `non-renal`, `extra-hepatic` |
| 4 | ≈18 | 1 | Benim 3. turda eklediğim `significant`/`depend` hatası (reddetmeler olumlu görünüyordu) |
| 5 (yalnız engelleyici) | 9 | 9 | Sözcükle reddetme (`without`, `rather than`, `absent`, `undetectable`, `unlikely`, `zero`, `escapes` …). Çift açıklamalarında yön/ilaç hatası bulunmadı |

Her bulgunun girdisi `tests/unit/test_m03_rules.py` içinde regresyon testidir (182
test). **5. tur da bulgu üretti.** Serbest metinden organ çıkarma uzun kuyruklu bir
sorundur. Kalan riskler §5'tedir.

## 4. Doğrulama

| Kontrol | Sonuç |
|---|---|
| M-03 birim testleri (`test_m03_rules.py`) | 182 geçti |
| M-03 HTTP → yetki → servis → sentetik PG (`test_m03_mechanism_api_pg.py`) | 17 geçti. Kapsam: 200, 401, 403 ×2, 422 ×6, 503 ×2 (ayrıntı sızdırmaz), salt okunur (5 tablonun md5'i değişmez), sınırlar |
| Katı tam paket (`MEDICALLM_STRICT_TESTS=1`, ayrı sentetik PG) | **1718 geçti, 0 atlandı** (M-02 dahil) |
| Frontend testleri | 80 geçti (M-03 için 9 bileşen + 5 sayfa testi) |
| Frontend derleme | başarılı |
| Canlı akış: React DOM → gerçek fetch → yetki → servis → sentetik PG (`vite.m02.config.js`) | 8/8 geçti. 2 M-03 testi: iki ilaçlı açıklama ve tek ilaç profili |
| Tarayıcı görsel kontrolü | Sentetik doktor hesabıyla `/timing`: organ alıntıları, protein tablosu, "Ciprofloxacin … CYP1A2 enzimini yavaşlatır … kanda birikebilir" görüldü |
| GitHub CI | bkz. PR/dal sayfası (push sonrası) |

Gerçek DrugBank kümesi başlatılmadı, okunmadı, değiştirilmedi. Tüm test metinleri ve
protein kayıtları `[SYNTHETIC]` etiketlidir. Lisanslı metin, anahtar veya hasta verisi
Git'e ya da bu rapora girmedi.

## 5. Bilinen sınırlar (Astra'nın bilmesi gerekir)

1. **Organ çıkarımı kural tabanlıdır.** Beş turdan sonra da yeni reddetme kalıpları
   bulunabilir. Her organ ifadesi birebir alıntıyla gösterilir; okuyucu alıntıyı
   okumalıdır. Bu, uzman kabulünde ve gerçek veri kapsam incelemesinde ayrıca
   ölçülmelidir.
2. **Ad tanıma yok.** Organ cümlesinde kodsuz gerçek bir başka ilaç adı geçiyorsa
   (`Ritonavir is renally excreted`) işaretlenmez. Yalnız karşılaştırma, kodlu ürün ve
   hayvan çalışması kalıpları işaretlenir.
3. **Pay yok.** Organ payları yapılandırılmaz.
4. **Protein kapsamı DrugBank kaydıyla sınırlıdır.** Eksik kayıt "kullanmıyor" demek
   değildir. `known_action` çoğu metabolizma kaydında `unknown`/`no`'dur ve "etkilemez"
   anlamına gelmez.
5. **Klinik derece yok.** Önem, doz önerisi ya da enzim payı türetilmez.
6. **Gerçek veriyle ölçüm yapılmadı.** Gerçek DrugBank metinlerinde organ ifadelerinin
   doğruluk oranı bilinmiyor.

## 6. Astra için kontrol listesi

1. `git log --oneline 85ad173..origin/feat/onur/m03-mechanism`.
   `git diff 85ad173 origin/feat/onur/m03-mechanism --stat` yalnız şunları göstermeli:
   - `backend/src/mechanism/*`, `backend/src/main.py` (2 satır);
   - `backend/tests/unit/test_m03_rules.py`,
     `backend/tests/integration/test_m03_mechanism_api_pg.py`;
   - `backend/scripts/m02_synthetic_demo.py` (sentetik M-03 tohumu);
   - `frontend/src/timing/*`, `frontend/e2e/timing.flow.jsx`;
   - `README.md`, `STATUS.md`, bu rapor.

   M-02 testlerinde yalnız M-03 isteğini taklit eden `vi.mock` satırı ve iki yeni
   `describe` bloğu eklendi; mevcut beklentiler değişmedi.
2. Kendi cümlelerinle `rules.organ_mentions(...)` dene. Özellikle şunlara bak:
   - reddetme, karşıtlık ve koşul cümleleri;
   - laboratuvar ve yan etki sözcükleri;
   - uzun cümleler.

   Ölçüt: temizleyen organ listesinde **işaretsiz** görünen yanlış bir organ
   engelleyicidir.
3. `rules.explain_pair(...)` ile yön, kimlik eşleşmesi (BE kimliği / ad / kimliksiz
   kayıt), insan dışı türler ve çelişkili kayıtları dene.
4. Ekranda tek ilaç profilini, iki ilaçlı açıklamayı ve M-03 hatasının M-02'yi
   etkilemediğini kontrol et.
5. Gerçek DrugBank verisiyle bir örneklem kapsam incelemesi ve Form A uzman kabulü
   planla. Bu teslim ikisini de iddia etmez.
