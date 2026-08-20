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
fatura/config.py       .env ayarları; GIB_TEST_MODU test/gerçek DB'yi ayırır
fatura/shopify_api.py  Admin GraphQL: sipariş çekme, etiket, ETTN metafield
fatura/donustur.py     sipariş -> Fatura (KDV ayrıştırma, kargo dağıtımı, uyarılar)
fatura/payload.py      Fatura -> GİB payload + tutarı yazıyla
fatura/gib.py          GİB e-Arşiv Portal istemcisi (login/dispatch/SMS imza)
fatura/depo.py         SQLite: durum, ETTN, hatalar
fatura/web.py          FastAPI panel sunucusu
static/index.html      panel arayüzü (vanilla JS, tek dosya)
kontrol.py             bağlantı ve hesap sınaması
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
olarak panele "sapma" rozetiyle taşınır. Gerçek siparişlerde sapma 0.00 çıkıyor.

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
gönderme — uydurma veri kullan. Oluşturduğun test faturalarını
`portal.fatura_sil(taslaklar, "açıklama")` ile temizle.

## Bilinen eksikler / muhtemel sıradaki işler

- **Geçmiş siparişler:** ilk gerçek çalıştırmada daha önce elle faturalanmış
  siparişler de listeye düşer → çift fatura riski. Kullanıcıya toplu
  `faturalandi` etiketleyen tek seferlik betik veya panele tarih filtresi
  önerildi, henüz yazılmadı.
- **İade/iptal:** kısmi iade `currentQuantity` ile orantılanıyor ama iade
  faturası (`iadeTable`) desteklenmiyor.
- ETTN eşleştirmesi aynı anda başka bir oturumdan fatura kesilirse kayabilir;
  panel bu durumda uyarı veriyor ama isim bazlı doğrulama eklenebilir.
- Panelde imzalanmış faturaların PDF'ini indirme yok (`gib.indirme_linki` hazır).

## Windows notları

- Başlatma: `baslat.bat` (çift tıkla), kontrol: `kontrol.bat`.
- venv yolu `.venv\Scripts\python.exe` — macOS'taki `.venv/bin/` değil.
- `.bat` dosyaları **ASCII + CRLF** olmalı; Türkçe karakter koyma, cmd bozuk gösterir.
- `kontrol.py` çıktıyı UTF-8'e `reconfigure` ediyor ve ANSI renk kullanmıyor.
- `uvicorn[standard]` içindeki `uvloop` Windows'ta otomatik atlanır, sorun değil.
- **Bu proje Windows'ta henüz çalıştırılmadı** (macOS'ta geliştirildi). İlk iş
  `kontrol.bat` ile dört adımın da ✅ olduğunu doğrulamak.

## Çalışma tarzı

- Kod ve arayüz Türkçe; değişken/fonksiyon adları da Türkçe (mevcut üsluba uy).
- Para ile ilgili bir şeye dokunursan gerçek sipariş verisiyle test et ve
  toplamların birebir tuttuğunu göster.
- Mevzuat sorularında kesin konuşma; mali müşavire danışmasını öner.
