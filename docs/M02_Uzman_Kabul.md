# M-02 uzman kabulü: aday küme ve kayıt yöntemi

**Durum: öneri; uzman tarafından onaylanmadı, değerlendirme yapılmadı.**
Form A imzasız taslaktır. Mevcut M-02 hedefi, önceden belirlenen örneklerde
değer/kaynak ve zamanlama/uzman uyumunun en az %90 olmasıdır; bu hedef düşürülmedi.
Aşağıdaki adaylar uygulama testi değildir ve sonuç görülerek kolaylaştırılamaz.

## Değerlendirmeden önce dondurulacak bilgiler

Uzman, her aday için ürün/ülke, uygulama yolu, formülasyon, popülasyon, ilaçların
kimliği, özgün kaynak/bölüm ve beklenen cevapları uygulama çıktısını görmeden
kaydeder. Yetkili DrugBank metni yerel, erişimi sınırlı değerlendirme dosyasında
tutulur; Git'e lisanslı metin veya hasta verisi girmez. Sadece sentetik profiller
kullanılır. Kümenin tarihi, hash'i, uzman onayı ve payda tanımı sonradan değiştirilmez.

| Aday | Değerlendirilecek durum | Referansın durumu |
|---|---|---|
| PK01 | İki ilaç; dakika/saat birimleri, tek Tmax ve yarı ömür | Uzman ürün/kaynak seçmeli |
| PK02 | Dakika–saat karışık aralık; alt/üst sınır korunması | Uzman ürün/kaynak seçmeli |
| PK03 | Gün biriminde uzun yarı ömür ile kısa süreyi aynı çizelgede okuma | Uzman ürün/kaynak seçmeli |
| PK04 | Aynı ilaçta iki formülasyonun farklı değerleri | Uzman ürün/kaynak seçmeli |
| PK05 | Sağlıklı yetişkin ve organ yetmezliği koşulları | Uzman ürün/kaynak seçmeli |
| PK06 | Metabolit/faz değeri; 5× uygulanmaması | Uzman ürün/kaynak seçmeli |
| PK07 | Yarı ömür veya Tmax eksik; sıfır/güvenli sonucuna dönmemesi | Uzman ürün/kaynak seçmeli |
| PK08 | Belirsiz, olumsuz, karşılaştırılan ilaca ait metin | Uzman ürün/kaynak seçmeli |
| PK09 | ± yayılım, sınır değer, belirsizlik ve 5× ayrımı | Uzman ürün/kaynak seçmeli |
| PK10 | Değere ait kaynak ile başka iddianın yakındaki kaynağı | Uzman ürün/kaynak seçmeli |
| T01 | UK siprofloksasin tablet + oral sukralfat: iki yön | SOURCES.md'deki ürün/bölüm; uzman değerlendirmesi bekliyor |
| T02 | UK Ciproxin süspansiyon + öğün dışında süt/yoğurt | Aynı durum |
| T03 | Aynı süspansiyon + öğünün parçası süt ürünü | Aynı durum; kuralı genellememe |
| T04 | US levotiroksin tablet + kahvaltı | Aynı durum; ters yön türetmeme |
| T05 | Ürün/formülasyon bilinmiyor veya kaynakla uyuşmuyor | Uzman beklenen çekimserliği belirlemeli |
| T06 | Katalog dışında ilaç–ilaç ve ilaç–gıda çifti | Eksik kapsamı başarı diye saymama |

## Her örnek için kayıt şablonu

```text
Örnek kimliği / küme sürümü / uzman / onay tarihi:
İlaç kimlikleri / ürünler / yol / formülasyon / popülasyon / öğün koşulu:
Yetkili yerel kaynak konumu / erişim tarihi / metin hash'i:
Uygulamadan ÖNCE kaydedilen beklenen değer-aralık-birim, koşul, özne, kaynak:
Beklenen öneri: özne / diğer öğe / önce-sonra / süre / geçerlilik şartı:
Beklenen çekimserlik varsa gerekçesi:
Uygulama commit SHA / parser ve katalog sürümü / test tarihi:
Gerçek çıktı ve kaynak eşlemesi:
Sonuç: doğru cevap / yanlış cevap / yanıt yok (çekimser) / teknik hata
Yanlış temiz sonuç var mı? (evet/hayır; sayı ve gerekçe):
Veri kapsamı: mevcut / eksik / ayrıştırılamayan / ürün-koşul eksik / katalog dışı
Uzman kararı / açıklama:
```

## Payda ve karar

- Değer/kaynak ve zamanlama/uzman uyumu ayrı ölçülür. Birbirini örtemez.
- Her küme için toplam önceden dondurulmuş **N**, doğru **D**, yanlış **Y**,
  çekimser **Ç**, teknik hata **H** ayrı verilir; `N = D + Y + Ç + H`.
- Referans yanıt gerektirdiği halde eksik/ayrıştırılamayan/katalog dışı kalan
  örnekler paydadan çıkarılmaz. Ana uyum `D/N` olarak raporlanır.
- Referansın açıkça çekimserlik istediği örneklerde doğru çekimserlik ayrıca
  sayılır; bu örneklerin ağırlığını uzman önceden onaylar. Yanıt kapsaması
  `(D + Y)/N` ve yanlış temiz sonuç sayısı ayrıca gösterilir.
- Yazılım testleri veya sentetik testlerin geçme oranı bu %90 ölçümünün yerine
  geçmez. Uzman onayı yokken sadece teknik hazır olma değerlendirilebilir.
