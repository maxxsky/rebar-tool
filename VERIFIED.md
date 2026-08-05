# VERIFIED — Hasil Verifikasi F4

> Fase ini dikerjakan oleh **owner (Brahma)** — bukan developer.
> Isi dokumen ini lengkap sebelum lanjut ke F5 (kolom).
> Prosedur lengkap: `05-VERIFICATION.md`.

---

## 1. Proyek & gambar yang dipakai

| Field | Isi |
|---|---|
| Nama proyek | |
| Kode proyek | |
| Gambar struktur (no. & rev) | |
| BBS asli (sumber) | |
| Tanggal verifikasi | |
| Versi tool | `rebar-tool v0.1.0` |

## 2. Config final hasil kalibrasi

> Salin nilai config yang TERPAKAI saat verifikasi (bukan contoh).

```yaml
# config/project.yaml — nilai final
panjang_penyaluran_mm:
  # ... per diameter dari gambar

hook:
  koreksi_bengkokan_aktif: false   # ubah kalau dikalibrasi

sengkang:
  metode_hitung: "kontinyu"        # atau "per_zona" — berdasar data
```

## 3. Perbandingan balok #1

Input: `B1 | bentang_bersih_mm | 1 | uji verifikasi`

| Item | BBS Asli | Output Tool | Selisih | Status |
|---|---|---|---|---|
| Tul. atas — panjang potong | | | | |
| Tul. atas — jumlah | | | | |
| Tul. bawah — panjang potong | | | | |
| Tul. bawah — jumlah | | | | |
| Sengkang — panjang potong | | | | |
| Sengkang — jumlah | | | | |
| Total berat balok (kg) | | | | |

## 4. Perbandingan balok #2 (tipe/dimensi beda)

Input: `____ | bentang_bersih_mm | 1 | uji verifikasi`

| Item | BBS Asli | Output Tool | Selisih | Status |
|---|---|---|---|---|
| Tul. atas — panjang potong | | | | |
| Tul. bawah — panjang potong | | | | |
| Sengkang — panjang potong | | | | |
| Sengkang — jumlah | | | | |
| Total berat balok (kg) | | | | |

## 5. Satu lantai penuh — total berat per diameter

| Diameter | BBS Asli (kg) | Output Tool (kg) | Selisih % | Status |
|---|---|---|---|---|
| D10 | | | | |
| D13 | | | | |
| D16 | | | | |
| D19 | | | | |

Toleransi: ≤1% per diameter.

## 6. Verifikasi optimizer

### 6.1 Konservasi manual
```
Σ (panjang tiap potongan × frekuensi pola) == total panjang di BBS?
```
| Diameter | Σ pola (m) | Total BBS (m) | Cocok? |
|---|---|---|---|
| | | | |

### 6.2 Kelayakan tiap pola
```
Σ potongan + (n_potongan − 1) × kerf ≤ 12000?
```
| Pola | Total (mm) | ≤ 12000? |
|---|---|---|
| | | |

### 6.3 Realisasi lapangan (opsional — pekerjaan selesai)

| | Realisasi | Output tool |
|---|---|---|
| Jumlah batang terpakai | | |
| Waste (%) | | |

> Klaim jujur: potensi hemat tool ≠ realisasi lapangan. Ada faktor yang
> tidak masuk model (sisa dipakai kerjaan lain, salah potong, preferensi
> tukang). Kalau tool bilang hemat 4%, klaimnya "potensi 4% kondisi ideal".

## 7. Checklist gerbang F4

- [ ] Satu balok cocok: panjang potong selisih **0 mm**
- [ ] Jumlah sengkang cocok / selisih dipahami & konvensi disepakati
- [ ] Tipe balok kedua cocok
- [ ] Satu lantai: total berat per diameter ≤1%
- [ ] Optimizer: konservasi terbukti manual
- [ ] Optimizer: semua pola layak (≤12000 mm termasuk kerf)
- [ ] `koreksi_bengkokan` dikalibrasi / dipastikan tidak perlu
- [ ] `metode_hitung` sengkang dipilih berdasar data
- [ ] Semua selisih tersisa punya penjelasan tertulis

## 8. Selisih yang tersisa + penjelasan

| Item | Selisih | Penyebab | Aksi |
|---|---|---|---|
| | | | |
| | | | |

---

**Selesai: `tanggal`** — lanjut F5 (kolom) 🟢 / **belum** 🔴
