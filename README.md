# Shopify → e-Arşiv Fatura

Magicland 3D siparişleri için toplu e-Arşiv fatura kesme aracı.
Siparişleri Shopify'dan çeker, gözden geçirmen için listeler, onayladıkların
için GİB e-Arşiv Portal'da taslak oluşturur ve **tek SMS kodu ile hepsini
birden imzalar**.

Portalda tek tek form doldurma yok. Aylık entegratör ücreti yok.

---

## Kurulum

### 1. Shopify Admin API anahtarı

Shopify yöneticisinde:

**Settings → Apps and sales channels → Develop apps → Create an app**

*Configure Admin API scopes* bölümünde şu izinleri ver:

| İzin | Ne için |
|---|---|
| `read_orders` | Siparişleri okumak |
| `write_orders` | Faturalanan siparişi etiketlemek |
| `read_customers` | Müşteri e-posta / telefon bilgisi |

Sonra **Install app** → **Reveal Admin API access token**.
`shpat_` ile başlayan bu değeri kopyala.

> 60 günden eski siparişleri listelemek istersen Shopify'ın ek onaya tabi
> `read_all_orders` iznini de talep etmen gerekir. Günlük kullanımda gerekmez.

### 2. Ayarları gir

```bash
cp .env.example .env
```

`.env` dosyasını aç ve doldur:

```ini
SHOPIFY_STORE=magicland-3d.myshopify.com
SHOPIFY_TOKEN=shpat_...

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
| `GIB_TEST_MODU` | `true` | `true` iken GİB **test** ortamına gider, resmî fatura kesilmez |

### Önce test et

GİB'in test ortamında herkese açık hesaplar vardır (`33333301` / şifre `1`).
`GIB_TEST_MODU=true` bırakıp bu bilgilerle akışı baştan sona deneyebilirsin:
gerçek siparişlerin listelenir, taslaklar GİB'in **test** sunucusunda oluşur,
resmî hiçbir belge doğmaz.

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
fatura/
  config.py      .env ayarları
  shopify_api.py Shopify Admin GraphQL istemcisi
  donustur.py    sipariş → fatura (KDV ayrıştırma, kargo dağıtımı, uyarılar)
  payload.py     fatura → GİB payload (+ tutarı yazıyla)
  gib.py         GİB e-Arşiv Portal istemcisi (login, taslak, toplu SMS imza)
  depo.py        SQLite: hangi sipariş faturalandı, ETTN'ler, hatalar
  web.py         panel sunucusu (FastAPI)
static/index.html  panel arayüzü
kontrol.py         bağlantı ve hesap sınaması
baslat.sh          kurulum + panel başlatma (macOS/Linux)
baslat.bat         kurulum + panel başlatma (Windows)
kontrol.bat        bağlantı sınaması (Windows)
CLAUDE.md          projede çalışacak Claude oturumları için notlar
```

## Sorun giderme

| Belirti | Sebep |
|---|---|
| `Invalid API key or access token` | `.env` içindeki `SHOPIFY_TOKEN` yanlış veya app kurulmamış |
| `GİB girişi başarısız` | Kullanıcı kodu/şifre hatalı, ya da `GIB_TEST_MODU` yanlış ortamı gösteriyor |
| `Portalda kayıtlı cep telefonu bulunamadı` | e-Arşiv Portal → Kullanıcı Bilgileri'nden telefon eklenmeli |
| `Taslaklar GİB portalında bulunamadı` | Taslak farklı bir tarih aralığında; portaldan kontrol et |
| Sipariş listeye düşmüyor | Zaten `faturalandi` etiketi var, ya da iptal edilmiş / ödemesi alınmamış |
| `Ettn ... 36 uzunluk sınırına uymuyor` | `faturaUuid` boş gönderilmeli — GİB tarafındaki yanıltıcı mesaj aslında "alanları okuyamadım" demek |
