"""Cutting stock optimizer — First Fit Decreasing (F1, PATCH-01).

Spec 03-SPEC-optimizer.md + PATCH-01. Aturan:
- FFD, dijalankan terpisah per diameter.
- Kerf dikonsumsi ANTAR potongan (potongan ke-2 dst), bukan per potongan.
- Pengelompokan batang identik = pelaporan MURNI. Tidak ada pembatasan
  pola / "SISA/CAMPURAN" — PATCH-01 menghapusnya (pola campuran tidak
  bisa dieksekusi & batang tidak terwakili pola).
- Fail loud: potongan > stok → ValueError.
- Invariant runtime: tiap pola layak dieksekusi (sum + (n-1)*kerf <= stok)
  dan sum(frekuensi) == total_batang. Keduanya bug internal →
  InfeasiblePatternError, bukan error input.
"""

from collections import Counter
from itertools import groupby

from models import Cut, InfeasiblePatternError, OptimizeResult, Pattern, \
    ProjectConfig


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

    if pieces and pieces[0] > stock:
        raise ValueError(
            f"Potongan {pieces[0]} mm > batang stok {stock} mm "
            f"(diameter {dia})")

    # 2. First fit decreasing
    bars = _ffd(pieces, stock, kerf)

    # 3. Kelompokkan batang identik -> pola + frekuensi (pelaporan murni,
    #    semua batang terwakili — tidak ada yang dibuang)
    pola_counts: Counter[tuple] = Counter()
    for bar in bars:
        key = tuple(sorted(bar, reverse=True))
        pola_counts[key] += 1

    return _build(cfg, dia, pola_counts, stock, kerf)


def optimize_all(cuts: list[Cut], cfg) -> dict[int, OptimizeResult]:
    """Optimasi semua diameter, terpisah per diameter."""
    out: dict[int, OptimizeResult] = {}
    cuts = sorted(cuts, key=lambda c: c.dia)
    for dia, group in groupby(cuts, key=lambda c: c.dia):
        out[dia] = optimize(list(group), cfg)
    return out


def _ffd(pieces: list[int], stock: int, kerf: int) -> list[list[int]]:
    """FFD murni — satu-satunya implementasi penempatan (PATCH-01 §3.3).

    Kerf dihitung ulang dari isi batang di _build(); fungsi ini hanya
    menempatkan. Return list batang, tiap batang = list panjang potongan.
    """
    pieces = sorted(pieces, reverse=True)
    bars: list[list[int]] = []
    sisa: list[int] = []

    for p in pieces:
        placed = False
        for i, s in enumerate(sisa):
            # kerf hanya antar potongan: potongan pertama di batang tanpa kerf
            need = p if not bars[i] else p + kerf
            if s >= need:
                bars[i].append(p)
                sisa[i] = s - need
                placed = True
                break
        if not placed:
            bars.append([p])
            sisa.append(stock - p)
    return bars


def _build(cfg, dia, pola_counts: Counter, stock, kerf) -> OptimizeResult:
    """Susun OptimizeResult + cek invariant (PATCH-01 §3.2)."""
    sisa_min = cfg.stok.sisa_min_simpan_mm
    patterns: list[Pattern] = []
    total_batang = 0
    total_kerf = 0
    total_sisa = 0
    sisa_reusable = 0
    total_terpakai = 0

    # urut pola: frekuensi tertinggi dulu, lalu isi (05-SPEC-output §3)
    for key, freq in sorted(pola_counts.items(), key=lambda kv: (-kv[1], kv[0])):
        potongan = tuple(sorted(key, reverse=True))
        panjang_potongan = sum(potongan)
        # kerf per batang: antar potongan = (n_potongan - 1) × kerf
        kerf_per_barang = max(len(potongan) - 1, 0) * kerf

        # INVARIANT 1 — kelayakan pola (PATCH-01 §3.2)
        if panjang_potongan + kerf_per_barang > stock:
            raise InfeasiblePatternError(
                f"BUG INTERNAL: pola {potongan} tidak layak dieksekusi — "
                f"sum {panjang_potongan} + kerf {kerf_per_barang} = "
                f"{panjang_potongan + kerf_per_barang} > stok {stock}. "
                f"Laporkan ke developer; ini bukan masalah data input.")

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

    # INVARIANT 2 — konsistensi frekuensi (PATCH-01 §3.2)
    sum_freq = sum(p.frekuensi for p in patterns)
    if sum_freq != total_batang:
        raise InfeasiblePatternError(
            f"BUG INTERNAL: sum(frekuensi)={sum_freq} != total_batang="
            f"{total_batang} — ada batang yang tidak terwakili pola. "
            f"Laporkan ke developer; ini bukan masalah data input.")

    total_stok = total_batang * stock
    waste_bersih = max(total_sisa - sisa_reusable, 0)
    waste_pct = (waste_bersih / total_stok * 100) if total_stok else 0.0
    waste_kotor_pct = (total_sisa / total_stok * 100) if total_stok else 0.0

    # PATCH-01: pembatasan pola dihapus — metrik sebelum == sesudah
    n_pola = len(patterns)
    return OptimizeResult(
        dia=dia, patterns=patterns, total_batang=total_batang,
        total_panjang_stok_mm=total_stok,
        total_panjang_terpakai_mm=total_terpakai,
        total_kerf_mm=total_kerf, total_sisa_mm=total_sisa,
        sisa_reusable_mm=sisa_reusable, waste_pct=round(waste_pct, 4),
        waste_kotor_pct=round(waste_kotor_pct, 4),
        pola_sebelum_batasi=n_pola,
        pola_sesudah_batasi=n_pola,
        waste_pct_tanpa_batasi=round(waste_pct, 4),
    )
