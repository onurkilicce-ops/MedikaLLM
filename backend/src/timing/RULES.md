# M-02 metin ayrıştırma kuralları (`m02-text-parser/6`)

Bu belge `parser.py`'nin **nesnel** kurallarıdır. Güven yüzdesi yoktur; her
değer ya kurala uyup yapılandırılır ya da metni korunarak incelemeye bırakılır.
LLM, harici kaynak veya ürün/dozaj tablosu kullanılmaz.

## 1. Kapsam

| Ölçüm | Okunan alan | Not |
|---|---|---|
| `tmax` | yalnız `drugs.absorption` | Alanın adı tek başına Tmax kanıtı değildir; açık Tmax ifadesi gerekir |
| `half_life` | yalnız `drugs.half_life` | `String(1000)`; tam 1000 karakter = **olası kesilme** işareti |

`metabolism`, `clearance`, `route_of_elimination` bu teslimde yalnız envanterde
sayılır, API'de ayrıştırılmaz.

## 2. Alan durumu

1. NULL / yalnız boşluk → `empty`.
2. Tüm metin (noktalama/boşluk kırpılmış, küçük harf) şu kümedeyse → `placeholder`:
   `not available`, `n/a`, `na`, `none`, `unknown`, `not applicable`,
   `no data`, `not known`, `not determined`, `not established`, `-`, `--`, `?`.
3. Aksi halde ayrıştırılır; sonuç `parsed` / `parsed_needs_review` /
   `unparsed_needs_review` / `no_statement_found` (bkz. 9).

## 3. Cümle ve pencere

- Cümle sonu: `.`, `!`, `?` + boşluk + büyük harf; veya `.`, `!`, `?` + satır
  içi referans belirteç(ler)i (`[A1]`) + (boşluk olsun olmasın) büyük harf —
  belirteçler önceki cümleye aittir; ayrıca satır sonu. Bilinen kısaltmadan
  (`approx.`, `pts.`, `i.e.`, `e.g.`, `i.v.`, `p.o.` …) sonra bölünmez.
  Ondalık nokta (`1.5`) cümle sonu değildir.
- Bir cümlede birden çok süre varsa cümle **pencerelere** bölünür. Ardışık a ve
  b süreleri arasındaki sınır: a'nın hemen arkasındaki parantez a'ya aittir
  (b o parantezin içindeyse `(` b'nin penceresini başlatır); aksi halde a'dan
  (ve parantezinden) sonraki **ilk** ayırıcı (`;`, `,`, ` and `, ` while `,
  ` whereas `, ` but `, ` compared with `, ` versus `, ` vs `). Ayırıcı yoksa
  ortası; bu belirsiz sınırdır ve o pencerelerde koşul varsa değer
  `condition_attribution_ambiguous` ile işaretlenir.
- Yaş ifadeleri (`aged 65 years`, `children 2 to 12 years`, ay/yıl birimleri)
  pencere kesmez; çevresindeki değerin koşuludur.
- Koşullar yalnız bulundukları pencereye uygulanır. Tek istisna: cümlenin ilk
  virgülünden önceki, süre içermeyen giriş ifadesi (`In children, …`,
  `Following oral administration, …`) kendi penceresinde o kategoride koşul
  olmayan sonraki pencerelere de uygulanır (kendi koşulu olan pencerede
  üzerine yazılmaz).

## 4. Süre ifadesi

- Sayı: `\d+(\.\d+)?`; harf, `/` veya `.` ile bitişik başlayan sayı (`t1/2`)
  sayı değildir. Virgüllü (`1,5`, `1,000`) veya birden çok noktalı sayı →
  inceleme (`ambiguous_number_format`). Sayı kelimeyle yazılmışsa (`two hours`)
  yapılandırılmaz.
- Birimler (orijinal yazım korunur): saniye `s, sec, secs, second(s)`; dakika
  `min, mins, minute(s)`; saat `h, hr, hrs, hour(s)`; gün `day(s)`; hafta
  `wk, wks, week(s)`. Saate çeviri: s/3600, dk/60, ×1, ×24, ×168.
  `month(s)`, `year(s)`, `yr(s)` tam çevrilemez → inceleme
  (`unit_not_exactly_convertible`).
- Biçimler: tek değer (`90 minutes`), aralık (`2-4 hours`, `2 – 4 h`, Unicode
  tire/eksi varyantları `‐ ‑ ‒ – — −`, `2 to 4 hours`, `2 hours to 3 days`,
  `between 2 and 4 hours`, `ranging from 2 to 4 hours`), `5.3 ± 1.2 hours`
  (`point` + `dispersion`; aralığa çevrilmez; `1.5 h ± 20 min` gibi karışık
  birimde yayılım kendi birimiyle çevrilir), bitişik sıfat (`12-hour`).
  `and` yalnız `between X and Y` içinde aralık ayırıcıdır; `4 hours and 12
  hours` iki ayrı değerdir.
- Kelimeye/alt simgeye bitişik sayı süre değildir: `t1/2`, `AUC0-24h`,
  `AUC0–24h`; `AUC(0-24 h)` → inceleme (`auc_interval`).
- Değişim ifadesi (`increased/prolonged/decreased … from X to Y`) aralık
  değildir → inceleme (`change_statement`); `ranges/ranging from X to Y`
  aralıktır.
- Niteleyiciler (sürenin hemen önünde):
  - yaklaşık → `approximate=true`: `approximately`, `approx.`, `about`,
    `around`, `roughly`, `nearly`, `~`, `≈`, `ca.`, `circa`;
  - üst sınır (`upper_bound`): `<` (`inclusive=false`), `≤`/`<=`/`up to`/
    `at most`/`no more than`/`not more than` (`true`), `less than`/`under`/
    `below`/`shorter than` (`false`); Tmax bağlamında `within` (`true`);
  - alt sınır (`lower_bound`): `>`/`more than`/`greater than`/`longer than`/
    `exceeding` (`false`), `≥`/`>=`/`at least` (`true`);
  - `over` belirsizdir → inceleme (`ambiguous_qualifier`); yarılanma ömründe
    `within` da belirsizdir.
- Geçersiz: 0, negatif (`-2 hours`, `−2 h`), sonlu olmayan sayı, ters aralık
  (`6-4 hours`) → inceleme (`invalid_value` / `inverted_range`). Bilinmeyen
  değer asla `0` olmaz.
- `4, 6 and 8 hours`, `3, 4, and 5 hours`, `3, 4 or 5 hours` gibi birimi
  paylaşan sayı listesi → inceleme (`number_list_shared_unit`).
- Aynı cümlede hedef ölçüme ait bir değer çözülemeyip incelemeye gittiyse
  (sayı listesi, belirsiz sayı/niteleyici, değişim ifadesi, geçersiz/ters
  aralık, ay/yıl), o cümlenin yapılandırılan diğer değerleri de
  `other_value_in_sentence_unresolved` ile işaretlenir — hiçbiri sessizce
  seçilmez.

## 5. Ölçüm türünün belirlenmesi

Hedef anahtar sözcükler:
- `half_life`: `half-life`, `half life`, `halflife`, `t1/2`, `t½`, `t 1/2`.
- `tmax`: `tmax`, `t max`, `t(max)`, `time to peak`, `time to maximum`,
  `time of maximum`, `peak (plasma|serum|blood)? (concentration|level)`,
  `maximum (plasma|serum|blood)? (concentration|level)`,
  `cmax ... (reached|achieved|attained|occur*|observed)`.
  `maximum (therapeutic)? effect`, `peak effect`, `onset` **Tmax değildir**.

Rakip anahtar sözcükler (başka bir olay/ölçüm): `steady state … reached`,
`onset`, `duration of action`, `effect`, `response`, `infusion`, `dosing`,
`interval`, `every`, `clearance`, `cleared`, `eliminat*` (hedef ifadeye bitişik
`elimination half-life` hariç), `complete(ly/d)`, `remain*`, `elevated`,
`persist*`, `remov*`, `session`, `detect*`/`undetectable`, `mean residence
time`/`MRT`, `excreted`/`recovered`, `washout`, `lag time`; Tmax için ayrıca
yarılanma ömrü sözcükleri ve `absorb*/absorption`; yarılanma ömrü için Tmax
sözcükleri.

Bağlam dışlamaları (sürenin hemen önü/sonu): `every`/`q`, `for`, `by`
(`prolonged by 2 hours` = değişim miktarı), `aged`/`age`/`older than`/
`younger than`/`years old`/`of age` ve ay/yıl biriminde `children`/`patients`
… (yaş), `AUC` (`auc_interval`), arkasından `later`; yarılanma ömründe
önünde `after`/`at`/`post` veya arkasından `after (a single) dose/
administration`. İstisna: değer yarılanma ömrünün yüklemiyse (`… half-life is
4 hours after oral administration`) arkadaki ifade zaman noktası değil yol
koşuludur. Dışlanan süre ölçüm olmaz → inceleme (gerekçe kodu ile).

Karar (sırayla; önce ölçüm türü, sonra bağlam dışlaması, sonra niteleyici):
1. Pencerede hedef sözcük varsa ve süreye **en yakın** ölçüm sözcüğü (hedef
   veya rakip; eşitlikte hedef) hedefse → `value_keyword`. Uygulama/dozdan
   sonra ifadesi (`after oral dosing`, `following administration`) içindeki
   `dosing`/`dose` rakip sayılmaz; zaman referansıdır.
2. Değil ve cümlede, süreden önce hedef sözcük varsa, pencerede rakip sözcük
   yoksa → `sentence_keyword`.
3. Yalnız `half_life` alanında: alan tek cümle ve tek süreden oluşuyorsa,
   süre/niteleyici/referans dışında en çok 4 sözcük kalıyorsa (örn. `4-6 hours`,
   `Approximately 2 hours in adults`) ve hiç hedef/rakip sözcük yoksa →
   `field_only`.
4. Aksi halde ölçüm değildir; süre inceleme kalemine yazılır
   (`duration_not_identified_as_tmax` / `duration_not_identified_as_half_life`).
   Ölçüm türü belirlenen süre bağlam dışlamasına takılırsa gerekçe dışlama
   kodudur: `dosing_interval`, `duration_of_other_event`, `change_amount`,
   `age_context`, `context_excluded`, `time_point_not_duration`.
5. Cümlede güçlü hedef sözcük var ama hiç ayrıştırılabilir süre yoksa →
   inceleme (`keyword_without_parsable_value`). Tmax için güçlü sözcük:
   `tmax`, `time to peak/maximum` veya tepe derişim ifadesi + zaman fiili.

## 6. Koşullar (pencere içi, sözcük kuralları)

`route` (oral/p.o./per os/PO, intravenous/IV/i.v., intramuscular/IM, subcutaneous/SC, sublingual,
buccal, rectal, topical, transdermal, inhaled/inhalation, intranasal,
ophthalmic, intrathecal), `formulation` (immediate-/extended-/sustained-/
controlled-/modified-/delayed-release, IR/ER/XR/SR/CR, tablet, capsule,
solution, suspension, injection, patch, liposomal, depot), `population`
(healthy volunteers/subjects/adults, adults, children/pediatric, adolescents,
infants, neonates, elderly/geriatric, renal impairment/failure/ESRD/
hemodialysis, hepatic impairment/cirrhosis, pregnant, poor/extensive/
ultrarapid metabolizers, smokers, `aged N(-M) years` ifadesi), `food_state`
(fasted/fasting, fed, with food, high-fat meal, empty stomach), `dosing`
(single dose, multiple/repeated doses, steady state), `analyte` (`metabolite`
geçerse `metabolite`; `parent`/`unchanged` geçerse `parent`; ikisi birden →
`not_stated` + `analyte_ambiguous`), `phase` (terminal, elimination,
bi-/tri-/multiphasic; `distribution/absorption/initial/alpha/beta/gamma`
yalnız faz bağlamında: `… phase`, `… half-life`, `t1/2α` — `initial dose`,
`beta-lactam`, `volume of distribution` faz değildir), `matrix` (plasma,
serum, whole blood, intracellular, CSF, tissue, red blood cells), `kinetics`
(nonlinear/non-linear, dose-dependent, saturable, Michaelis-Menten,
zero-order, capacity-limited), `other` (tür/in vitro: rats, mice, dogs,
monkeys, animals, in vitro, preclinical; eş zamanlı kullanım:
co-administered with X, concomitant, in combination with X, given alone).

Çelişki anahtarı için terimler normalleştirilir (`orally`/`p.o.`→`oral`,
`i.v.`/`IV`→`intravenous`, çoğul→tekil, `children`→`child` …); yanıtta
metindeki yazım korunur.

Zaman referansı (yalnız Tmax): pencere/cümlede `after/following ...
(administration|dose|dosing|ingestion|intake)` veya `post-dose` →
`after_administration`; yoksa `not_stated`. Yarılanma ömrü bir **süredir**:
`not_applicable_duration`.

## 7. Referanslar

Alıntılanan cümledeki `[A123]`, `[L45, T6]` gibi belirteçler yalnız **aynı
ilacın** `drug_references.ref_id` değeriyle birebir eşleşirse bağlanır.
Durumlar: `matched` (hepsi), `partially_matched`, `unmatched`,
`no_inline_reference`. Genel referanslar belirteç olmadan **hiçbir** ölçüme
bağlanmaz. Kapsam (`reference_scope`): değerin kendi penceresinde yazılmış
belirteç → `value_window`; cümle sonundaki belirteç, değer son `;` cümleciğinde,
cümlede tek süre ve değerden sonra başka iddia yok → `sentence_single_value`; cümlede
birden çok süre veya değerden sonra başka iddia → `sentence_shared`; belirteç başka
bir `;` cümleciğini kapatıyor → `sentence_other_clause` (bağlanmaz,
`nearby_reference_tokens`). `stored_reference_attributed` (sürüm 1'deki
`primary_reference_verified`) yalnız `matched` **ve** kapsam `value_window` veya
`sentence_single_value` ise `true`; bu saklı bir eşlemedir, dış kaynağın açılıp
değeri desteklediğinin doğrulanması değildir (bkz. 8b).

## 8. İnceleme ve çelişki

Ölçümün `review_reasons` örnekleri: `stored_text_possibly_truncated`,
`conflicting_values_same_conditions`. Çelişki: aynı ölçüm türü ve **tamamen
aynı koşul anahtarına** sahip (koşulların tümü + analit) iki veya daha çok
ölçümün değerleri (tür, alt, üst, nokta) farklıysa; hepsi korunur, aynı
`conflict_group` ile işaretlenir, hiçbiri sessizce seçilmez.

Olası kesilmiş metinde son cümle terminal noktalama ile bitmiyorsa
ayrıştırılmaz (`sentence_possibly_truncated`); diğer ölçümler
`stored_text_possibly_truncated` ile işaretlenir.

## 9. Durum kodları (`data_status.tmax` / `data_status.half_life`)

`parsed` ≥1 işaretsiz ölçüm · `parsed_needs_review` ölçüm var, hepsi işaretli ·
`unparsed_needs_review` ölçüm yok, inceleme kalemi var (veya yarılanma ömrü
alanında metin var) · `no_statement_found` (yalnız absorption) metin var, Tmax
ifadesi/inceleme kalemi yok · `empty` · `placeholder`.

## 8f. Sürüm 6 — beşinci denetim (M02-O1-R5) kuralları: özne karar kuralı

8d ve 8e'deki özne kuralları bu bölümle değiştirildi. Çelişen eski cümleler
`[R5: 8f ile değişti]` diye işaretlidir. Kök neden: "aday çözülemedi" bilgisi altı yolda
sessizce "özne yok" ya da "kayıt eşleşti" sonucuna dönüşüyordu:
- (1) çerçevede tek bir ortam sözcüğü (`monotherapy`) bütün baş öbeği atlatıyordu;
- (2) adayın herhangi bir yerinde grup adı (`drug b in adults`) adayı yok sayıyordu;
- (3) rakamlı sözcük (`drug b 10 mg`) adayı yok sayıyordu;
- (4) küçük harfli yolda adın baştan/sondan kısmi örtüşmesi kayıt sayılıyordu;
- (5) büyük harfli yolda baştan örtüşme (`Magnesium` / `Magnesium Sulfate`) kayıt
  sayılıyordu;
- (6) rakamla başlayan her çizgi sonrası parça aralık sayılıyordu (D4).

**Karar kuralı (her harf büyüklüğünde ve her özne kalıbında aynı):**

1. **Baş öbek.** Aday, ilk edat koşulundan ya da ilgi cümleciğinden önceki baş öbektür.
   Kesen sözcükler: `in`, `with`, `without`, `after`, `during`, `following`, `at`, `on`,
   `under`, `before`, `among`, `receiving`, `taking`, `given`, `when`, `if`, `by`, `via`,
   `from`, `to`, `versus`, `who`, `which`, `that`, `whose`. `of` tutulur (`the metabolite
   of drug b`). Örnek: `drug b in adults` → `drug b`.
2. **Özne taşımayan aday (`ignore`), yalnız şu üç durumda:**
   - aday bir miktardır (rakamla başlar: `4 hours`);
   - aday bütünüyle bir metabolit kodudur (`M1`);
   - baş öbeğin son sözcüğü bir topluluk adıdır (`Japanese subjects`, `Patients who …`).
3. **Ad sözcükleri.** Bunlar atılır: belirleyiciler, genel sözcükler, koşul / grup / tür /
   metabolit sözcükleri, ortam ve zarf sözcükleri (`monotherapy`, `overdose`, `general`
   …), ürün/biçim/miktar/yaş sözcükleri (`form`, `dosage`, `mg`, `aged`, `years` …) ve
   rakamlar. İlaç adından sonraki tek harf ya da sayı kodu adla birleşir (`drug_b`). Hiç ad
   sözcüğü kalmazsa aday özne taşımaz (`For oral administration,`, `In general,`, `For
   monotherapy,`, `In children aged 2 to 12 years,`).
4. **Kayıt eşleşmesi yalnız eşitliktir.** Normalize edilmiş ad, aynı yolla normalize
   edilmiş kayıt adına eşit olmalıdır.
   - Tuz sözcükleri atıldıktan sonra ad kalıyorsa karşılaştırma tuzsuzdur. Aynı ana adın
     tuzu aynı ilaç sayılır: `drug a hydrochloride` ↔ `Drug A`, `drug a sodium` ↔ `drug
     a`.
   - Ad tuz sözcüklerinden oluşuyorsa tuzlarla birlikte tam eşitlik gerekir:
     `magnesium sulfate` ↔ `magnesium sulfate` evet; `magnesium` ↔ `magnesium sulfate`
     hayır; `magnesium sulfate` ↔ `magnesium` hayır.
   - Baştan/sondan kısmi örtüşme (`acid` / `valproic acid`, `drug a b` / `drug a`) eşleşme
     değildir.
   - Büyük harfli adlar (8a/8b) da aynı kuralla karar verir.
5. **Diğer her aday çözülememiştir.** Ölçüm yok (gerekçe `subject_unresolved` ya da büyük
   harfli adda `subject_not_record_drug`), ≈5× yok; metin inceleme kaleminde korunur.
6. **Bağlam yedeği.** Önce değerin penceresi okunur. Pencerede özne yoksa ve ölçüm sözcüğü
   de yoksa cümlede önceki özne geçerlidir (8d).

Bu kuralın sonucu: aynı yabancı özneye koşul (`monotherapy`, `in adults`, `in overdose in
adults`, `10 mg`, `extended-release tablets` …) eklemek ya da silmek sonucu temize
çeviremez. Aynı koşulla kayıt öznesi temiz kalır.

**Çizgi ve aralık (D4).** 8e'deki çizgiler (`-`, `–`, `—`, `--`) bir çizgi
ayırıcısıdır; ardından bir süre (sayı + zaman birimi) geliyorsa iki süreyi bağladığı
kabul edilir ve ayırıcı sayılmaz (`4 hours - 6 hours`, `4 – 6 hours` aralıktır). Ardından
süre olmayan sayılı bir ifade gelirse (`- 10 patients developed rash [A2]`, `– 10% of
patients …`) ayrı iddiadır: belirteç bağlanmaz, `nearby`'da kalır, kapsam `none` olur.
Sözcük içi tire (`half-life`, `extended-release`) ayırıcı değildir. İki nokta aralık
olamaz.

**Bilinen sınırlar:**
- Genel ilaç/marka adı ve kimyasal eşdeğerlik tanıma yoktur: kayıt adının farklı yazımı
  ya da eş adı incelemeye düşer (aşırı inceleme, yanlış temiz yok).
- `4 hours -- 6 hours` değer ayrıştırmada aralık değildir (önceki davranış): iki çelişen
  değer olarak incelemeye düşer, A1 yalnız ikinci değere bağlanır.
- Kesen edat ve sözcük listeleri sınırlıdır. Listede olmayan bir ortam sözcüğü ad
  sayılır; kayıtla eşleşmezse ölçüm incelemeye düşer.
- API yapısı değişmedi ve yeni gerekçe kodu yok.

## 8e. Sürüm 5 — dördüncü denetim (M02-O1-R4) kuralları

- **Temizleme kayıt eşleşmesi değildir (D3).** Özne adayı, 8d'de anlatılan kalıntı ada iki
  kez indirgenir:
  - tuz sözcükleri atılarak;
  - tuz sözcükleri tutularak.

  Yalnız belirleyici, genel sözcük, koşul, grup, tür ya da metabolit sözcüğünden oluşan
  aday (`the drug's`, `For oral administration,`, `In overdose,`) özne taşımaz (`ignore`).
  Tuzlar atılınca boşalan ama tuzlarla birlikte ad kalan aday (`magnesium sulfate`,
  `sodium chloride`) bir maddeyi adlandırır. Böyle bir aday yalnız tuzlarıyla birlikte
  kayıt adına eşitse kayıt ilacıdır (sentetik kayıt adı `magnesium sulfate`); değilse
  yabancıdır → ölçüm yok, `subject_unresolved`. Tuz atıldıktan sonra ad kalan aday
  (`drug a hydrochloride` → `drug_a`) önceki gibi karşılaştırılır.
- **Çerçevede koşul özneyi silmez (D3).** `For|In <en çok 10 sözcük>,` çerçevesinde
  yalnız ilk edattan (`in`, `with`, `after`, `during`, `at`, `on`, `under`, `among`,
  `receiving`, `taking`, `given`, `by`, `via`, `from`, `to`, `of` …) önceki baş öbek aday
  olur (`For drug b in overdose,` → `drug b`). Bir durum sözcüğünün `of` tümleci de aday
  olur (`In overdose of drug b,` → `drug b`). Durum sözcükleri: `overdose`, `intoxication`,
  `poisoning`, `use`, `administration`, `treatment`, `therapy`, `infusion`, `dosing`.
  Zarf/ortam listesi (8d) artık yalnız baş öbeğe uygulanır, bütün çerçeveyi atlamaz.
  [R5: 8f ile değişti — ortam sözcüğü baş öbeği atlatmaz, yalnız ad kalıntısından atılır.]
- **`half-life of X` sınırı (D3).** Adayı bitiren sözcük (`is`, `in`, `at` …) bütün bir
  sözcük olmalıdır; önceden `sulfate` içindeki `at`'ta kesiliyordu. Aday en çok 6 sözcük
  olabilir (`drug b hydrochloride extended-release tablets`).
- **Çizgi (D4).** Değerden sonra en üst düzeyde gelen aşağıdaki çizgiler iki nokta gibi
  okunur:
  - `—` (boşluklu ya da boşluksuz);
  - boşluklu `–`;
  - `--`;
  - boşluklu `-`, ardından rakam gelmiyorsa. [R5: 8f ile değişti — ölçüt artık "ardından
    süre gelmiyorsa"; `- 10 patients …` ayırıcıdır.]

  Her parça 8d'deki gibi `annotation` / `claim` / `unclear` olarak sınıflanır. İlk
  `annotation` olmayan parça değerin iddiasını bitirir. O parçadaki belirteç
  `inline_reference_tokens`'a ve `references`'a girmez, yalnız `nearby`'dadır; kapsam
  `none` olur. Ardından gelen cümle sonu belirteci `sentence_other_clause` (`claim`) ya
  da `sentence_shared` (`unclear`) olur. `— in adults —` gibi bir `annotation` parçası
  iddiada kalır. Değerden önceki aynı çizgiler de önceki iddiayı bitirir.
- **Çizgi sayılmayanlar.** Sözcük içi tire (`half-life`, `extended-release`) ve sayısal
  aralık (`4-6`, `4 – 6`, `4 - 6`) çizgi sayılmaz.
- API yapısı değişmedi ve yeni gerekçe kodu ya da kapsam değeri eklenmedi.
- Bilinen sınırlar:
  - Genel ilaç adı ve marka tanıma yoktur.
  - Tuz listesi sınırlıdır: listede olmayan tuz sözcüğü (`heptahydrate`) ad sayılır,
    kayıt adıyla eşleşmezse incelemeye düşer.
  - Çerçevenin `of` tümleci yalnız yukarıdaki durum sözcüklerinden sonra okunur.
  - D1 ara ifade boşlama kuralları çizgili ara ifadeye uygulanmaz.

## 8d. Sürüm 4 — üçüncü denetim (M02-O1-R3) kuralları

Denetimin sekiz örneği ve ilk düzeltmeye karşı yapılan ayrı bir çürütme
taramasında yürütülerek yeniden üretilen yollar bu kurallarla kapatıldı.

- **Araya giren ifade (D1).** Cümlecik çözümlemesinden önce virgüllü ara ifadeler
  (`, … ,`, en çok 80 karakter) boşlanır. Bu yalnız çözümleme için yapılır; koşullar ve
  alıntı değişmez. Boşlanan konumlar:
  - bağlaçtan hemen sonra (`that, in adults, the half-life is …`, `whether, after oral
    administration, Tmax is …`);
  - olumsuzluktan hemen sonra (`did not, however, find that`);
  - özne ile fiil arasında (`the half-life, measured in adults, is …`);
  - değerden hemen önce (`is not, in adults, 4 hours`);
  - `that`/`whether`/`to`'dan hemen önce (`no evidence, however, that`, `failed, despite
    repeated attempts, to establish`).

  Böylece `that`/`whether`/`if` yine açan sözcük olur ve 8c'deki yöneten cümlecik
  kuralı uygulanır. Bağlaç sözcüğüyle (`and`, `but`, `or`, `yet`, `so`, `while`,
  `whereas`, `although`, `because`, `since`) başlayan parça ara ifade sayılmaz
  (`…, but in children, 4 hours`). Bağlaçtan sonra virgülsüz gelen yan cümlecik
  (`If taken with food, Tmax is 3 hours.`) de ara ifade değildir; değer ana cümlede
  ileri sürülmüştür.
- **Ara ifadenin sözcükleri (D1).** Boşlanan ara ifadenin içi yine de okunur:
  - koşula bağlı olmayan olumsuzlama, belirlenmemişlik ya da şüphe varsa ölçüm yok,
    `undetermined_statement` (`The half-life, which has never been confirmed, is 4
    hours.`);
  - temkin (`possibly`, `it is claimed`, `if confirmed`, `we suspect`, `reportedly`)
    varsa değer kalır, `hedged_value` (5× yok).
- **Zincirleme `that` (D1).** Art arda gelen her `that` düzeyinin yöneten cümleciği
  okunur (`It is not true that the investigators reported that …`).
- **Kurulamama ve yanlışlama (D1).**
  - Belirlenmemişlik sayılanlar: `fail(ed/s/ure) to`, `unable to` ya da `inability to`
    ardından `establish`, `determine`, `show`, `demonstrate`, `confirm`, `verify`,
    `prove`, `detect`, `measure`, `identify`, `characterize`, `define`, `replicate`,
    `reproduce`, `quantify`; ayrıca `remains to be shown/established/…` ile `false`,
    `untrue`, `incorrect`, `mistaken`, `erroneous`, `disproven`, `discredited` (değerin
    kendi cümleciğinde, yöneten cümlecikte ya da değerden sonra).
  - `lack/absence of evidence|data|proof|support` yöneten şüphedir.
  - Başka bir fiil alan `failed to respond` kapsam dışıdır.
- **Soru (D1).** `?` ile biten cümledeki değer ileri sürülmemiştir → ölçüm yok,
  `hypothetical_or_open_question`.
- **Olumsuz sınır.** `never shorter than` ve `isn't shorter than` alt sınırdır;
  `never longer than` üst sınırdır (8b'deki `not less than` gibi).
- **Özne (D3).** Aşağıdaki kalıplar harf büyüklüğünden bağımsız okunur:
  - `<sözcükler>'s half-life/Tmax/peak … concentration/Cmax` (araya en çok 4 sözcük;
    `'`, `’`, `ʼ`, `` ` ``, `´` kesmeleri);
  - çoğul `<sözcükler>' half-lives`;
  - `<sözcükler> reaches/attains/achieves peak/maximum/Cmax`;
  - `<en çok 5 sözcük> has/exhibits … half-life`;
  - `For|In <en çok 5 sözcük>,` (cümle/pencere başında ya da `.;:,` veya `and`, `but`,
    `while`, `whereas` sonrasında; `and`/`or`/`,` ile ayrılan her parça ayrı aday).

  Her adaydan kalıntı ad çıkarılır. Belirleyiciler, genel sözcükler, tuzlar
  (`hydrochloride`, `sodium` …), koşullar (özgün harf büyüklüğüyle de okunur:
  `ER tablets`), grup, metabolit ve tür sözcükleri ile metabolit kodları (`M1`) atılır.
  İlaç adından (`drug`, `compound`, `agent`, `product` …) hemen sonra gelen tek harf ya
  da sayı kodu adın parçasıdır: `drug b`, `compound a`. Kayıt `[SYNTHETIC] Drug A`
  için kalıntı `drug_a` olur, `compound a` ise kayıt değildir.

  Karar:
  - Kalıntı boşsa (`the drug's`, `In general,`, `For oral administration,`, `Japanese
    subjects`) özne değildir.
  - Kalıntı kayıt adına eşit ise ya da kayıt adıyla başlıyor/bitiyorsa kayıttır
    (`drug a hydrochloride`, `valproic acid` için `acid's`). [R5: 8f ile değişti — yalnız
    eşitlik; kısmi örtüşme (`acid's`) çözülemedi sayılır.]
  - Diğer kalıntı yabancıdır → ölçüm yok, `subject_unresolved`.
  - Çoğul ilaç adı (`the two drugs'`) ya da başka ürün işaretli ilaç adı (`comparator
    drug`, `reference product`, `concomitant medication` …) her zaman yabancıdır.
  - Önce değerin penceresi okunur. Pencerede özne yoksa ve pencerede ölçüm sözcüğü de
    yoksa (`… 8 hours in adults and 12 hours in children`), cümlede daha önceki en
    yakın özne geçerlidir. `…, and the half-life is 4 hours` kendi (genel) öznesini
    taşır.

  Büyük harfli ad 8a/8b'deki gibi ayrıca `subject_not_record_drug` verir. Genel ilaç
  adı tanıma yoktur: kayıt adının eşanlamlısı/markası da incelemeye düşer.
- **Ayraç ve iki nokta (D4).** Değerden sonraki ayraç içeriği ve `: ` sonrası (bir
  sonraki `;`'e veya cümle sonu belirtecine kadar) üç sınıftan birine girer:
  - `annotation`: çekimli fiil ya da atıf sözcüğü yok; koşul, sayı, birim, istatistik
    (`n`, `SD`, `CI`, `range` …), kısaltma (`e.g.`, `i.e.`, `approx.`) ve kaynak gösterme
    (`Smith et al.`, `Table 3`, `reference`) dışında içerik sözcüğü de yok → değerin
    iddiasının parçasıdır (`(in adults)`, `(n = 12, SD 1.1)`, `(Smith et al. [A1])`).
  - `claim`: `is/are/was/were/has/have/had/can/may/should/…` ya da `see/cf` içerir
    (`(adverse events are described elsewhere [A2])`, `(rash is common)`, `: adverse
    events are described …`) → ayrı iddiadır.
  - `unclear`: geri kalan her şey (`(adverse events described elsewhere [A2])`).

  `claim` ve `unclear` ayracın içindeki belirteçler ile ayraçtan sonra iddianın
  sonuna kadar gelen belirteçler değere bağlanmaz, `nearby`'da kalır (`(rash is common)
  [A2]`). İki nokta ayrı bir iddiaya açılıyorsa değerin iddiası `:`'da biter. Cümle
  sonu belirteci:
  - önünde `claim` varsa `sentence_other_clause` (bağlanmaz);
  - `unclear` varsa `sentence_shared` (listede, `stored_reference_attributed=false`;
    belirsizlik raporlanır).

  Değeri içeren ayraç sınıflanmaz.
- **İddia sınırı.** Değerin iddiası değerle aynı ayraç düzeyinde biter: `(n = 12,
  SD 1.1)` içindeki virgül iddiayı bitirmez. Küçük harfle başlayan sonraki cümle
  bölünmediği için iddia, değerden önceki `. `/`: ` sonrasından başlar ve sonraki
  `. `'da biter. Kısaltma noktası (`e.g.`, `approx.`, `et al.`, `Fig.`) ve ayraç içi
  nokta sınır sayılmaz.
- Bu sürümde API yapısı değişmedi ve yeni gerekçe kodu eklenmedi. Mevcut gerekçeler
  (`undetermined_statement`, `hypothetical_or_open_question`, `hedged_value`,
  `subject_unresolved`) ve kapsamlar (`none`, `sentence_other_clause`,
  `sentence_shared`) kullanılır.
- Bilinen sınırlar:
  - Kural listesi dışındaki yöneten fiiller ya da yanlışlama sözcükleri kaçabilir.
  - Tırnak/çizgi ile ayrılan ara ifadeler (`—`, `–`) boşlanmaz.
  - `Contrary to the claim that X, it is Y` yalnız `hedged_value` + çelişki verir.
  - `Patients who did not eat had a Tmax of …` (ilgi cümleciğindeki olumsuzluk) önceki
    gibi `negated_value` verir (aşırı inceleme).
  - Kısaltmalı sayfa başlığı (`Pharmacokinetics: the half-life is …`) 8a'daki büyük
    harfli `Name:` başlığı olarak okunur ve incelemeye düşer.

## 8c. Sürüm 3 — yeniden denetim (M02-O1-R2) kuralları

- **Yöneten cümlecik (D1).** Değerin cümleciği `whether` veya `if` ile açılıyorsa
  değer ileri sürülmemiştir → ölçüm yok, `hypothetical_or_open_question`. `that` ile
  açılıyorsa onu yöneten üst cümlecik (bir önceki cümlecik sınırından `that`'e kadar)
  okunur: olumsuzlama, belirlenmemişlik ya da `no/little/insufficient evidence`,
  `unlikely`, `doubt…` → ölçüm yok, `undetermined_statement`; `suggest`, `believe`,
  `may` gibi temkin → değer kalır, `hedged_value`. `as/since/because` ile bağlanan
  cümlecik ileri sürülmüştür; üst cümleciğin olumsuzluğu ona taşınmaz.
- **Tür kapsam cümlesi (D2).** Değersiz bir cümlede tanınan insan dışı/in vitro sözcüğü
  bir farmakokinetik sözcükle (elimination, half-life, pharmacokinetic, clearance,
  absorption, plasma, exposure, Tmax, AUC, studied, measured, data …) birlikte geçiyorsa
  kapsam cümlesidir (`In dogs, elimination was studied.`). Başka konudaki tür cümlesi
  (`In vitro studies indicate that X is a P-gp substrate.`) kapsam değildir.
- **Açık özne (D3).** `half-life/Tmax of|for <sözcükler>`, `<sözcükler> has/exhibits a
  half-life` ve değerden sonra `for/of <sözcükler>` harf büyüklüğünden bağımsız okunur.
  Baştaki belirleyiciler (`the`, `its` …) atılır; kalan ifade kayıt adı değil ve genel
  sözcük (`drug`, `compound`, `elimination`, `approximately` …), koşul, grup, metabolit
  ya da tür değilse → ölçüm yok, `subject_unresolved`. Genel ilaç adı tanıma yoktur:
  kayıt adının eşanlamlısı/markası da incelemeye düşer (bilinen sınırlama).
- **İddia içi atıf (D4).** Belirteç yalnız değerin kendi iddiasındaysa (değerden önceki
  son cümlecik sınırından sonraki sınıra kadar) `inline_reference_tokens`'a girer
  (`value_window`). Cümle sonu belirteci: değerden sonra `;` veya içerikli başka bir
  cümlecik varsa `sentence_other_clause` (bağlanmaz); cümlede başka süre varsa
  `sentence_shared`; aksi halde `sentence_single_value`. Bağlanmayan belirteçler
  `nearby_reference_tokens`'tadır.

## 8b. Sürüm 2 — bağımsız denetim (M02-O1-D1) kuralları

Hangi yapıda temiz değer verilir, nerede çekimser kalınır:

- **Olumsuzlama (D1).** Yalnız değerin **kendi cümleciği** sayılır: değerden önceki
  son `,`, `;` veya bağlaç (`and`, `but`, `as`, `since`, `because`, `which`, `that`,
  `when`, `although` …) sonrasından değere kadar. Orada `not`, `never`, `no`,
  `cannot` veya `n't` varsa → değer üretilmez, `negated_value`. İstisnalar: sınır
  ifadeleri (`not/no less|more|longer|shorter|greater|fewer than`, `does not
  exceed`, `not above/over` = üst sınır; `not below/under` = alt sınır) ve hemen
  ardından (≤30 karakter) bir koşul terimi gelen olumsuzlama (`patients with no
  hepatic impairment` → olumsuz koşul). Böylece `No dose adjustment is required as
  the half-life is 4 hours` temiz bir değerdir.
  `undetermined_statement` (değer üretilmez): kendi cümlecikte, değerden hemen sonraki
  yüklemde (`… 4 hours has not been established`) ya da değere bağlanan `which/that`
  cümleciğinde (`…, which was later refuted`) `not/n't (be/been/yet/well-/reliably)
  established|determined|known|reported|measured|confirmed|observed|demonstrated|
  seen|verified|proven|shown|validated…`, `yet to be …`, `unknown`, `unclear`,
  `unproven`, `refuted` geçmesi. Değerden sonraki `;` cümleciği veya **sonraki
  cümle** `This/These/It/Such/The value …` ile başlayıp aynı ifadeyi içeriyorsa
  değer kalır, `undetermined_statement` ile işaretlenir. Başka öznenin cümleciği
  (`… 5 hours, and the relevance of this … is unclear`) değeri etkilemez.
  Kanıtsız tahmin (`may/might/could be`, `possibly`, `presumably`, `thought/believed/
  assumed/suggested to be`) → değer kalır, `hedged_value` (≈5× yok).
  Koşul teriminin önünde `without`, `lacking`, `no`, `not in/with/on/receiving/
  undergoing`, `who do not have`, `except`, `excluding`, `other than`, `free of/from`,
  `absence of`, `unless` varsa terim metni olumsuzlamayla birlikte tutulur ve değer
  `negated_condition` alır (≈5× yok). `nonsmokers`/`non-smokers` bir nüfus terimidir.
- **Değer dışı bağlam (D2).** Alanın **değer içermeyen** bir cümlesi yalnız açıkça
  kapsam bildiriyorsa sayılır: `these/this/such data|values|measurements|results|…`,
  `data … were obtained/derived/measured/from`, `apply to`, `refer to`, `the study
  enrolled/included`, `studies were done/conducted`, ya da başlık satırı (`Dogs:`,
  ≤4 sözcüklük noktasız satır). Böyle bir cümlede formülasyon/nüfus/`other` koşulu
  ya da tanınmayan bir grup/form sözcüğü (`patients`, `formulation`, `products` …)
  varsa ve değerin kendi penceresinde o kategoride koşul yoksa →
  `field_context_unattributed`. Sıradan cümleler (`It is available as tablets.`,
  `No dose adjustment is needed in the elderly.`, `In vitro studies indicate …`)
  kapsam bildirmez. İnsan dışı/in vitro sözcüğü (kelime olarak; `administration`
  içindeki `rat` değil) böyle bir kapsam cümlesinde ya da değer içeren bir cümlede
  geçiyor ve değerin kendi tür terimi (`humans` dahil) yoksa →
  `non_human_context_in_field`. Sözlük: rats, mice, murine, rodents, dogs, beagles,
  canines, monkeys, macaques, primates, rabbits, pigs, animals, in vitro, ex vivo,
  preclinical/nonclinical, hepatocytes, microsomes, cell lines … Sözlükte olmayan
  grup `in/among <1–2 sözcük> patients|subjects|…` biçiminde yakalanır.
- **Özne (D3).** Karşılaştırma ifadesi (`unlike`, `like`, `similar to`, `compared
  with/to`, `in contrast to`, `as with`, `relative to`, `than that of`) değerden önce
  gelir ve değer karşılaştırılanın ilgi cümleciğindeyse (`which/who/whose/with` veya
  parantez) → `subject_unresolved_comparison` (değer üretilmez); değerden önce gelen
  diğer karşılaştırma yalnız `comparison_in_clause` ile işaretler; değerden sonra
  gelen karşılaştırma (`… 4 hours, which is shorter than that of other drugs`)
  etkilemez. Kayıt adı verilirse büyük harfle başlayan ad şu kalıplarda özne
  sayılır: `half-life/Tmax of|for X`, `X's half-life`, `X has/exhibits/shows a
  half-life`, cümle başında `For/In X,`, `X:` başlığı, `Half-life (X)`, değerden sonra
  `for/of/with X`. Ad kayıt adıyla aynı (veya kayıt adı + boşluklu ek, ör. tuz)
  değilse → `subject_not_record_drug` (değer üretilmez). Ardından grup sözcüğü gelen
  ad (`Japanese subjects`), koşul/ölçüm/tür sözcükleri özne değildir; metabolit kodu
  (`M1`) değer kalır, `subject_code_unresolved`. Marka adı kayıt adından ayırt
  edilemez → incelemeye düşer (bilinen sınırlama). Küçük harfle yazılmış başka ilaç
  adları yakalanmaz; genel ilaç adı tanıma yoktur.
- **Referans kapsamı (D4).** Cümle sonu belirteci yalnız son üst düzey `;` cümleciğine
  aittir. Değer başka cümlecikteyse belirteç bağlanmaz (`sentence_other_clause`,
  `nearby_reference_tokens`). Cümlede başka süre ya da değerden sonra (belirtece kadar)
  başka içerik sözcüğü varsa `sentence_shared`. `stored_reference_attributed` yalnız
  `value_window`/`sentence_single_value` ve tam saklı eşleşmede `true`; bu bir saklı
  eşlemedir, dış kaynağın doğrulanması değildir.
- **Yayılım (D5).** `±` yayılımı saate kendi birimiyle çevrilir; sonlu değilse
  `invalid_value`, sıfırdan büyükken 6 ondalıkta 0'a yuvarlanıyorsa
  `value_below_precision` (değer üretilmez). ≈5× nesnesi yayılımı da ×5 taşır
  (`statistic: "not_stated"`; SD/aralık/güven aralığı diye yorumlanmaz, min–max'a
  çevrilmez); sonlu değilse `invalid_dispersion`. Değerin hemen önünde `±`, `+/-`,
  `∓`, `plus or minus`, tek `+`, `SD`, `SEM`, `CI`, `IQR`, `standard deviation of` …
  ya da `4 to` / `4 ±` gibi yarım kalmış aralık varsa → değer üretilmez
  (`dispersion_or_range_form_not_structured`). Değerden sonra yazılan yayılım
  (`4 hours (± 1)`, `4 hours, with a standard deviation of 1 hour`, `(95% CI …)`)
  okunmaz; değer kalır, `dispersion_not_structured` (≈5× yok).
- **Demo hedefi (D6).** `src.timing.demo_guard`: yalnız süreç ortamı; `DO_POSTGRES_URL`
  tanımlı, `postgresql`, sorgusuz, loopback, ad `_synth` ve `M02_DEMO_CONFIRM` ile
  aynı; `PGHOSTADDR`/`PGSERVICE`/`PGSERVICEFILE` ne süreçte ne `run.py`'nin yüklediği
  `.env` dosyalarında tanımlı; salt okunur bağlantıda `current_database()` aynı ve
  sentetik olmayan kullanıcı yok. Aksi halde çıkış 2.

## 8a. İkinci bağımsız inceleme turundan sonra eklenen genel kurallar

- `sentence_keyword` (ölçüm önceki cümle parçasından devralınır) ve `field_only`
  yalnız değerin penceresinde değer, koşul terimleri, referans ve işlev
  sözcüklerinden (`is`, `in`, `and`, `average`, `respectively`, `patients` …)
  başka **içerik sözcüğü kalmıyorsa** geçerlidir; aksi halde süre başka bir olayı
  anlatıyor olabilir (`… but platelet inhibition lasts 7 days`) → inceleme.
- Değerden hemen önce (en çok 2 sözcük arayla) değişim fiili (`delayed`,
  `prolonged`, `increased`, `reduced`, `shortened`, `extended`, `doubled` …) →
  `change_amount`; arada `to` varsa `change_statement`. `from X to Y` için değişim
  fiili cümlenin herhangi bir yerinde olabilir (parantez içi dahil).
- `1 h 30 min` gibi yalnız boşlukla bitişik iki süre → `compound_duration`
  (inceleme); `4 h and 8 h`, `4 h, 8 h` gibi yalnız `and`/`or`/`,` ile ayrılan
  değerler konumsal listedir → `parallel_value_list`.
- İki değer arasında birden çok ayırıcı varsa ve ilk ile son ayırıcı arasında
  koşul terimi geçiyorsa (`… with renal and hepatic impairment, and 8 h …`) ya da
  ayırıcı yoksa (ortadan bölme; sözcük sınırına çekilir), cümlede koşul varsa
  değerler `condition_attribution_ambiguous` alır.
- Giriş ifadesi, karşıtlık bildiren pencereye (`versus`, `compared`, `younger`,
  `controls`, `healthy`, `humans`, `otherwise` …) taşınmaz; giriş ifadesinde
  koşul varsa o değer `condition_attribution_ambiguous` alır.
- `1:30` (saat yazımı) süre değildir; `not/no less than X` alt sınır,
  `no longer/more than X` üst sınırdır (kapsayıcı); parantez içindeki `;` cümle
  parçası sonu değildir; `i.v./p.o./s.c./i.m.`'den sonra boşluk + büyük harf
  cümle sonudur.
- Saate çevrilmiş değer sonlu değilse `invalid_value`, 6 ondalıkta 0'a
  yuvarlanıyorsa `value_below_precision` (asla 0 yayımlanmaz); ×5 sonucu sonlu
  değilse türetilmiş değer hesaplanmaz.
- Nüfus: yaş bandı (`children 2 to 6 years`), `younger patients`, `controls`;
  `other`: `humans`. Çelişki anahtarında `pediatric/paediatric/children`→`child`,
  `geriatric/older adults`→`elderly`.

## 9a. Belirsizlik kararları (bağımsız vaka yazarlarının listesi üzerine)

- İncelemeye giden değerler (virgüllü/sıfır/negatif/ters aralık/ay-yıl/`over`/
  yarılanma ömründe `within`/sayı listesi/sözcükle sayı) **ölçüm üretmez**;
  yalnız inceleme kalemi olur (sayı alanı yok, 0 yok).
- `within` + aralık (`within 1-2 hours`) → `range`.
- Karışık birimli aralıkta `original.unit` üst sınırın birimi, `original.lower_unit`
  alt sınırın birimidir (aynı birimde `null`).
- Yarılanma ömrü için güçlü sözcük, 5'teki yarılanma ömrü sözcüklerinin
  tamamıdır (sözcükle yazılmış sayı → `keyword_without_parsable_value`).
- Dışlanan süreler de pencere bölmede süre sayılır (koşullar pencerelere
  buna göre dağılır); bağımsız incelemeden sonra **yaş ifadeleri** bunun
  dışında tutuldu (bkz. 3).
- Çelişki karşılaştırması saat cinsinden (tür, nokta, alt, üst, `inclusive`)
  üzerindendir; yalnız `approximate` farkı çelişki sayılmaz.
- `[SYNTHETIC]` gibi yalnız harf içeren köşeli ifade referans belirteci değildir
  (belirteç = 1–3 harf + rakam).
- Olası kesilmiş metinde son cümle terminal noktalama ile bitse de diğer
  ölçümler `stored_text_possibly_truncated` ile işaretlenir.
- Tmax zaman referansı yalnız değerin kendi penceresinden veya değerin hemen
  arkasından okunur; başka pencerenin `after ... administration` ifadesi
  taşınmaz.
- Absorption alanında Tmax sözcüğü geçmeyen cümlelerdeki süreler de inceleme
  kalemi olur; bu yüzden böyle bir alan `no_statement_found` değil
  `unparsed_needs_review` olur (temkinli seçim).

## 10. ≈5 × yarılanma ömrü

Her `half_life` ölçümü için ayrı bir `derived` nesnesi. `computed` için hepsi:
ölçüm işaretsiz; analit `metabolite` değil; analit belirtilmemişken alanda
başka yerde metabolit geçmiyor; faz `distribution/alpha/initial/absorption`
değil; faz `terminal/elimination` dışında bir faz (beta, gamma, çok fazlı)
değil; alanda çok fazlı anlatım varken bu ölçümün fazı belirtilmemiş değil;
alanda doğrusal olmayan kinetik ifadesi yok; matris `intracellular/CSF/
tissue/red blood cells/bone` değil; `other` insan dışı tür veya in vitro
değil. Hesap: nokta ×5, aralıkta alt ×5 ve üst ×5 **ayrı**,
tek yönlü sınır ×5 (yön korunur); `±` değerinde merkez ×5, yayılım da ayrı
`dispersion` alanında ×5 taşınır (`statistic: "not_stated"`; aralığa çevrilmez,
bkz. 8b). Tmax eklenmez. Aksi halde `not_computed` + gerekçe kodları:
`measurement_requires_review` (+ ölçümün kendi gerekçeleri),
`metabolite_not_parent`, `analyte_ambiguous_metabolite_mentioned`,
`non_elimination_phase`, `phase_ambiguous_multiphasic`,
`nonlinear_or_dose_dependent_kinetics`, `non_plasma_matrix`,
`non_human_or_in_vitro`.

Varsayım: tek, sabit yarılanma ömrü (birinci derece üstel azalma). 5 yarılanma
ömrü sonunda bu varsayımla başlangıç miktarının ~%3'ü kalır; bu **yaklaşık**
bir süredir. "Tamamen atıldı", "etki bitti" veya "diğer ilaç güvenle
alınabilir" anlamına gelmez; kişisel düzey, doz ve klinik aralık değildir.
