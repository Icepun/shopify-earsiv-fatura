# CLAUDE.md — Shopify → GİB e-Arşiv fatura otomasyonu

Bu dosya, projede çalışacak Claude oturumları içindir. Kullanıcı **Türkçe**
konuşuyor; yanıtları Türkçe ver.

## Kullanıcı ve bağlam

- Mağaza: **Magicland 3D** (`magicland-3d.myshopify.com`), Shopify Basic, TRY.
- 3D baskı ürünleri satıyor, ayda ~100 sipariş, ortalama ~640 TL.
- **Şahıs şirketi.** e-Fatura mükellefi *değil* → kestiği belge **e-Arşiv fatura**.
- e-Ticaret için e-Fatura geçiş haddi **500.000 TL**; 2026 cirosu ~56.000 TL
  olduğu için eşiğin çok altında. Eşiği aşarsa e-Arşiv Portal kapanır ve özel
  entegratöre (Nilvera/Paraşüt vb.) geçmesi gerekir.
- Fatura kesme yöntemi: ücretsiz **GİB e-Arşiv Portal**, entegratör yok.

## Amaç

Portalda tek tek form doldurmayı bitirmek. Akış (26.08.2026'dan itibaren):
siparişleri Shopify'dan çek → panelde gözden geçir/düzelt → **UBL-TR XML
üret** → Hepsiburada e-Faturam portalına toplu yükle → onayla → Shopify'da
`faturalandi` etiketle.

**GİB e-Arşiv Portal artık kullanılmıyor.** Kullanıcı zaten Hepsiburada
satıcısı ve e-Faturam portalını kullanıyor; oraya XML yüklemek GİB'de SMS
imzalamaktan basit. `gib.py` ve `payload.py` duruyor ama panele bağlı değil —
GİB'e dönülürse diye saklanıyor, oradaki protokol bilgisi zor kazanıldı.

## Mimari

```
masaustu.py            uygulama giriş noktası: pencere + gömülü sunucu
derle.py               PyInstaller ile tek dosyalık .exe üretir
yayinla.py             .exe'yi GitHub Releases'e yükler
fatura/config.py       ayarlar (ayarlar.json; yoksa .env'den devralır)
fatura/shopify_api.py  Admin GraphQL: sipariş çekme, tekil arama, etiketleme
fatura/donustur.py     sipariş -> Fatura (KDV ayrıştırma, kargo dağıtımı, uyarılar)
fatura/ubl.py          Fatura -> UBL-TR 1.2 e-arşiv XML'i  ← ASIL ÇIKTI
fatura/depo.py         SQLite: durum, belge geçmişi, fatura numarası sayacı
fatura/tek_ornek.py    aynı anda tek kopya çalışsın (Windows kilidi)
fatura/guncelleme.py   GitHub Releases: sürüm kontrolü, indirme, kendini değiştirme
fatura/web.py          FastAPI panel sunucusu
static/index.html      panel: liste → önizleme → XML (vanilla JS, tek dosya)
fatura/gib.py          KULLANILMIYOR — eski GİB e-Arşiv Portal istemcisi
fatura/payload.py      KULLANILMIYOR — eski GİB payload üreticisi
```

Katmanlar bilinçli olarak ayrık: entegratöre geçilecek olursa yalnızca
`gib.py` değişir, hesap mantığı aynen kalır.

## Hepsiburada e-Faturam — UBL-TR XML (26.08.2026)

Biçim, kullanıcının kendi hesabından indirdiği gerçek bir faturadan
(`INT2026000000361`) çıkarıldı ve **canlı yükleme ile doğrulandı**.

- `ProfileID = EARSIVFATURA`, `CustomizationID = TR1.2`, `UBLVersionID = 2.1`
- Miktar birimi **NIU** (GİB portalındaki `C62` değil)
- Tutar yazıyla: `Yalnız #Üç Yüz Yetmiş Dokuz Türk Lirası Doksan Dokuz Kuruş#`
  — `#` sınırlayıcılar ve boşluklu kelimeler şart, örnekle birebir eşleşiyor
- `CityName` = il, `CitySubdivisionName` = ilçe
- Nihai tüketici alıcı TCKN'si `11111111111`
- **Eleman sırası UBL şemasında bağlayıcı** — `ubl.py`'deki sıra örnekten
  birebir alındı, oynatma
- **İmzasız gönderiyoruz.** İmzayı portalın entegratörü (Uyumsoft) atıyor;
  `UBLExtensions`, `cac:Signature` ve XSLT eki üretilmiyor, portal kabul etti
- Yüklenen fatura portala **Taslak** olarak düşüyor; kullanıcı orada gözden
  geçirip "Gönder" diyor
- **Her ETTN bir kez kabul ediliyor.** Taslak portaldan silinse bile aynı
  UUID tekrar yüklenemez ("aynı UUID'ye sahip ve taslak durumunda olmayan bir
  fatura zaten sistemde mevcut"). Yeniden denemek gerekirse yeni UUID üret.
- Fatura numarası bizde: `SERI + YIL + 9 hane` (`MGL2026000000001`).
  Hepsiburada'nın kendi `INT` serisiyle çakışmasın diye ayrı seri.
  Sayaç veritabanında — bkz. "Fatura numarası sayacı".
- Üretim anında `depo.belge_uret()` çağrılıyor: yükleme başarılı olup
  etiketleme unutulursa iz kalmazsa aynı siparişe ikinci fatura üretilir.

## Fatura numarası sayacı (12.10.2026, 1.5.0)

Sayaç artık `ayarlar.json`'da değil veritabanında: `sayac` tablosu, anahtar
`SERI+YIL` (`MGL2026 -> 182`). **Yıl değişince yeni anahtar açılır, sıra
1'den başlar**; numaradaki yıl fatura tarihinin yılıdır (bugünün değil).

`depo.belge_uret()` numarayı alır, XML'i yazdırır ve kaydı düşer — **tek
SQLite işleminde** (`BEGIN IMMEDIATE`). Hata olursa geri sarılır: numara
harcanmaz, yarım kayıt kalmaz. Parti ortasında hata çıkarsa o ana kadar
üretilenler geçerlidir, yanıtın `hata` alanı kalanları bildirir.

Eskiden üç ayrı yoldan aynı numara iki kez verilebiliyordu; hepsi kapandı:

- **Ayarlar formu sırayı her kayıtta gönderiyordu.** Form açılıştaki değeri
  tuttuğu için, fatura ürettikten sonra Kaydet ya da "Bağlantıyı Sına"
  sayacı geri sarıyordu. Artık sıra yalnızca elle değiştirilince gider
  (`yuklenenSira` karşılaştırması) ve form her açılışta tazelenir.
- **Sıra parti sonunda kaydediliyordu.** Ortada hata olursa dosyalar yazılmış
  ama sıra ilerlememiş oluyordu.
- **Sıra bellekten okunuyordu.** İki kopya açıkken ikisi de aynı numaradan
  devam ediyordu.

Ek güvenceler: `belgeler.belge_no` birincil anahtar (aynı numara iki kez
yazılamaz) ve sayaç ne derse desin **verilmiş en büyük numaranın altından
devam edilmez** (`_son_sira`). Ayarlardan sırayı düşürmek bu yüzden
reddedilir; yükseltmek serbesttir.

`ayarlar.json > fatura_sira` yalnızca **yedek**: her partiden sonra
güncellenir, `sayac` tablosu boşsa (ilk geçiş ya da silinmiş veritabanı)
sayaç oradan devralınır.

**Numaralar eskiden yeniye verilir.** Liste yeniden eskiye sıralı olduğu
için eskiden belge numarası büyürken fatura tarihi geriye gidiyordu;
`xml_uret` artık partiyi sipariş zamanına göre sıralıyor.

### Belge geçmişi

`belgeler` tablosu üretilen her XML'in kalıcı izidir (`uretildi` |
`yuklendi` | `iptal`). Yeniden üretme ve geri alma satır silmez, `iptal`
yapar. `faturalar` tablosu ise siparişin şu anki durumudur (sipariş başına
tek satır).

Bu olmadan önce yeniden üretim eski numarayı iz bırakmadan eziyordu:
gerçek veritabanında `MGL2026000000165–173` böyle kayboldu.

## GİB protokolü — zor kazanılmış bilgiler (ARTIK KULLANILMIYOR)

Bunlar GİB test ortamında **canlı denenerek** bulundu. Dokümante değil.

1. **`faturaUuid` BOŞ gönderilmeli.** ETTN'i portal kendisi atar. Kendi UUID'ini
   koyarsan `"Ettn ya eksik ya boş ya da 36 uzunluk sınırına uymuyor"` hatası
   gelir — mesaj yanıltıcıdır, UUID geçerli olsa bile reddedilir.
2. **Yanıtta ETTN dönmez.** Hangi taslağın hangi siparişe ait olduğu, oluşturma
   öncesi/sonrası taslak kümesi farkından ve `belgeNumarasi` sırasından
   eşleştirilir (`web.py > taslak_olustur`). Taslak kaydında `siparisNumarasi`
   alanı **yoktur**; sadece şu 7 alan döner:
   `belgeNumarasi, aliciVknTckn, aliciUnvanAdSoyad, belgeTarihi, belgeTuru, onayDurumu, ettn`
3. **`json.dumps(jp)` — `ensure_ascii=True` bırak.** Değiştirme.
4. **Taslak oluşturmak SMS istemez; sadece imzalamak ister.** `SMSSIFRE_DOGRULA`
   komutu `DATA` olarak bir taslak **listesi** alır → tek kodla toplu imza.
   Toplu kesim tamamen buna dayanıyor.
5. **Legacy TLS gerekli.** `ssl` bağlamında `OP_LEGACY_SERVER_CONNECT` (0x4)
   açılmazsa bağlantı kurulmaz. Bkz. `gib._ssl_baglami()`.
6. Uçlar: `POST /earsiv-services/assos-login` (token), `POST /earsiv-services/dispatch`
   (`cmd` + `callid` + `pageName` + `token` + `jp`). Üretimde `assoscmd=anologin`,
   testte `login`.

## Shopify kimlik doğrulaması — değişti (21.08.2026)

Shopify **artık Admin içinden `shpat_...` veren "admin-created custom app"
açtırmıyor** (doküman: *"You can no longer create new admin-created custom
apps"*). Mevcut olanlar çalışmaya devam ediyor.

Bu proje için doğru yol **client credentials grant**: uygulama Dev
Dashboard'da açılır, `POST https://{magaza}/admin/oauth/access_token` ucuna
`client_id` + `client_secret` + `grant_type=client_credentials` gönderilir,
karşılığında **24 saatlik** bir erişim tokeni alınır. Token yine
`X-Shopify-Access-Token` başlığıyla kullanılır, GraphQL tarafı aynı.

- İstemci kimliği/gizli anahtarı **doğrudan GraphQL'e gönderme** — "Invalid
  API key or access token" alırsın. Önce takas et.
- Token `shopify_api._token_deposu` içinde modül düzeyinde saklanıyor. Panel
  her istekte yeni `Shopify()` kurduğu için önbellek nesnede değil modülde
  olmak zorunda.
- Süre dolmadan 5 dk önce yenileniyor; ayrıca 401 gelirse önbellek atılıp
  bir kez yeniden deneniyor (panel gece boyu açık kalabilir).
- **Uygulama ile mağaza aynı organizasyonda olmalı**, yoksa
  `shop_not_permitted`. Mağazanın Dev Dashboard > Dev stores altında
  görünmesi gerekiyor; Admin'den açılmış mağazalar organizasyona dahil
  olmayabiliyor.
- `SHOPIFY_TOKEN` dolu ise takas atlanır — eski tokenler için geri uyumluluk.

## Para hesabı — bozma

Shopify fiyatları KDV **dahil** tutar, fatura KDV hariç matrah ister. Her şey
`Decimal`; float kullanılmıyor. Korunması gereken üç kural:

```
birimFiyat x miktar = malHizmetTutari
malHizmetTutari x kdvOrani = kdvTutari
toplam matrah + toplam KDV = odenecekTutar
```

Kargo, kullanıcının kararıyla **ayrı satır değil** — net tutarı ürün satırlarına
tutar oranında dağıtılır, artık son satıra yazılır (`KARGOYU_DAGIT=true`).
Fatura toplamı ile tahsilat arasındaki kuruş farkı gizlenmez, `Fatura.sapma`
olarak panele "sapma" rozetiyle taşınır.

### İndirim tahsisleri — `discountedTotalSet` KULLANMA (21.08.2026'da bulundu)

Satır net tutarı **`originalTotalSet` eksi `discountAllocations` toplamı**
olarak hesaplanır. Sebep, canlı veriyle bulundu:

`lineItem.discountedTotalSet` yalnızca **satır bazlı** indirimi yansıtıyor
(`discountApplications.allocationMethod == "EACH"`). Sipariş geneline yayılan
indirim (`allocationMethod == "ACROSS"` — ör. "%25 kupon") o alanda **hiç
görünmüyor**; satır indirimsizmiş gibi duruyor, `totalDiscountSet` bile 0.00.
`discountAllocations` ise her iki türü de içeriyor.

Eski kod `discountedTotalSet` kullanıyordu ve **faturayı tahsilattan yüksek
kesiyordu**. 54 gerçek siparişte 9'unda sapma vardı; en büyüğü **#1060'ta
467.49 TL** (fatura 1869.97 / tahsilat 1402.48). Düzeltmeden sonra büyük sapma
sıfır: 41 sipariş tam 0.00, 13 sipariş 1–2 kuruş (birim fiyat ekseninde KDV
ayrıştırma + kargo dağıtımının kaçınılmaz yuvarlaması).

Doğrulama: `originalTotalSet − tahsisler` toplamı, siparişin
`currentSubtotalPriceSet` değerine birebir eşit çıkıyor.

Adres: Shopify'da Türkiye adresleri düzensiz (`province` genelde `null`, `city`
bazen ilçe adı). Şehir, **posta kodunun ilk iki hanesinden** (plaka kodu)
türetiliyor — "Milas / 48200" → Muğla ili + Milas ilçesi. Telefonlar 10 haneye
normalize ediliyor.

**İl adı karşılaştırmaları `donustur.duz()` ile yapılır, `casefold()` ile
değil.** Shopify bazı illeri Türkçe harfsiz gönderiyor (`Istanbul`, `Izmir`);
`casefold()` İ/ı ayrımını koruduğu için bunlar il olarak tanınmıyor, ilçe
sanılıp faturaya ilçe diye yazılıyordu (166 siparişin 25'inde).

**İlçe boş olabilir** — portal adresi yazıldığı gibi kabul ediyor (kullanıcı
teyidi, 12.10.2026). Siparişlerin %58'inde müşteri ilçeyi ayrı yazmıyor; bu
yüzden önizlemede ilçe "eksik" sayılmıyor. İlçe doğrulaması ekleme.

## Saat dilimi (12.10.2026)

Shopify `createdAt` değerini **UTC** verir. `donustur.yerel_zaman()` onu
Türkiye saatine (`config.TURKIYE`, sabit UTC+3) çevirir; fatura tarihi ve
saati buradan çıkar. Çevrilmeden kullanıldığında gece 00:00–03:00 arası
verilen siparişlerin faturası bir gün önceye düşüyordu (170 siparişin 9'u;
#1148 ay sınırını aşıp Ekim yerine Eylül'e yazılıyordu).

Tarih filtresi de aynı şekilde: `shopify_api._gun_siniri()` günün Türkiye
saatiyle başını/sonunu UTC'ye çevirip sorguya koyar.

## Test etme

GİB'in herkese açık test hesabı: kullanıcı kodu `33333301`, şifre `1`,
`GIB_TEST_MODU=true`. Test ortamında **SMS imzalama çalışmaz** (kayıtlı telefon
yok) — 1. ve 2. adım doğrulanabilir, 3. adım doğrulanamaz.

Test kayıtları `fatura-test.db`'ye, gerçekler `fatura.db`'ye yazılır; test
denemeleri gerçek siparişleri "faturalandı" saymaz.

**Test ortamı paylaşımlıdır.** Oraya gerçek müşteri adı/adresi/telefonu
gitmesin diye `payload._test_kimligi()` artık `GIB_TEST_MODU=true` iken alıcı
ad/soyad/ünvan, adres, telefon, e-posta ve TCKN alanlarını uydurma değerlerle
değiştiriyor. **Tutarlar, il/ilçe ve posta kodu aynen kalır** — hesap ve adres
türetme yine baştan sona doğrulanabilsin diye. Yani panel test modunda gerçek
siparişlerle güvenle çalıştırılabilir.

Sandbox'ın ne kadar başıboş olduğunun kanıtı: `33333301` hesabının ünvanına
başkası küfür yazmış durumda. Oraya hiçbir gerçek veri gönderme.

**GİB tek oturuma izin verir.** İkinci bir giriş denemesi şu hatayı alır:
`"Sisteme aynı anda birden fazla giriş yapamazsınız."` Bu sadece test
ortamının derdi değil — **gerçek çalıştırmada da tarayıcıda e-Arşiv Portal
açıksa panel giriş yapamaz.** Panelden önce portaldan "Güvenli Çıkış" yap.
Oturum sunucu tarafında bir süre daha açık kalabiliyor; `kapat()` çağrılsa
bile hemen serbest kalmayabilir.

`33333301` çoğu zaman başkası tarafından kullanımda oluyor. `33333302`
(şifre yine `1`, mükellef "Kaya a.ş", VKN 3333333302) alternatif olarak
çalıştı — 333333xx aralığındaki diğer kodlar da denenebilir.

**`fatura_sil` test ortamında çalışmıyor.** Payload'ın her varyantı
(`belgeTarihi` gg/aa/yyyy, `hangiTip` ekli, sadece ettn+belgeNumarasi, tekil
sözlük) `"Silinirken bir sorun oluştu."` dönüyor; taslak duruyor. Onaylanmamış
taslak olmasına rağmen. Bu yüzden test ortamında bıraktığın taslaklar
temizlenemeyebilir — mümkün olduğunca az taslak oluştur.

## Bilinen eksikler / muhtemel sıradaki işler

- **Geçmiş siparişler — çift fatura riski YOK (21.08.2026 teyidi).** Kullanıcı
  Shopify siparişleri için bugüne kadar *hiç* fatura kesmedi; faturalamaya
  doğrudan bu araçla başlıyor. Elle faturalanmış sipariş olmadığı için toplu
  `faturalandi` etiketleme betiğine gerek kalmadı — bu madde kapandı.
  Yerine geçen asıl soru **birikmiş sipariş yığını**: ilk çalıştırmada
  mağazanın o güne kadarki bütün ödenmiş siparişleri listeye düşecek.
  Bunların geçmiş tarihli faturalanıp faturalanamayacağı bir **mevzuat
  sorusudur** (e-Arşiv faturasının düzenlenmesi için bir süre sınırı var);
  kesin konuşma, mali müşavire sordur. `donustur.py` faturaTarihi'ni
  siparişin `createdAt` alanından alır, yani yığın faturalanırsa faturalar
  geçmiş tarihli düzenlenir — kullanıcı bunu bilerek karar vermeli.
  Tarih filtresi bu yüzden eklendi (21.08.2026) — amacı çift faturayı
  önlemek değil, birikmiş yığını küçük partilere bölmek.
- **Shopify 60 gün penceresi:** uygulamalar varsayılan olarak yalnızca son
  60 günün siparişlerini okur. Daha eskisi gerekiyorsa `read_all_orders`
  izni eklenmeli.
- **İade/iptal:** kısmi iade `currentQuantity` ile orantılanıyor ama iade
  faturası (`iadeTable`) desteklenmiyor.
- ETTN eşleştirmesi aynı anda başka bir oturumdan fatura kesilirse kayabilir;
  panel bu durumda uyarı veriyor ama isim bazlı doğrulama eklenebilir.
- Panelde imzalanmış faturaların PDF'ini indirme yok (`gib.indirme_linki` hazır).
- **`fatura-test.db` dosyasını SİLME — kurulu uygulamada gerçek kayıtlar
  orada.** `gib_test_modu` varsayılanı True ve arayüzde artık düğmesi yok,
  bu yüzden Hepsiburada akışının bütün kayıtları (belge geçmişi ve sayaç
  dahil) `fatura-test.db`'ye yazılıyor; `fatura.db` eski ve boşa yakın.
  Ad yanıltıcı; dosyayı `fatura.db`'ye taşımak yapılacaklar listesinde.

## Masaüstü uygulaması (21.08.2026'da eklendi)

**Uygulamayı yalnızca Berke kullanıyor** (12.10.2026; başta Simay için
tasarlanmıştı). Yine de `.bat` yok, konsol yok, dosya düzenlemek yok;
arayüz metinleri kısa ve sade kalır.

Kurulu kopya `%LOCALAPPDATA%\Programs\Magicland Fatura\` altında; veritabanı,
ayarlar, `faturalar/` ve günlükler de orada (.exe'nin yanı).

**Tek kopya çalışır** (`tek_ornek.kilidi_al()`): açılış birkaç saniye
sürdüğü için simgeye ikinci tıklama ikinci bir uygulama açıyordu. İkinci
kopya artık açık pencereyi öne getirip çıkar. Kilit duruyor ama 15 sn
içinde pencere çıkmıyorsa önceki kopya takılmış sayılır ve açılış devam
eder — güncelleme sonrası "kapat-aç" sırasında kullanıcı uygulamasız
kalmasın diye.

- **Kabuk:** `masaustu.py` — uvicorn'u arka planda **boş bir portta** açar
  (8787 sabit değil; dolu olabilir), pywebview penceresinde gösterir.
  Sunucu hazır olana kadar animasyonlu açılış ekranı gösteriliyor.
- **Paketleme:** `derle.py` → PyInstaller `--onefile --windowed`. Tek dosya
  şart: güncelleme mekanizması çalışan .exe'nin adını değiştirip yerine
  yenisini koyuyor, çok dosyalı dizinde bu işe yaramaz.
- **static/ yolu:** paketliyken `sys._MEIPASS` altına açılıyor;
  `config.kaynak_klasoru()` bunu çözüyor. `__file__` güvenilir değil.
- **Veri yeri:** paketliyken `%APPDATA%\Magicland Fatura` (ayarlar.json +
  .db). Kaynaktan çalışırken proje klasörü — geliştirme akışı bozulmasın.
  onefile geçici klasörü her kapanışta silindiği için oraya yazılamaz.

### Ayarlar artık .env değil

`ayarlar.json` asıl kaynak. `ayarlar.json` yoksa bir kereliğine `.env`'den
devralınıyor (mevcut kurulumlar bozulmasın). `config` modülündeki BÜYÜK_HARF
adlar duruyor; `_globalleri_tazele()` onları yerinde güncelliyor, bu yüzden
ayar kaydetmek **yeniden başlatma gerektirmiyor**.

- Gizli alanlar (`GIZLI_ALANLAR`) arayüze **hiç gönderilmiyor**; yalnızca
  "dolu mu" bilgisi gidiyor. Kullanıcı alanı boş bırakırsa eski değer korunur.
- `POST /api/ayarlar` kaydettikten sonra Shopify token önbelleğini ve açık
  GİB oturumunu bırakıyor; test modu değişmişse veritabanı başka dosyaya
  kaydığı için `depo.hazirla()` yeniden çağrılıyor.

### Güncelleme

Public depo `Icepun/shopify-earsiv-fatura`, GitHub Releases API. Yeni sürüm
için: `config.SURUM`'u yükselt → `derle.py` → `vX.Y.Z` etiketiyle release,
.exe'yi ekle.

Windows çalışan .exe'nin **üzerine yazdırmaz** ama **adını değiştirtir**:
`Uygulama.exe -> Uygulama.eski.exe`, `Uygulama.yeni.exe -> Uygulama.exe`.
Artık dosya sonraki açılışta `eski_surumu_temizle()` ile siliniyor.

İndirme arka planda; ilerleme `/api/guncelleme/durum` ile yüzde olarak
okunuyor (belirli ilerleme çubuğu). `httpx.stream`'e **timeout=None verme** —
ağ takılınca indirme %0'da sonsuza kadar asılı kalıyor ve kullanıcı hiçbir
şey görmüyordu; şimdi connect/read sınırı + 3 deneme var.

### Uygulama kendini yeniden başlatmıyor — bilerek

Dosya değiştirildikten sonra kullanıcıya "kapatıp yeniden açın" deniyor.
Otomatik yeniden başlatmanın **dört yolu denendi, dördü de tutmadı**
(Windows 11, PyInstaller onefile, penceresiz):

| Yöntem | Sonuç |
|---|---|
| `os.startfile(exe)` | Yeni örnek açılıyor ama PyInstaller "Error" kutusuyla ölüyor — eski sürüm hâlâ ayakta |
| `subprocess.Popen(..., DETACHED_PROCESS)` | Yardımcı süreç biz kapanınca birlikte ölüyor |
| `cmd /c start "" exe` | Aynı şekilde ölüyor |
| Bekleyip açan `.cmd` + `os.startfile(show_cmd=0)` | `.cmd` sonuna kadar çalışıyor (kendini siliyor) ama başlattığı uygulama ayağa kalkmıyor |

İzole testte `os.startfile` ile açılan çocuk süreç ebeveyn `os._exit(0)`
yaptıktan sonra **yaşıyor** — yani mekanizma değil, uygulamanın kendi
başlangıcı takılıyor. Tekrar denemeye kalkarsan `guncelleme.log`'a bak,
körlemesine uğraşma.

Tek çift tıklamaya değmez; kullanıcıya söylemek sıfır riskli ve her seferinde
çalışıyor (1.0.14 -> 1.0.15 ile uçtan uca doğrulandı).

### `private_mode` kapatma

`webview.start()` çağrısında `private_mode=False` **verme**. Kapalıyken
WebView2 sabit bir profil klasörü kullanıyor ve aynı anda iki örnek
açılamıyor. Varsayılan (True) her örneğe kendi geçici klasörünü veriyor.
Kalıcı veri zaten sunucu tarafında.

.exe **imzalı değil** — Windows SmartScreen ilk açılışta "bilinmeyen
yayımcı" diyecek. Kod imzalama sertifikası alınmadıkça bu sürecek.

## Fatura tarihi — parti bazında seçiliyor

Mali müşavir, **birikmiş geçmiş siparişlerin bugünün tarihiyle** kesilmesini
istedi; bundan sonrakiler siparişin kendi tarihiyle gidiyor. Bu yüzden
önizleme ekranında "Fatura tarihi: Siparişin kendi tarihi / Bugün" seçimi var
(`TaslakIstegi.bugun_tarihli`, `ubl_fatura(belge_tarihi=..., belge_saati=...)`).

**Faturadaki iki tarih daima aynı olur** — `IssueDate` ve
`OrderReference/IssueDate`. Kullanıcının portalda kestiği mevcut faturalarda
da öyle. Siparişin gerçek tarihini faturaya ayrıca yazmıyoruz; hangi siparişe
ait olduğu `OrderReference/ID`'deki sipariş numarasından belli.

## Yanlış kesilen faturayı geri alma

`/api/faturayi-geri-al`: Shopify'daki `faturalandi` etiketini kaldırır
(`tagsRemove`) ve belgeyi geçmişte `iptal` yapar (`depo.geri_al`). Sipariş
yeniden "bekliyor" olur ve **yeni belge numarası + yeni ETTN** ile tekrar
üretilir — portal aynı UUID'yi ikinci kez kabul etmiyor; eski numara da bir
daha verilmez.

Panelde faturalanmış satırlar seçilebilir ama "Gözden Geçir" onlar için
kapalı; yalnızca "Faturayı Geri Al" çalışır.

**Portaldaki taslağı silmek kullanıcının işi** — bu uç yalnızca bizim tarafı
temizler. Taslak değil de gönderilmiş bir fatura söz konusuysa yeniden kesmek
çift fatura demektir; o bir mevzuat sorusudur, mali müşavire sorulmalı.

## Sipariş gizleme

Deneme siparişleri listeyi kirletmesin diye kalıcı gizleme var:
`depo.gizlenenler` tablosu, `/api/gizle` ve `/api/gizlemeyi-kaldir`.
Gizlenenler listeye hiç düşmez; "Gizlenenleri göster" işaretlenince
`gizli` rozetiyle görünür ve tek tıkla geri alınır.

Fatura durumundan ayrı tutuluyor — gizlemek fatura kesmek değil, ve
yanlışlıkla gizlenen bir siparişin kurtarılabilmesi gerekiyor.

## Ayarların saklanması — iki konum

Kullanıcının makinesinde `%APPDATA%\Magicland Fatura` içindeki ayar
dosyaları **zaman zaman görünmez oldu**: uygulamanın açılış günlüğü
`dosya_var=False` derken aynı dosya diskte duruyordu. Defender tehdit kaydı
yok, kontrollü klasör erişimi kapalı, OneDrive çalışmıyor — sebep
bulunamadı, bu makineye özgü bir şey.

**Büyük olasılıkla açıklaması (12.10.2026):** Claude masaüstü uygulaması
MSIX paketi; Claude oturumundan başlatılan her süreç `%APPDATA%` altını kendi
özel kopyasına yönlendirilmiş görüyor
(`%LOCALAPPDATA%\Packages\Claude_…\LocalCache\Roaming\Magicland Fatura`).
Oturumdan yazılan ayar dosyasını Gezgin'den açılan uygulama görmez, tersi de
geçerli: aynı yolda oturum `sira=80`, gerçek uygulama `sira=182` görüyordu.
Yani dosya "kaybolmuyordu"; iki süreç farklı dosyaya bakıyordu. **Claude
oturumundan `%APPDATA%`'ya ya da kurulum klasörüne yazarak test etme** —
gerçek uygulama onu görmez. Kurulum klasörünü salt-okunur oku, denemeleri
yalıtılmış bir klasörde yap (`config.ayar_konumlari`'nı geçici olarak
değiştirerek).

`config.ayar_konumlari()` iki yer döner: **.exe'nin yanı**
(birincil, veritabanı da orada) ve **APPDATA** (ikincil). `kaydet()` her
ikisine de yazar, `yeniden_yukle()` dördüne birden bakar
(ayarlar + yedek × 2 konum) ve dolu olan ilkini alır.

Ek korumalar:
- `KORUNAN_ALANLAR`: kimlik alanları boş gelirse **eski değer korunur**.
  Boş bir formu kaydetmek eskiden her şeyi siliyordu.
- `ayarlar.yedek.json`: dolu her kayıtta yazılır.
- Yazma atomik: geçici dosya + `os.replace`.
- `baslangic.log`: her açılışta hangi konumda ne bulunduğu yazılır.
  Yine olursa **önce buraya bak**.

## Panel akışı — üretilip işaretlenmemiş faturalar (12.10.2026)

XML'i üretilmiş ama "faturalandı" diye işaretlenmemiş sipariş yerelde
`faturalar.durum='taslak'`, listede **"XML üretildi"** rozetiyle görünür.
Shopify'da henüz etiketi olmadığı için sipariş sorgusundan dönmeye devam
eder.

Eskiden bu satırlar da kendiliğinden seçiliyordu ve listeden "işaretle"
demenin yolu yoktu: 3. adımı işaretlemeden kapatan kullanıcının tek çıkışı
aynı siparişi yeni numarayla yeniden üretmekti (165–173 böyle yandı).
GİB dönemindeki "Bekleyen taslaklar" kutusu Hepsiburada geçişinde
arayüzden düşmüş, yalnız `/api/bekleyenler` ucu kalmıştı.

Şimdi:

- Liste ekranının başında **"N fatura işaretlenmeyi bekliyor"** kutusu var
  (`bekleyenleriYukle()`): açılışta, her "Siparişleri Getir"de ve her
  işaretleme/vazgeçmeden sonra tazelenir. İki eylem: "Portala Yükledim,
  İşaretle" ve "Vazgeç" (belge `iptal`, sipariş yeniden faturalanabilir).
- **Kendiliğinden yalnızca "faturalanmadı" satırları seçilir**
  (`kendiligindenSecilir`). "Faturalananları da göster" açıkken hepsinin
  seçili gelmesi "N Faturayı Geri Al" düğmesini hepsi için hazır tutuyordu.
- "XML üretildi" satırı elle seçilip gözden geçirilirse **onay sorulur**;
  devam edilirse eski belge `iptal` olur, yeni numara verilir.
- İşaretleme ve vazgeçme 5'erli parçalar halinde gönderilir
  (`parcaliGonder`), ilerleme çubuğu "12 / 80" diye gerçek ilerlemeyi
  gösterir.

## Windows notları

**Windows'ta çalıştırıldı ve doğrulandı** (21.08.2026, Windows 11 + Python
3.13.4): venv kurulumu, paketler, panel sunucusu, para hesabı ve GİB legacy
TLS bağlantısı — hepsi çalışıyor.

- Başlatma: `baslat.bat` (çift tıkla), kontrol: `kontrol.bat`.
- venv yolu `.venv\Scripts\python.exe` — macOS'taki `.venv/bin/` değil.
- `.bat` dosyaları **ASCII + CRLF** olmalı; Türkçe karakter koyma, cmd bozuk gösterir.
- `kontrol.py` **hem stdout hem stderr'i** UTF-8'e `reconfigure` ediyor ve ANSI
  renk kullanmıyor. stderr şart: beklenmeyen bir hatada traceback'teki Türkçe
  mesaj okunamaz hale geliyordu.
- `uvicorn[standard]` içindeki `uvloop` Windows'ta otomatik atlanır, sorun değil.
- Proje yolunda boşluk var ("Magicland 3D Apps"); SQLite ve venv sorunsuz,
  ama `.bat`/kabuk çağrılarında yolu tırnak içine al.

### Windows'ta çıkıp düzeltilen sorunlar

- **`.env` kodlaması.** `baslat.bat` dosyayı Not Defteri'nde açıyor; kullanıcı
  "ANSI" (cp1254) olarak kaydederse `load_dotenv` UnicodeDecodeError ile
  patlıyor ve panel hiç açılmıyordu. `config._ortami_yukle()` artık sırayla
  `utf-8-sig` → `cp1254` → `latin-1` deniyor. BOM'lu UTF-8 de destekli.
- **Tarayıcı sunucudan önce açılıyordu.** `baslat.bat` artık `start` ile
  tarayıcıyı hemen açmıyor; arka planda 8787 portunu dinleyip (en fazla 20 sn)
  sunucu ayağa kalkınca açıyor. Kullanıcı boş "sayfaya ulaşılamıyor" görmüyor.
- **Yarım kalmış kurulum sessizce geçiliyordu.** Hem `baslat.bat` hem
  `kontrol.bat` artık `.venv` klasörüne değil `.venv\Scripts\python.exe`
  varlığına bakıyor; ayrıca `baslat.bat` paketleri import ederek sınıyor ve
  eksikse tamamlıyor (pip yarıda kesilirse eskiden ModuleNotFoundError
  traceback'i çıkıyordu).

## Çalışma tarzı

- Kod ve arayüz Türkçe; değişken/fonksiyon adları da Türkçe (mevcut üsluba uy).
- Para ile ilgili bir şeye dokunursan gerçek sipariş verisiyle test et ve
  toplamların birebir tuttuğunu göster.
- Mevzuat sorularında kesin konuşma; mali müşavire danışmasını öner.
