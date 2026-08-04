"""Cutting stock optimizer — First Fit Decreasing (F1).

Spec 03-SPEC-optimizer.md. Aturan:
- FFD, dijalankan terpisah per diameter.
- Kerf dikonsumsi ANTAR potongan (potongan ke-2 dst), bukan per potongan.
- Pola dikelompokkan & dibatasi ke max_pola (default 8), sisa jadi pola
  "SISA/CAMPURAN" — lapor dampak waste-nya.
- Fail loud: potongan > stok → raise ValueError.
"""

from collections import Counter
from itertools import groupby

from models import Cut, OptimizeResult, Pattern, ProjectConfig


def optimize(cuts: list[Cut], cfg: ProjectConfig) -> OptimizeResult:
    """Optimasi satu diameter. `cuts` HARUS sudah satu diameter."""
    dias = {c.dia for c in cuts}
    if len(dias) != 1:
        raise ValueError(f"optimize() menerima satu diameter, dapat {dias}")
    dia = next(iter(dias))

    stock = cfg.stok.panjang_batang_mm
    kerf = cfg.stok.kerf_mm

    # 1. Expand (panjang, qty) -> list panjang individual
    pieces: list[int] = []
    for c in cuts:
        pieces.extend([c.panjang_mm] * c.jumlah)

    # 2. Urutkan panjang -> pendek
    pieces.sort(reverse=True)

    if pieces and pieces[0] > stock:
        raise ValueError(
            f"Potongan {pieces[0]} mm > batang stok {stock} mm "
            f"(diameter {dia})")

    # 3. First fit
    bars: list[list[int]] = []
    sisa: list[int] = []

    for p in pieces:
        placed = False
        for i, s in enumerate(sisa):
            need = p if not bars[i] else p + kerf
            if s >= need:
                bars[i].append(p)
                sisa[i] = s - need
                placed = True
                break
        if not placed:
            bars.append([p])
            sisa.append(stock - p)

    # 4. Kelompokkan baris identik -> pola + frekuensi
    pola_counts: Counter[tuple] = Counter()
    for bar, sisa_mm in zip(bars, sisa):
        key = tuple(sorted(bar, reverse=True))
        pola_counts[key] += 1

    # ── metrik sebelum pembatasan ──
    hasil_tanpa_batasi = _build(cfg, dia, pola_counts, stock, kerf)

    # ── pembatasan pola ──
    campur = None
    if cfg.optimizer.batasi_pola and len(pola_counts) > cfg.optimizer.max_pola:
        pola_counts, campur = _batasi_pola(pola_counts, cfg.optimizer.max_pola,
                                           stock, kerf)

    hasil = _build(cfg, dia, pola_counts, stock, kerf, campur=campur)
    # isi metrik pembatasan
    return OptimizeResult(
        dia=dia,
        patterns=hasil.patterns,
        total_batang=hasil.total_batang,
        total_panjang_stok_mm=hasil.total_panjang_stok_mm,
        total_panjang_terpakai_mm=hasil.total_panjang_terpakai_mm,
        total_kerf_mm=hasil.total_kerf_mm,
        total_sisa_mm=hasil.total_sisa_mm,
        sisa_reusable_mm=hasil.sisa_reusable_mm,
        waste_pct=hasil.waste_pct,
        waste_kotor_pct=hasil.waste_kotor_pct,
        pola_sebelum_batasi=hasil_tanpa_batasi.pola_sesudah_batasi,
        pola_sesudah_batasi=hasil.pola_sesudah_batasi,
        waste_pct_tanpa_batasi=hasil_tanpa_batasi.waste_pct,
    )


def optimize_all(cuts: list[Cut], cfg) -> dict[int, OptimizeResult]:
    """Optimasi semua diameter, terpisah per diameter."""
    out: dict[int, OptimizeResult] = {}
    cuts = sorted(cuts, key=lambda c: c.dia)
    for dia, group in groupby(cuts, key=lambda c: c.dia):
        out[dia] = optimize(list(group), cfg)
    return out


def _build(cfg, dia, pola_counts, stock, kerf, campur=None) -> OptimizeResult:
    """Susun OptimizeResult dari pola counts (setelah/sblm pembatasan).

    campur: None | (potongan_tuple, frekuensi_batang, sisa_avg_mm, kerf_total_mm)
    — satu pola "SISA/CAMPURAN" hasil pembatasan.
    """
    sisa_min = cfg.stok.sisa_min_simpan_mm
    patterns: list[Pattern] = []
    total_batang = 0
    total_kerf = 0
    total_sisa = 0
    sisa_reusable = 0
    total_terpakai = 0

    # urut pola: frekuensi tinggi dulu, lalu isi
    for key, freq in sorted(pola_counts.items(), key=lambda kv: (-kv[1], kv[0])):
        potongan = tuple(sorted(key, reverse=True))
        panjang_potongan = sum(potongan)
        # kerf per batang: antar potongan = (n_potongan - 1) × kerf
        kerf_per_barang = max(len(potongan) - 1, 0) * kerf
        sisa_barang = stock - panjang_potongan - kerf_per_barang
        reusable = sisa_barang >= sisa_min
        patterns.append(Pattern(potongan=potongan, frekuensi=freq,
                                sisa_mm=sisa_barang, reusable=reusable))
        total_batang += freq
        total_kerf += kerf_per_barang * freq
        total_sisa += sisa_barang * freq
        total_terpakai += panjang_potongan * freq
        if reusable:
            sisa_reusable += sisa_barang * freq

    if campur is not None:
        # Pola "SISA/CAMPURAN": potongan = SEMUA potongan tersisa (agregat),
        # frekuensi = 1. Jumlah batang nyata (batang_campur) dihitung terpisah —
        # isi tiap batang campur tidak identik, jadi tidak bisa diwakili
        # sebagai satu pola berfrekuensi >1 tanpa melanggar konservasi.
        potongan_campur, batang_campur, sisa_total, kerf_campur = campur
        sisa_avg = round(sisa_total / batang_campur) if batang_campur else 0
        reusable_campur = sisa_avg >= sisa_min
        patterns.append(Pattern(potongan=tuple(sorted(potongan_campur,
                                                      reverse=True)),
                                frekuensi=1, sisa_mm=sisa_total,
                                reusable=reusable_campur))
        total_batang += batang_campur
        total_kerf += kerf_campur
        total_sisa += sisa_total
        total_terpakai += sum(potongan_campur)
        if reusable_campur:
            sisa_reusable += sisa_total

    total_stok = total_batang * stock
    waste_bersih = max(total_sisa - sisa_reusable, 0)
    waste_pct = (waste_bersih / total_stok * 100) if total_stok else 0.0
    waste_kotor_pct = (total_sisa / total_stok * 100) if total_stok else 0.0

    return OptimizeResult(
        dia=dia, patterns=patterns, total_batang=total_batang,
        total_panjang_stok_mm=total_stok,
        total_panjang_terpakai_mm=total_terpakai,
        total_kerf_mm=total_kerf, total_sisa_mm=total_sisa,
        sisa_reusable_mm=sisa_reusable, waste_pct=round(waste_pct, 4),
        waste_kotor_pct=round(waste_kotor_pct, 4),
        pola_sebelum_batasi=len(pola_counts) + (1 if campur else 0),
        pola_sesudah_batasi=len(pola_counts) + (1 if campur else 0),
        waste_pct_tanpa_batasi=round(waste_pct, 4),
    )


def _ffd_pieces(pieces: list[int], stock: int, kerf: int):
    """FFD murni utk daftar potongan → (bars, rem, kerf_total)."""
    pieces = sorted(pieces, reverse=True)
    bars: list[list[int]] = []
    rem: list[int] = []
    kerf_total = 0
    for p in pieces:
        placed = False
        for i, s in enumerate(rem):
            need = p if not bars[i] else p + kerf
            if s >= need:
                bars[i].append(p)
                kerf_total += kerf if bars[i] else 0
                rem[i] = s - need
                placed = True
                break
        if not placed:
            bars.append([p])
            rem.append(stock - p)
    return bars, rem, kerf_total


def _batasi_pola(pola_counts: Counter, max_pola: int, stock, kerf):
    """Ambil max_pola-1 pola terpopuler; sisanya SATU pola 'SISA/CAMPURAN'.

    Return (Counter pola yang dipertahankan, campur_info | None).
    campur_info = (potongan_tuple, frekuensi_batang, sisa_avg_mm, kerf_total_mm)
    """
    if max_pola <= 1:
        max_pola = 2
    ordered = sorted(pola_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    keep = ordered[: max_pola - 1]
    campur_items = ordered[max_pola - 1:]

    baru: Counter[tuple] = Counter()
    for key, freq in keep:
        baru[key] = freq
    if not campur_items:
        return baru, None

    # FFD ulang semua potongan yang belum tercakup → hitung batang nyata
    pieces: list[int] = []
    for key, freq in campur_items:
        pieces.extend(list(key) * freq)
    bars, rem, kerf_total = _ffd_pieces(pieces, stock, kerf)
    batang_campur = len(bars)
    sisa_total = sum(rem)
    campur_info = (tuple(pieces), batang_campur, sisa_total, kerf_total)
    return baru, campur_info
