# M-03 kuralları (`m03-mechanism-rules/1`)

Kurallar saf işlevlerdir (`rules.py`): veritabanı, LLM veya ilaç adı tanıma yoktur.
Her çıktı DrugBank'in saklı kaydına dayanır ve kaynağıyla (ham eylem metni ya da
birebir cümle) birlikte döner. Kurallar iki çekişmeli inceleme turunda bulunan
örneklerle sınandı (`tests/unit/test_m03_rules.py`).

## 1. Protein rolleri

DrugBank her enzim, taşıyıcı ve taşıyıcı protein kaydı için bir eylem listesi tutar
(`actions`, ör. `substrate, inhibitor`).

- Liste `,`, `;` ve `/` ile bölünür; büyük/küçük harf ve boşluk önemsenmez.
- `substrate` → kullanır, `inhibitor` → yavaşlatır, `inducer` → hızlandırır.
- `inactivator` (mekanizmaya dayalı inaktivasyon) yavaşlatma olarak `inhibitor` sayılır.
  Ham sözcük her zaman yanında gösterilir.
- Başka her sözcük `other` olur. `negative modulator`, `downregulator`, `binder`,
  `carrier`, `agonist` gibi sözcüklerden bilerek yön çıkarılmaz.
- `known_action` (`yes` / `no` / `unknown`) ve enzimdeki güç alanları kayıttaki gibi
  aktarılır; yorumlanmaz.

## 2. Organ yolları

`route_of_elimination`, `metabolism` ve `clearance` metinleri cümlelere bölünür.

- Bölme `.`, `;` ve satır sonuyla yapılır.
- Yalnız iki rakam **arasındaki** nokta (`2.5 h`) cümle bitirmez. `CYP3A4.` cümle
  bitirir.
- Yaygın kısaltmalar da cümle bitirmez: `approx.`, `i.v.`, `i.m.`, `s.c.`, `p.o.`,
  `e.g.`, `i.e.`, `ca.`, `vs.`, `et al.`, `cf.` Zaman birimleri (`60 min.`) cümle bitirir.
- Cümle ayrıca bölümlere ayrılır. Ayırıcılar: virgül, parantez, `and`, `but`, `while`,
  `whereas`, `with`, `without`, `since`, `because`, `although`, `which`, `whether`.
- Bir cümlenin en çok 5000 karakteri incelenir.

| Organ | Sözcükler |
|---|---|
| `kidney` | urine, urinary, renal(ly), kidney(s), glomerular, tubular |
| `liver` | hepatic(ally), liver, hepatobiliary |
| `bile_feces` | bile, biliary, hepatobiliary, feces/faeces, fecal, stool |
| `lungs` | exhaled, exhalation, expired air, lung(s), pulmonary |

Önekli biçimler o organın **tersidir** ve hiçbir zaman o organın yolu sayılmaz:
`non-renal`, `nonrenal`, `extra-hepatic`, `non-biliary`, `post-…`, `pre-…`.
Aşağıdakiler de yol sayılmaz:
- organ sözcüğünden sonra bir laboratuvar, yan etki ya da yapı sözcüğü geliyorsa:
  `enzymes`, `function`, `tests`, `retention`, `colic`, `necrosis`, `stones`, `tumour`,
  `blood flow`, `tissue`, `filtration rate`, `bile salt`, `bile acid` …;
- yol sözcüğü olmayan dağılım cümleleri: `accumulates in the liver`, `concentrations in
  lung tissue`;
- başka bir madde ya da böbrek işlevi ölçüsü: `tubular secretion of creatinine`, `GFR`,
  `CrCl`.

**Yol ifadesi şartı.** Organ sözcüğü ancak bulunduğu bölüm bir atılım yolunu anlatıyorsa
ifade olarak döner. Bunun için aşağıdakilerden biri gerekir:

- yol sözcüğü: excreted, eliminated, cleared/clearance, recovered, metabolized,
  secreted, filtered, route, pathway, appears/found/detected, accounts …;
- `in/into/via/through/by (the)` + organ;
- kısa, fiilsiz bir etiket (`Mainly hepatic`, `Urine: 65% unchanged`). Etiket ancak
  cümlenin ilk bölümüyse ya da cümlede hiç fiil yoksa sayılır;
- cümlede daha önce bir yol bölümü varsa ona bağlanmış kısa bir öğe; parantez ya da
  zarf aradaysa da geçerlidir: `excreted in breast milk and urine`, `predominantly renal
  and fecal`, `recovered in urine (40%) and feces (55%)`, `in urine and, to a lesser
  extent, feces`;
- `… of which` yapısı (`clearance is 5 L/h, 60% of which is renal`);
- yol bölümüne bağlı `which is … renal` yapısı (`Clearance, which is predominantly
  renal, …`).

Sayılmayanlar: `Liver enzymes increased`, `Urinary retention was reported`,
`Pulmonary absorption is rapid`, `Renal function should be monitored`,
`… a bile acid sequestrant …`.

**Pay atanmaz.** Her ifade birebir cümle metni ve konumuyla döner. Bu bir **kayıt
ifadesidir**. Sistem bir organa yüzde ya da pay **atamaz**. Gerekçe: iki inceleme turu,
serbest metinde yüzdenin yanlış organa bağlandığını gösterdi:
- `60% and 30% … in urine and feces, respectively`;
- `Renally excreted, 95% protein bound`;
- `decreased by 50% in hepatic failure`.

Bu, en tehlikeli hata türüdür. Yüzdeler alıntının içinde okunur.

Notlar:

- `negated_or_minor`: organın **her** yol bölümünde olumsuzluk ya da açık bir küçük üst
  sınır var.
  - Olumsuzluk: `not`, `no`, `negligible`, `minimal`, `little`, `trace`, `small
    fraction` …
  - Küçük üst sınır: `less than / under / below / < / ≤ / no more than / at most` ile en
    çok %5 (`percent` de olur). Organın hemen ardından gelen parantezdeki pay sözcüğü
    (`renal (minor)`, `urinary (<5%)`) ve organın bölümünden yalnız bir parantezle
    ayrılan özne (`Only a small fraction (<2%) appears in urine`) de sayılır.
  - Olumsuzluk sayılmayanlar:
    - değişim anlatan `not`: `not reduced`, `did not differ`, `not different`, `does not
      change`, `did not affect`, `not dose-dependent`, `not saturated/saturable`, `not
      significantly different/changed`;
    - `not only`, `not less than`, `no dose adjustment`;
    - türü niteleyen `minor` (`minor metabolites`, `minor glucuronide conjugates`).
  - Olumsuzluk sayılanlar: `not significant route`, `not significantly metabolized`, `no
    significant … excretion`, `does not depend on …`. Bunlar yolu reddeder.
  - Sözcükle reddetme de olumsuzluktur: `absent`, `absence of`, `devoid of`, `lacks`,
    `nonexistent`, `never`, `undetectable`, `below the limit of detection/quantification`,
    `unlikely`, `unimportant`, `zero`, `nil`, `0%`, `escapes`, `bypasses`, `resistant to`,
    `free of`.
  - Karşıtlıkla dışlanan organ da olumsuzdur: `without hepatic metabolism`, `by the liver
    rather than the kidneys`, `in feces instead of / as opposed to urine`. Karşıtlığın
    öbür tarafındaki organ (karaciğer, dışkı) olumlu kalır.
  - Bir yol bölümüne bağlanmış kısa öğe o bölümün olumsuzluğunu da taşır: `not excreted in
    urine, feces, or bile` → üçü de `negated_or_minor`.
  - Olumsuzluk yalnız organın kendi bölümünde aranır. Parantez ve yan cümle ayrı
    bölümdür. `not metabolized by the liver and 95% is excreted in urine` → böbrekte not
    yok, karaciğer `negated_or_minor`. `Excreted in the urine (not metabolized)` → not
    yok.
  - Organın olumlu bir bölümü varsa not düşmez: `Renal clearance is negligible, but 80% …
    in urine`.
- `uncertain_statement`: kayıt bunu bilinmiyor ya da kesin değil olarak anlatıyor.
  - Çekinceli anlatım da sayılır: `may/might/could`, `possibly`, `probably`, `likely`,
    `thought to`, `believed to`, `suggested`, `not confirmed`, `unverified`, `putative` …
    `unlikely` çekince değil, olumsuzluktur.
  - Çekince organın kendi bölümünde aranır. Daha önceki bir çekince ancak organın fiilini
    de yönetiyorsa taşınır:
    - `The drug may be metabolized in the liver and excreted in urine` → iki yol da
      belirsiz (ortak `may`);
    - `Absorption may be delayed by food, and 80% of the dose is excreted unchanged in
      urine` → böbrek **kesin** kalır, çünkü araya yeni bir çekimli fiil (`is`) girer;
    - `;` sonrası çekince geriye taşınmaz.
  - Örnekler: `It is not known whether it is excreted in urine`, `Little is known about
    hepatic metabolism`, `No data are available on biliary excretion`, `has not been
    (fully) characterized/evaluated/established`, `is not well understood`.
  - "İhmal edilebilir" anlamına gelmez; `negated_or_minor` ile birlikte verilmez.
  - Yalnız organın kendi bölümünde aranır. Tek istisna bir önceki `… whether` bölümüdür.
  - `not known to inhibit …` belirsizlik sayılmaz.
- `condition_context`: organ yalnız bir hasta durumu olarak geçiyor (`renal
  impairment`, `hepatic cirrhosis`, `failure`, `disease`, `dialysis`, `patients with …`).
  Atılım yolu ifadesi değildir; okuyucudan gizlenmez. Durum sözcüğü organın kendi
  bölümünde aranır (`Excreted in urine and dialysis removes 30%` bir yol ifadesidir).
- `condition_also_mentioned`: organın yol ifadesi var, aynı cümlede bir hasta durumu da
  geçiyor. Durum cümlenin herhangi bir yerinde olabilir. Örnekler:
  - `Excreted in urine, but renal failure prolongs it`;
  - `Hepatic clearance is reduced in patients with cirrhosis`;
  - yolu değiştiren durum: `Renal excretion is impaired in infants`. Bu bir yol ifadesidir,
    yalnız durum değildir.

  `patients with normal renal function` durum sayılmaz.
- `metabolite_mentioned`: cümlede metabolit, glukuronid, konjugat veya sülfat geçiyor.
  Yalnız **bilgidir**; organ ana listede kalır. Örnek: `AlphaMed is extensively metabolized
  in the liver to inactive metabolites` (ana ilaç karaciğerde metabolize olur). İlaç
  adındaki `hydroxy-` sayılmaz.
- `metabolite_route`: o organ yoluyla giden şey **metabolittir**, ana ilaç değildir.
  - Metabolit cümleciğin öznesiyse: `The metabolite is excreted in urine`, `Its glucuronide
    is excreted in bile`.
  - Organdan sonra `as/of … metabolites` geliyorsa: `recovered in urine as metabolites`,
    `renal excretion of metabolites`.
  - Organın olumlu ifadelerine bakılır: `Renal clearance is negligible, but 80% … in urine
    as metabolites` → `metabolite_route`.
  - Ana ilaç da anılıyorsa (`unchanged drug and metabolites`, `the parent drug and
    metabolites`) bu not verilmez.
  - Bu not aidiyeti belirsiz listesine gider.
- `other_drug_named`: cümlede **başka bir ilacın adı** geçiyor; ifade o ilaca ait
  olabilir.
  - Adlar DrugBank'in kendisinden bulunur: metindeki 1–4 sözcüklük diziler `drugs.name`
    ve `drug_synonyms` ile tam (küçük harf) karşılaştırılır.
  - Kaydın kendi adı ve eş adları "başka ilaç" sayılmaz. Vücut maddeleri de sayılmaz
    (`urea`, `water`, `glucose`, `albumin` …).
  - Bulunan ad yanıtta `other_drugs` olarak gelir (metindeki yazılışıyla).
- `animal_study`: hayvan çalışması (`In rats, …`, `in animal studies`); ifade insana
  uygulanmayabilir.
- `other_subject_possible`: cümlede karşılaştırma ya da başka ürün geçiyor.
  - İşaretlenenler: `unlike`, `in contrast to`, `as opposed to`, `co-administered with`,
    `combined with`, `given with` (yemek/su değilse), `drug x` …
  - İşaretlenmeyenler: `with food`, `compared with young subjects`, `similar to that in
    young subjects`.
  - İşaretliyse ifade bu ilaca ait olmayabilir.
- **Sınırlar.** Bir alandan en çok 50 ifade döner (`organs_truncated`). Bir alıntı en
  çok 1000 karakterdir (`quote_truncated`). Uzun bir cümlede alıntı, organ sözcüğünü
  içeren pencere olarak verilir. Pencerenin nereden kesildiği `quote_cut_before` ve
  `quote_cut_after` ile bildirilir. Saklı metin en çok 20 000 karakter gösterilir
  (`truncated`). İfadeler yalnız gösterilen metinden çıkarılır; her konum gösterilen
  metnin içindedir.
- **Yer tutucu.** `Not Available`, `N/A` gibi yer tutucular (sondaki noktalama dahil)
  metin sayılmaz.

## 3. Ortak protein üzerinden açıklama

İki ilaç ancak **aynı, tanımlanabilir insan proteinini** kaydetmişse açıklanır.

- **Gruplama.** Bir ilacın kayıtları önce BE kimliğine göre gruplanır. Kimliksiz bir
  kayıt, adını taşıyan **tek** bir gruba katılır. Ad birden çok grupta varsa ya da
  hiçbirinde yoksa yalnız adla ayrı bir grup olur. Kimliksiz bir kayıt iki farklı kimliği
  asla birleştirmez.
- **Eşleşme.** İki tarafta da kimlik varsa ortak bir BE kimliği gerekir; tür fark etmez.
  Farklı BE kimlikleri, ad aynı olsa bile eşleşmez. Kimlik yalnız bir taraftaysa ya da
  hiçbirinde yoksa ad eşleşir.
- **Belirsiz ad.** Kimliksiz bir grup hiçbir şey açıklamaz:
  - karşı ilacın birden çok grubuyla adla eşleşiyorsa;
  - ya da kendi ilacı o adı birden çok BE kimliğiyle listeliyorsa.

  Hangi proteinin kastedildiği bilinemez. Ad yine de `shared_proteins_without_direction`
  içinde gösterilir; "ortak protein yok" denmez.
- **Tek açıklama.** Aynı etken, kurban, protein ve mekanizma için tek açıklama verilir.
  Protein **kimliğe** (BE) göre ayırt edilir. Aynı adlı ama farklı kimlikli iki protein
  ayrı ayrı açıklanır. Yönsüz listede adın yanına kimlik yazılır (`X (BE1)`, `X (BE2)`).
- **Güç seçimi.** `unknown` yazan güç "belirtilmiş" sayılmaz; aynı rolün `strong` gibi
  açık bir gücü varsa o seçilir.
- **Ortak substratın türü.** Çiftin sırasından bağımsızdır (taşıyıcı > enzim > plazma
  proteini).
- **Kimliksiz kayıt.** Kimliği ve adı olmayan kayıt hiçbir şeyle eşleşmez.
- **İnsan dışı türler.** `Humans`, `Human` ve `Homo sapiens` dışındaki türler listede
  gösterilir, karşılaştırmaya girmez.
- **Yinelenen kayıt.** Bir ilaç aynı proteini birden çok kez listelediyse eylemler
  birleştirilir. Her rol için **tek bir kaydın** kanıtı tutulur: önce `known_action:
  yes` olan, sonra güç belirten kayıt. Güç ve `known_action` farklı kayıtlardan
  karıştırılmaz.
  - İnhibitör kaydı `yes`, substrat kaydı `no` ise inhibisyon kanıtı `yes` olarak
    görünür.
  - `yes` ve güçsüz bir kayıt ile `no` ve `strong` bir kayıt varsa sonuç `yes` olur, güç
    yazılmaz (`strength_not_stated`).
- **Listeleme sınırı.** Bir ilacın proteinlerinden en çok 200'ü listelenir
  (`proteins_truncated`). Çift açıklamaları her zaman kayıtların tamamıyla yapılır.

Her iki yön ayrı ayrı denenir. Açıklamanın türü (`enzyme` / `transporter` / `carrier`),
kurbanın **substrat kaydının** türüdür. Etkenin kaydı başka türdense
`listed_under_different_protein_kinds` uyarısı düşer.

| İlaç A'nın rolü | İlaç B'nin rolü | Açıklama |
|---|---|---|
| inhibitör | substrat | Enzim: A, B'yi işleyen enzimi yavaşlatır; B kanda **birikebilir** (`victim_exposure_may_increase`). Taşıyıcı: B'nin taşınması azalabilir (`victim_transport_may_decrease`). Plazma taşıyıcı proteini (`carrier`): yalnız bağlanma değişebilir, serbest düzeyin yönü belirlenemez (`carrier_binding_may_change`) |
| indükleyici | substrat | Enzim: B **daha hızlı temizlenebilir** (`victim_exposure_may_decrease`). Taşıyıcı: taşınma artabilir. Carrier: yukarıdaki gibi yönsüz |
| substrat | substrat (ikisinde de inhibitör/indükleyici yok) | Yarışma olabilir, yön yok (`competition_possible_not_established`); zayıf kanıt |
| başka | başka | Yön çıkarılmaz; protein `shared_proteins_without_direction` içinde adıyla listelenir |

Bir açıklama şu durumlarda `directional: false` olur:
- ortak substrat;
- plazma taşıyıcı proteini (carrier);
- etkenin aynı protein için hem inhibitör hem indükleyici olması.

Yönlü açıklamalar önce sıralanır; enzimler taşıyıcılardan önce gelir. Açıklaması olan bir
protein `shared_proteins_without_direction` içinde ayrıca listelenmez.

Çift durumu:

| Durum | Anlamı |
|---|---|
| `explained_by_shared_protein` | En az bir **yönlü** açıklama var (`directional: true`) |
| `shared_substrate_only` | Yalnız ortak substrat |
| `shared_protein_no_direction` | Ortak protein var, net yön yok. Nedenleri: yalnız plazma taşıyıcı proteini, etken aynı protein için hem inhibitör hem indükleyici, ya da rol yok |
| `no_shared_protein_in_record` | Kayıtlarda ortak protein yok |
| `drug_not_found` | İlaçlardan biri bulunamadı |

Her açıklamanın uyarıları (`caveats`):
- İki rolden biri DrugBank'te doğrulanmış değilse `known_action_not_confirmed`.
- Aynı ilaç aynı protein için hem inhibitör hem indükleyiciyse
  `perpetrator_listed_as_inhibitor_and_inducer`. İki zıt açıklama da zayıf olarak
  gösterilir; net yön yoktur.
- Enzimde `prodrug_reverses_direction`: ilaç bu enzimle etkinleşiyorsa yön tersine döner.
- Enzimde güç yoksa `strength_not_stated`.
- Taşıyıcıda `transport_direction_depends_on_protein`.
- Plazma taşıyıcı proteininde `carrier_binding_direction_not_established`.
- Farklı türde kayıtlarda `listed_under_different_protein_kinds`.
- Ortak substratta `shared_substrate_is_weak_evidence`.
- Her zaman `other_pathways_may_compensate`.

Ekran cümlesi "temizleyen" değil, "işleyen" der: DrugBank'te substrat olmak, o enzimin
ana temizlenme yolu olduğu anlamına gelmez. Örnek: "A, B ilacını işleyen X enzimini
yavaşlatır (B bu enzimin substratı olarak kayıtlı). Bu yüzden B kanda birikebilir."

Ekranın diğer kuralları:
- **Çelişki.** İnhibitör+indükleyici çelişkisi tek bir çekinceli cümle olarak gösterilir:
  "hem yavaşlatıcı hem hızlandırıcı olarak kaydedilmiş; yön belirlenemez". Kanıtta iki
  kaydın gücü de yazılır.
- **Plazma proteini.** Ortak substrat plazma taşıyıcı proteinindeyse "aynı kan/plazma
  bağlanma proteinine bağlanır" denir.
- **known_action.** "ilacın kendi etki mekanizmasının parçası mı" olarak açıklanır.
  `no` değeri "proteini etkilemez" anlamına gelmez.
- **Organ listesi.** Üç ayrı liste vardır:
  1. **Temizleyen organlar:** işaretsiz ifadeler.
  2. **Aidiyeti belirsiz ifadeler:** `other_drug_named`, `other_subject_possible`,
     `animal_study`, `metabolite_route`. Yalnız `metabolite_mentioned` taşıyan ifade ana
     listede kalır. Açıklamasıyla ve geçen ilacın adıyla gösterilir;
     seçilen ilacın yolu sayılmaz.
  3. **Olumsuz, belirsiz ya da yalnız hasta durumu:** `negated_or_minor`,
     `uncertain_statement`, `condition_context`.
- **Tek ilaç.** Tek ilaç seçiliyken "Organ ve protein profilini göster (M-03)" düğmesi
  yalnız M-03'ü çağırır.

DrugBank'in kendi etkileşim metni (`drug_interactions`) çiftin yanında, ayrı bir kanıt
olarak gösterilir. Yinelenen kayıtlar bir kez gösterilir. Kurallar o metni okumaz ve
onunla birleştirmez.

## 4. Bilinen sınırlar

- **Ad tanıma DrugBank adlarıyla sınırlı.** Organ cümlesindeki başka ilaç, yalnız
  DrugBank'te adı ya da eş adı olarak kayıtlıysa (tam yazılışla) tanınır. Kısaltma, marka
  yazım farkı ya da yalnız zamirle anlatılan başka ilaç (`the parent compound`)
  tanınmayabilir. Okuyucu birebir cümleyi görür.
- **Pay yok.** Organ payları (yüzde) yapılandırılmaz; alıntıdan okunur.
- **Kapsam kayıttakiyle sınırlı.** Protein listesi DrugBank'in kaydettikleriyle
  sınırlıdır. Eksik kayıt, ilacın o proteini kullanmadığı anlamına gelmez.
- **Klinik derece yok.** Enzim payı, güç sınıflandırması ya da klinik önem derecesi
  türetilmez.
- **Uzman kabulü yok.** Form A ≥%90 M-03 uzman kabulü bu teslimde yapılmadı.
