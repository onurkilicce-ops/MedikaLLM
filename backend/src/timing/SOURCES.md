# M-02 zamanlama önerisi kaynak kaydı

Kontrol tarihi: **2026-11-26**. Katalog: `2026-11-26.1`.
Sayfalar açıldı; ilgili tam bölüm, ürün kimliği, yön ve koşul okundu.
Arama özeti veya LLM belleği kanıt olarak kullanılmadı. Bu, uzman kabulü değildir.
Kısa özgün alıntılar tek yerde, `advice.py` içindeki `SOURCES` kayıtlarında tutulur
ve API/ekranda gösterilir. Lisanslı DrugBank metni bu kataloğa eklenmedi.

| Kaynak ve bölüm | Açıkça desteklediği sınırlı kural | Eşleşme şartı |
|---|---|---|
| [emc 4346, SmPC 4.5, Chelation Complex Formation](https://www.medicines.org.uk/emc/product/4346/smpc) | Siprofloksasin, sukralfattan **1–2 saat önce** veya **en az 4 saat sonra**. Yönün öznesi siprofloksasindir. | Ranbaxy/Sun UK 500 mg film kaplı oral tablet; oral sukralfat. Sayfadaki güncelleme: 2026-10-15. |
| [emc 885, SmPC 4.2 Method of administration](https://www.medicines.org.uk/emc/product/885/smpc) (alıntı 4.2'de birebir doğrulandı; 4.5 metni birebir doğrulanmadığı için kaynak gösterilmez) | Siprofloksasin süspansiyonu, **öğün dışında tek başına** süt/yoğurt veya kalsiyumla zenginleştirilmiş içecekten **1–2 saat önce** veya **en az 4 saat sonra**. | Bayer Ciproxin UK 250 mg/5 mL oral süspansiyon. Öğünün parçası olan süt ürününe bu sayısal kural uygulanmaz. Sayfadaki güncelleme: 2026-10-15. |
| [DailyMed, setid 9e588c43-b9b5-478e-99f7-e197add3cd26, 2.1](https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=9e588c43-b9b5-478e-99f7-e197add3cd26) | Levotiroksin sodyum tablet, aç karnına **kahvaltıdan 0,5–1 saat önce**. Kahvaltı sonrasına ters bir süre türetilmez. | Proficient Rx LP / Lannett US 100 mcg oral tablet. Sayfa güncellemesi 2025-08-01; etiket revizyonu 4/2025. |

## Eşleşmenin sınırı

- Veritabanındaki tam etken madde adı yalnız uygun ürün profillerini listeler.
  Ürün profili kendiliğinden seçilmez: profesyonel, ürün/ülke/formülasyon/yolun
  gerçekten eşleştiğini ayrıca belirtir. İstemcinin gönderdiği isim kullanılmaz.
- Aynı etken maddenin farklı ülkedeki veya farklı formülasyondaki ürününe
  genellenmez. UK/US etiketleri Türkiye ürün eşdeğerliğini kanıtlamaz.
- İnceleme sadece bu küçük katalog içindir. `not_in_catalog`, tüm literatürde
  kanıt olmadığı anlamına gelmez; `conditions_required` ise değerlendirme eksiktir.
- `not_applicable` öğün koşulunun bu kurala uymadığını söyler; güvenli birlikte
  kullanım sonucu değildir. Zaman ayırmak diğer etkileşimleri çözmüş sayılmaz.
- Katalog doz seçmez, hastaya kullanım takvimi çıkarmaz. PK değerleri, Tmax,
  yarı ömür veya 5× hesabı hiçbir zaman öneri kaynağı değildir.

## Dışarıda bırakılan kaynak

[DailyMed ciprofloxacin, setid fa32aafd-e3f5-4be6-9413-c7663c1c2cec](https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=fa32aafd-e3f5-4be6-9413-c7663c1c2cec)
açıldı. Bölüm 2.4 ile danışmanlık bölümündeki yön anlatımı arasında sorun
görüldüğü için bu etiket katalogda kullanılmadı. UK ve US aralıkları birleştirilmedi.
Kaynak değişirse etkilenen kural, uzman değerlendirmesi ve katalog sürümü birlikte
yeniden ele alınmalıdır; çalışma anında sessiz güncelleme yapılmaz.

## Doğrulama

`test_m02_advice.py`: yön, giriş sırasından bağımsız özne, koşul eksikliği,
yanlış ürün profili, öğün istisnası, ters yön üretmeme, kanıtsız çift ve teknik hata.
`test_m02_completion_pg.py`: gerçek PostgreSQL üzerinden aynı API sözleşmesi.
`frontend/e2e/timing.flow.jsx`: React DOM → gerçek HTTP → bu servis → sentetik PG.
Testlerdeki ilaç kimliği ve PK metinleri sentetiktir; klinik doğruluk oranı değildir.
