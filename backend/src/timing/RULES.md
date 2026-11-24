# M-02 metin ayrıştırma kuralları (`m02-text-parser/1`)

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
belirteç → `value_window`; cümle sonundaki belirteç ve cümlede tek değer →
`sentence_single_value`; cümle sonundaki belirteç ve birden çok değer →
`sentence_shared` (hangi değere ait olduğu belirlenemez). 
`primary_reference_verified` yalnız `matched` **ve** kapsam `value_window`
veya `sentence_single_value` ise `true`.

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
tek yönlü sınır ×5 (yön korunur); `±` değerinde yalnız merkez ×5 (yayılım
taşınmaz). Tmax eklenmez. Aksi halde `not_computed` + gerekçe kodları:
`measurement_requires_review` (+ ölçümün kendi gerekçeleri),
`metabolite_not_parent`, `analyte_ambiguous_metabolite_mentioned`,
`non_elimination_phase`, `phase_ambiguous_multiphasic`,
`nonlinear_or_dose_dependent_kinetics`, `non_plasma_matrix`,
`non_human_or_in_vitro`.

Varsayım: tek, sabit yarılanma ömrü (birinci derece üstel azalma). 5 yarılanma
ömrü sonunda bu varsayımla başlangıç miktarının ~%3'ü kalır; bu **yaklaşık**
bir süredir. "Tamamen atıldı", "etki bitti" veya "diğer ilaç güvenle
alınabilir" anlamına gelmez; kişisel düzey, doz ve klinik aralık değildir.
