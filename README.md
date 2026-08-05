# Rebar BBS Generator + Cutting Optimizer

Alat bantu kuantitas tulangan beton untuk pekerjaan QS. BBS + cutting optimizer + output Excel.

## Status fase

| Fase | Isi | Status |
|---|---|---|
| F0 | Config loader + validasi | ✅ selesai |
| F1 | Optimizer potong (FFD) | ✅ selesai |
| F2 | Generator BBS balok | ✅ selesai |
| F3 | Output Excel 4 sheet | ✅ selesai |
| **F4** | **Verifikasi manual (owner)** | 🔴 **sedang — lihat `VERIFIED.md`** |
| F5+ | Kolom, lap splice, plat | nunggu F4 lulus |

## Aturan project (jangan dilanggar)

1. **No hardcoded engineering values** — semua nilai teknis dari `config/project.yaml`. Melihat `40 * dia` di kode = pelanggaran.
2. **Fail loud** — data config kurang → raise error & berhenti. Gak ada default, gak ada interpolasi, gak ada warning-lalu-lanjut.
3. **Traceability** — tiap output cetak parameter config yang dipakai (nilai + sumber gambar/revisi).
4. **Satuan mm integer** internal; meter hanya di layer output.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt   # pyyaml pytest openpyxl
```

## Pakai

```bash
# F1 — optimasi potong dari CSV (dia,panjang_mm,jumlah)
.venv/bin/python src/cli.py optimize input/potongan.csv --config config

# F2+F3 — BBS dari elemen.xlsx → Excel 4 sheet
.venv/bin/python src/cli.py bbs input/elemen.xlsx --config config
# → output/BBS_{kode}_{YYYYMMDD-HHMM}.xlsx (tidak menimpa)
```

## Test

```bash
.venv/bin/python -m pytest tests -q    # 69 passed
```

## Struktur

```
rebar-tool/
├── config/            # project.yaml (nilai teknis) + templates.yaml
├── src/               # config_loader, models, bbs, optimizer, export, cli
├── tests/             # test F0-F3
├── input/             # elemen.xlsx, potongan.csv
├── output/            # BBS_*.xlsx (timestamp)
└── VERIFIED.md        # hasil verifikasi F4 (diisi owner)
```

## Verifikasi (F4)

Prosedur & template di `VERIFIED.md` + `05-VERIFICATION.md` (dokumen owner).
Gerbang: jangan lanjut F5 sebelum F4 lulus.
