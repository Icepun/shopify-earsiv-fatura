# Shopify → e-Arşiv Fatura

Magicland 3D siparişleri için toplu e-Arşiv fatura kesme aracı.
Siparişleri Shopify'dan çeker, gözden geçirmen için listeler, onayladıkların
için GİB e-Arşiv Portal'da taslak oluşturur ve **tek SMS kodu ile hepsini
birden imzalar**.

Portalda tek tek form doldurma yok. Aylık entegratör ücreti yok.

**Masaüstü uygulamasıdır** — tek bir `.exe`, kurulum sihirbazı yok, Python
kurmaya gerek yok. Ayarlar uygulamanın içinde; dosya düzenlenmez. Yeni sürüm
çıktığında uygulama kendisi haber verir ve tek tıkla günceller.

---

## Kullanacak kişi için

1. `MagiclandFatura.exe` dosyasını indir, çift tıkla. Kurulum yok.
2. İlk açılışta **Ayarlar** penceresi kendiliğinden gelir; Shopify ve GİB
   bilgileri doldurulur, **Bağlantıyı Sına** ile doğrulanır, kaydedilir.
3. Bir daha ayarlara dokunmak gerekmez.

> Windows ilk açılışta "bilinmeyen yayımcı" uyarısı gösterebilir
> (**Daha fazla bilgi → Yine de çalıştır**). Dosya imzalı olmadığı için
> normaldir.

Ayarlar ve kayıtlar `%APPDATA%\Magicland Fatura` klasöründe tutulur; uygulama
güncellenince silinmez.

---

## Geliştirme kurulumu

Aşağısı kaynaktan çalıştırmak ve yeni sürüm derlemek içindir.

### 1. Shopify Admin API kimlik bilgileri

Shopify artık Admin içinden `shpat_...` tokeni veren "custom app" açtırmıyor.
Yeni uygulamalar **Dev Dashboard**'da (dev.shopify.com) açılır ve kod, istemci
kimliği + gizli anahtarı 24 saatlik bir erişim tokenine kendisi çevirir
(*client credentials grant*). Panelin yaptığı bu; senin token kopyalaman
gerekmiyor.

1. **dev.shopify.com** > Apps > uygulamanı aç (yoksa oluştur).
2. Uygulamanın sürümünde erişim izinlerini seç:
   `read_orders`, `write_orders`, `read_customers`.
3. Uygulamayı **mağazana kur** (Install). Kurulu değilse token alınamaz.
4. **Ayarlar > Kimlik bilgileri**'ndeki iki değeri `.env`'e yaz:
   `SHOPIFY_ISTEMCI_KIMLIGI` ve `SHOPIFY_GIZLI_ANAHTAR`.

> Uygulama ile mağaza **aynı Shopify organizasyonunda** olmalı; değilse token
> ucu `shop_not_permitted` döner. `kontrol.bat` bu durumu Türkçe açıklar.

Elinde eskiden alınmış bir `shpat_...` tokeni varsa `SHOPIFY_TOKEN` alanına
yazabilirsin; o zaman takas yapılmaz ve doğrudan kullanılır.

### 2. Ayarları gir

```bash
cp .env.example .env
```

`.env` dosyasını aç ve doldur:

```ini
SHOPIFY_STORE=magicland-3d.myshopify.com
SHOPIFY_ISTEMCI_KIMLIGI=  # Dev Dashboard > Ayarlar > Kimlik bilgileri
SHOPIFY_GIZLI_ANAHTAR=    # aynı ekrandaki gizli anahtar

GIB_KULLANICI_KODU=      # İnternet Vergi Dairesi kullanıcı kodun
GIB_SIFRE=               # İnternet Vergi Dairesi şifren
GIB_TEST_MODU=true       # Önce true ile dene, sonra false yap
```

### 3. Bağlantıları sına

**Windows:** `kontrol.bat` dosyasına çift tıkla.

**macOS/Linux:**
```bash
./.venv/bin/python kontrol.py
```

Shopify ve GİB bağlantısını ayrı ayrı dener, ilk siparişi faturaya çevirip
hesabı gösterir. Hepsi ✅ olmadan panele geçme.

> Sanal ortam yoksa önce `./baslat.sh` çalıştır (kurulumu o yapar), sonra
> Ctrl+C ile durdurup `kontrol.py`'yi çalıştır.

### 4. Çalıştır

**Windows:** `baslat.bat` dosyasına çift tıkla — tarayıcı kendiliğinden açılır.

**macOS/Linux:**
```bash
./baslat.sh
```

Panel **http://127.0.0.1:8787** adresinde açılır. İlk çalıştırmada sanal ortam
kurulur (birkaç dakika), sonrakiler anında açılır.

> Windows'ta Python kurulu değilse [python.org/downloads](https://www.python.org/downloads/)
> adresinden 3.11 veya üstünü kur. Kurulum sırasında **"Add python.exe to PATH"**
> kutusunu işaretlemeyi unutma — yoksa `baslat.bat` Python'u bulamaz.

---

## Kullanım

Panel üç adımdan oluşur:

**1 · Siparişleri Getir**
Kargolanmış (veya istersen sadece ödemesi alınmış), henüz faturalanmamış
siparişler listelenir. Her satırda matrah, KDV ve toplam hazır hesaplanmıştır.

Dikkat edilmesi gereken satırlar rozetle işaretlenir:
- *Kurumsal sipariş görünüyor* → VKN ve vergi dairesi girmen gerekir
- *Şehir belirlenemedi* → adres alanını elle doldur
- *Yuvarlama farkı* → fatura toplamı ile tahsilat arasında kuruş farkı var

"bilgileri düzenle" bağlantısıyla alıcı bilgilerini düzeltebilirsin.

**2 · Taslakları Oluştur**
Seçtiğin siparişler GİB portalında **taslak** olarak oluşur. SMS gerekmez,
resmîleşmez, yanlış varsa portaldan silebilirsin.

**3 · Onayla**
"SMS Kodu İste" → kayıtlı cebine kod gelir → kodu gir → **tüm taslaklar tek
seferde imzalanır**. İmzalananlar Shopify'da `faturalandi` etiketi alır ve
fatura ETTN'i siparişin `fatura.ettn` metafield'ına yazılır, böylece bir daha
listeye düşmez.

---

## Ayarlar

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `KDV_ORANI` | `20` | Uygulanacak KDV yüzdesi |
| `KARGOYU_DAGIT` | `true` | `true`: kargo bedeli ürün satırlarına dağıtılır (ayrı satır görünmez). `false`: "Kargo Bedeli" ayrı satır olur |
| `FATURA_NOTU` | boş | Her faturanın not alanına eklenir (IBAN vb.) |
| `BASLANGIC_TARIHI` | boş | Panelde tarih aralığının varsayılan başlangıcı (YYYY-AA-GG). Boş = filtre yok |
| `GIB_TEST_MODU` | `true` | `true` iken GİB **test** ortamına gider, resmî fatura kesilmez |

### Önce test et

GİB'in test ortamında herkese açık hesaplar vardır (`33333301` / şifre `1`;
meşgulse `33333302` de çalışır). `GIB_TEST_MODU=true` bırakıp bu bilgilerle
akışı baştan sona deneyebilirsin: gerçek siparişlerin listelenir, taslaklar
GİB'in **test** sunucusunda oluşur, resmî hiçbir belge doğmaz.

### Tarih aralığı

1. adımdaki **Başlangıç** ve **Bitiş** alanlarıyla yalnızca belirli bir
dönemin siparişleri listelenir; hazır seçenekler için *Bu ay / Geçen ay /
Son 30 gün / Tümü* düğmeleri var. Boş bırakılırsa bütün faturalanmamış
siparişler gelir. Birikmiş siparişleri ay ay, küçük partiler halinde
faturalamak için kullanışlı.

Test ortamında SMS imzalama çalışmaz (kayıtlı telefon yok), yani 3. adım
denenemez. 1. ve 2. adım — sipariş çekme, hesaplama, taslak oluşturma —
tamamen doğrulanır.

> Test hesabı paylaşımlıdır; ünvan alanında başkalarının yazdığı saçma
> metinler görebilirsin. Önemli değil.

**Test kayıtları ayrı veritabanında tutulur** (`fatura-test.db`). Böylece
test denemelerin gerçek siparişleri "faturalandı" saymaz. `GIB_TEST_MODU=false`
yaptığında `fatura.db` devreye girer ve tüm siparişler yeniden listelenir.

Gerçek fatura kesmeye hazır olduğunda `GIB_TEST_MODU=false` yap ve kendi
İnternet Vergi Dairesi bilgilerini gir.

---

## Para hesabı nasıl yapılıyor

Shopify'da fiyatlar KDV **dahil** tutulur. Fatura ise KDV hariç matrah ister.
Tüm hesap `Decimal` ile yapılır, float kullanılmaz. Her faturada şu üç kural
korunur:

```
birimFiyat × miktar = malHizmetTutari
malHizmetTutari × kdvOranı = kdvTutarı
toplam matrah + toplam KDV = ödenecek tutar
```

Kargo bedeli (indirimler düşülmüş net hali) ürün satırlarına tutar oranında
dağıtılır; dağıtım artığı son satıra yazılır, böylece toplam korunur.

Fatura toplamı ile Shopify'ın tahsil ettiği tutar arasında kuruş farkı
kalırsa **gizlenmez** — panelde "sapma" rozetiyle gösterilir.

---

## Bilmen gerekenler

**ETTN'i GİB atar.** Fatura oluşturma isteğine kendi UUID'ini koyarsan portal
`Ettn ... 36 uzunluk sınırına uymuyor` diyerek reddeder — `faturaUuid` boş
gönderilmeli. Portal yanıtında ETTN dönmediği için, hangi taslağın hangi
siparişe ait olduğu oluşturma öncesi/sonrası taslak farkından ve belge
numarası sırasından eşleştirilir. Eşleşme yapılamazsa panel uyarır ve
faturaları portaldan elle onaylaman gerekir.

**Bu API resmî değil.** GİB e-Arşiv Portal'ın web arayüzünün kullandığı JSON
uçlarıyla konuşuyoruz. GİB arayüzü değiştirirse `fatura/gib.py` güncellenmelidir.
Kendi hesabınla kendi faturanı kestiğin için işin özünde bir sakınca yok, ama
resmî destekli bir entegrasyon olmadığını bilerek kullan.

**Bir entegratöre geçmek kolay.** Fatura üretme mantığı (`donustur.py`,
`payload.py`) gönderim katmanından ayrı. Nilvera/Paraşüt gibi bir servise
geçmek istersen sadece `gib.py` yerine yeni bir istemci yazılır.

**Şifreler `.env` içinde düz metin durur.** `.gitignore` bu dosyayı dışlar;
makineni başkasıyla paylaşıyorsan dikkat et.

---

## Dosyalar

```
masaustu.py        uygulama giriş noktası (pencere + gömülü sunucu)
derle.py           tek dosyalık .exe üretir (dist/MagiclandFatura.exe)
simge.ico          uygulama simgesi
fatura/
  config.py      ayarlar (ayarlar.json; yoksa .env'den devralır)
  shopify_api.py Shopify Admin GraphQL istemcisi
  donustur.py    sipariş → fatura (KDV ayrıştırma, kargo dağıtımı, uyarılar)
  payload.py     fatura → GİB payload (+ tutarı yazıyla)
  gib.py         GİB e-Arşiv Portal istemcisi (login, taslak, toplu SMS imza)
  depo.py        SQLite: hangi sipariş faturalandı, ETTN'ler, hatalar
  guncelleme.py  GitHub Releases'ten sürüm kontrolü, indirme, kurulum
  web.py         panel sunucusu (FastAPI)
static/index.html  panel arayüzü + ayarlar penceresi
kontrol.py         bağlantı sınaması (uygulama içindeki "Bağlantıyı Sına" ile aynı iş)
baslat.sh / baslat.bat / kontrol.bat   geliştirme kısayolları
CLAUDE.md          projede çalışacak Claude oturumları için notlar
```

## Yeni sürüm çıkarma

1. `fatura/config.py` içindeki `SURUM` değerini yükselt (ör. `1.1.0`).
2. `.venv\Scripts\python.exe derle.py`
3. GitHub'da `v1.1.0` etiketiyle release oluştur, `dist\MagiclandFatura.exe`
   dosyasını ekle.

Uygulama açılışta son release'i sorar, yenisi varsa şerit gösterir. Kullanıcı
"Güncelle" derse .exe indirilir, çalışan dosyanın adı `.eski.exe` yapılıp
yenisi yerine konur ve uygulama yeniden başlar.

## Sorun giderme

| Belirti | Sebep |
|---|---|
| `Invalid API key or access token` | Ayarlar'daki istemci kimliği/gizli anahtar yanlış, ya da uygulama mağazaya kurulmamış |
| `GİB girişi başarısız` | Kullanıcı kodu/şifre hatalı, ya da deneme modu yanlış ortamı gösteriyor |
| `Sisteme aynı anda birden fazla giriş yapamazsınız` | Tarayıcıda e-Arşiv Portal açık; oradan "Güvenli Çıkış" yap |
| `Portalda kayıtlı cep telefonu bulunamadı` | e-Arşiv Portal → Kullanıcı Bilgileri'nden telefon eklenmeli |
| `Taslaklar GİB portalında bulunamadı` | Taslak farklı bir tarih aralığında; portaldan kontrol et |
| Sipariş listeye düşmüyor | Zaten `faturalandi` etiketi var, ya da iptal edilmiş / ödemesi alınmamış |
| `Ettn ... 36 uzunluk sınırına uymuyor` | `faturaUuid` boş gönderilmeli — GİB tarafındaki yanıltıcı mesaj aslında "alanları okuyamadım" demek |
