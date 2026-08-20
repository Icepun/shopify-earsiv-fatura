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

Portalda tek tek form doldurmayı bitirmek. Akış: siparişleri Shopify'dan çek →
panelde gözden geçir/düzelt → toplu taslak oluştur → **tek SMS koduyla hepsini
imzala** → Shopify'da `faturalandi` etiketle.

## Mimari

```
masaustu.py            uygulama giriş noktası: pencere + gömülü sunucu
derle.py               PyInstaller ile tek dosyalık .exe üretir
fatura/config.py       ayarlar (ayarlar.json; yoksa .env'den devralır)
fatura/shopify_api.py  Admin GraphQL: sipariş çekme (tarih aralığı), etiket, ETTN metafield
fatura/donustur.py     sipariş -> Fatura (KDV ayrıştırma, kargo dağıtımı, uyarılar)
fatura/payload.py      Fatura -> GİB payload + tutarı yazıyla
fatura/gib.py          GİB e-Arşiv Portal istemcisi (login/dispatch/SMS imza)
fatura/depo.py         SQLite: durum, ETTN, hatalar
fatura/guncelleme.py   GitHub Releases: sürüm kontrolü, indirme, kendini değiştirme
fatura/web.py          FastAPI panel sunucusu
static/index.html      panel arayüzü + ayarlar penceresi (vanilla JS, tek dosya)
kontrol.py             bağlantı sınaması (uygulamadaki "Bağlantıyı Sına" ile aynı iş)
```

Katmanlar bilinçli olarak ayrık: entegratöre geçilecek olursa yalnızca
`gib.py` değişir, hesap mantığı aynen kalır.

## GİB protokolü — zor kazanılmış bilgiler

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
- **Test veritabanını sıfırlamak:** `fatura-test.db` dosyasını sil. Test
  ortamında imzalama çalışmadığı için oradaki taslaklar sonsuza kadar
  "bekliyor" görünür; gerçek kayıtlar `fatura.db`'de, etkilenmez.

## Masaüstü uygulaması (21.08.2026'da eklendi)

**Uygulamayı Simay kullanacak, Berke değil.** Teknik olmayan bir kullanıcı
varsayımıyla tasarlandı: `.bat` yok, konsol yok, dosya düzenlemek yok.

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

## Panel akışı — taslaklar "kaybolmaz"

Taslak oluşturulunca satırlar 1. adım tablosundan düşer (aynı siparişe ikinci
kez fatura kesilmesin diye; `depo.islenmis_idler()` de onları bir daha
listelemez). Eskiden bu yüzden **ekranda hiçbir iz kalmıyordu**: `ciz()` liste
boşalınca 2. ve 3. adım kartını da gizliyordu ve kullanıcı faturaların nereye
gittiğini göremiyordu. `/api/gecmis` ucu vardı ama arayüz onu hiç çağırmıyordu.

Şimdi 2. ve 3. adım arasında **"Bekleyen taslaklar"** kutusu var
(`/api/bekleyenler` → `depo.bekleyen_taslaklar()`); açılışta, taslak
oluşturunca ve imzalayınca tazeleniyor. `kartGorunurlugu()` bekleyen taslak
varken işlem kartını açık tutuyor.

Taslaklar iki yerde durur: GİB portalında `onayDurumu="Onaylanmadı"` olarak,
ve yerel SQLite'ta `durum='taslak'` olarak. ETTN ikisini bağlar.

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
