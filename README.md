# 🧾 vibe-receipts

> **Vibe coding'in fişi.** Claude'la gerçekte kaç saat çalıştın? Commit'ler tahmin eder, loglar kanıtlar.

Bir git reposunda harcanan **gerçek çalışma süresini**, git geçmişinden ve
Claude Code oturum kayıtlarından tahmin eden küçük bir araç.
Tek dosya, bağımlılık yok (yalnız Python 3 standart kütüphanesi).

## Claude Code'a kur (önerilen)

```
/plugin marketplace add sahmett/vibe-receipts
/plugin install vibe-receipts@vibe-receipts
```

Sonra Claude'a sor: *"Bu repoda bu hafta kaç saat çalıştım?"*, *"Haziran'ın fişini çıkar"*.
Skill script'i çalıştırır, raporu üretir ve günlük ne yapıldığını commit'lerden özetler.

## Ya da doğrudan çalıştır

```bash
python3 receipts.py ~/path/to/repo
```

Çıktı: `~/vibe-receipts/<repo>-rapor.html` (görsel rapor) ve `<repo>-gunluk.csv` (günlük döküm).
Raporlar kişisel çalışma verisi içerir, analiz edilen repoya yazılmaz.

## Repo yapısı

```
.claude-plugin/            ← plugin + marketplace manifestleri
skills/vibe-receipts/
├── SKILL.md               ← Claude'un ne zaman/nasıl çalıştıracağı
└── scripts/
    ├── receipts.py        ← analiz + HTML rapor
    └── to_jpg.sh          ← raporu JPEG'e çevirir
receipts.py, to_jpg.sh     ← kısayol (symlink)
```

## Yöntem: iki bağımsız katman

### 1) Tahmin: commit "efor oranı" modeli
Git commit'lerinden hesaplanır, transcript'i olmayan projelere de uygulanabilir.

```
TOPLAM     = Ölçülen × Efor oranı
Efor oranı = 1 + (eklenen etkin kod × KOD_ORANI) / Ölçülen
```

1. **Temizlik:** merge ve stash commit'leri atılır.
2. **Ölçülen:** ardışık commit'ler arası boşlukların toplamı. `>150 dk` boşluk
   mola sayılıp çıkarılır, altındaki tüm boşluk tam sayılır.
3. **Eklenen etkin kod:** eklenen satırlar tipe göre ağırlıklanır:
   `kod ×1.0 · config ×0.4 · docs/mimari ×0 · kopya-vendor ×0 · üretilmiş (lock, migration) ×0`.
   Toplu kopyalanan statik içerik (`prototypes/`, `_archive/`, `vendor/`) dışlanır.
   Dışlanmazsa süre tamamen bozulabilir. Projene göre `VENDOR_RE`'yi genişlet.
4. **Efor oranı:** kod yoğunluğundan türeyen tek katsayı. Sabit "sallama" yüzde yok.

### 2) Gerçek (ground truth): Claude transcript aktif süresi
`~/.claude/projects/<proje>/*.jsonl` dosyalarındaki **her olayın zaman damgasından**
ölçülür. Ardışık olaylar arası boşluk `≤15 dk` ise aktif sayılır, üstü uzaklaşma kabul
edilip çıkarılır. Commit yöntemiyle aynı mantık ama çok daha yoğun veriyle.

- Proje klasörü repo yolundan otomatik bulunur (Claude Code yoldaki alfanümerik olmayan
  karakterleri `-` yapar). `.claude/worktrees/` altındaki oturumlar da dahil edilir.
  Farklı bir klasör için `--transcripts <dir>` kullan.
- Yalnız bu repo klasöründe açılan oturumlar sayılır, başka projeler karışmaz.
  Claude olmadan elle yapılan iş bu ölçüme girmez.

> ⚠️ **Claude Code eski transcript'leri varsayılan olarak 30 gün sonra siler.**
> Geçmişe dönük ölçüm istiyorsan `~/.claude/settings.json` içine
> `"cleanupPeriodDays": 36500` ekle. Silinmiş günler için yalnız commit tahmini kalır.

## Kalibrasyon

`KOD_ORANI` (dk / eklenen etkin satır) çalışma tarzına göre değişir. Transcript'i olan
bir projede gerçek değere oturt:

```bash
python3 receipts.py ~/path/to/repo --since 2026-06-01 --until 2026-06-30 --calibrate
```

Çıkan değeri `receipts.py` başındaki `KOD_ORANI`'ya yaz. Toplam bu yüzden tasarım
gereği transcript'e oturur. Modelin asıl bağımsız testi **günlük dağılımdır**.

## Parametreler

| Bayrak | Anlam |
|---|---|
| `repo` | analiz edilecek git reposu (varsayılan `.`) |
| `--since / --until` | gün aralığı `YYYY-MM-DD` (commit + transcript ikisine de uygulanır) |
| `--author` | yalnız bu yazarın commit'leri (`git log --author` deseni) |
| `--transcripts DIR` | Claude kayıt klasörünü elle ver (tekrarlanabilir) |
| `--calibrate` | `KOD_ORANI`'yı transcript'e göre hesapla |
| `--out DIR` | çıktı klasörü (varsayılan `~/vibe-receipts`) |

Script başındaki sabitler:

| Sabit | Değer | Anlam |
|---|---|---|
| `BREAK` | 150 dk | commit arası mola eşiği |
| `KOD_ORANI` | 0.02 dk/satır | efor oranını belirleyen kod oranı |
| `TR_IDLE` | 15 dk | transcript aktif-süre eşiği |
| `CODE_W` | kod 1.0 / config 0.4 / docs 0 | eklenen kod ağırlıkları |
| `VENDOR_RE`, `GEN_RE` | regex | dışlanan kopya/vendor ve üretilmiş dosya desenleri |

## JPEG'e çevirme (opsiyonel)

```bash
bash to_jpg.sh ~/vibe-receipts/<repo>-rapor.html   # macOS + Google Chrome + Pillow
```
