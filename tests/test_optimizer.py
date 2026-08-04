"""Tests optimizer (F1) — spec 03-SPEC-optimizer.md §6.

Wajib:
- A: trivial exact fit
- B: butuh 2 batang
- C: kerf antar-potongan (bukan per potongan)
- D: konservasi — 5+ seed acak
- E: potongan > stok → ValueError
- F: pembatasan pola
- G: sisa reusable
"""

import random
import sys
from collections import Counter
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from config_loader import load_all
from models import Cut, OptimizerConfig, ProjectConfig
from optimizer import optimize, optimize_all

CONFIG_DIR = REPO / "config"


def _cfg(panjang=12000, kerf=0, sisa_min=1000, max_pola=8, batasi=True):
    cfg, _ = load_all(CONFIG_DIR)
    import dataclasses
    return dataclasses.replace(
        cfg,
        stok=dataclasses.replace(cfg.stok, panjang_batang_mm=panjang,
                                 kerf_mm=kerf, sisa_min_simpan_mm=sisa_min),
        optimizer=OptimizerConfig(max_pola=max_pola, batasi_pola=batasi),
    )


def _cut(dia, panjang, jumlah):
    return Cut(dia=dia, panjang_mm=panjang, jumlah=jumlah)


def _total_potongan_hasil(r):
    total = 0
    for p in r.patterns:
        total += sum(p.potongan) * p.frekuensi
    return total


# ── A — trivial exact fit ───────────────────────────────────
def test_kasus_a_exact_fit():
    r = optimize([_cut(10, 3000, 4)], _cfg(kerf=0))
    assert r.total_batang == 1
    assert len(r.patterns) == 1
    assert r.patterns[0].potongan == (3000, 3000, 3000, 3000)
    assert r.patterns[0].sisa_mm == 0
    assert r.waste_pct == 0.0


# ── B — butuh 2 batang ─────────────────────────────────────
def test_kasus_b_dua_batang():
    r = optimize([_cut(10, 3000, 5)], _cfg(kerf=0))
    assert r.total_batang == 2
    pola = {p.potongan: p.frekuensi for p in r.patterns}
    assert pola == {(3000, 3000, 3000, 3000): 1, (3000,): 1}
    assert r.total_sisa_mm == 9000


# ── C — kerf antar-potongan ─────────────────────────────────
def test_kasus_c_kerf_antar_potongan():
    # 4×3000, kerf 10: terpakai = 3000×4 + 10×3 = 12030 > 12000 → 2 batang
    r = optimize([_cut(10, 3000, 4)], _cfg(kerf=10))
    assert r.total_batang == 2, "kalau 1 batang, kerf salah implementasi"
    # kerf total: batang 1 isi 3 potongan (2 kerf=20), batang 2 isi 1 (0 kerf)
    assert r.total_kerf_mm == 20


# ── D — konservasi, 5+ seed ─────────────────────────────────
@pytest.mark.parametrize("seed", range(5))
def test_kasus_d_konservasi(seed):
    rng = random.Random(seed)
    inputs = [_cut(13, rng.randint(500, 5000), rng.randint(1, 4))
              for _ in range(40)]
    r = optimize(inputs, _cfg(kerf=3))
    total_input = sum(c.panjang_mm * c.jumlah for c in inputs)
    assert r.total_panjang_terpakai_mm == total_input
    assert _total_potongan_hasil(r) == total_input


def test_kasus_d_konservasi_200_potongan():
    rng = random.Random(42)
    inputs = []
    for _ in range(200):
        dia = rng.choice([10, 13, 16])
        inputs.append(_cut(dia, rng.randint(500, 5000), rng.randint(1, 5)))
    # gabung per diameter via optimize_all
    results = optimize_all(inputs, _cfg(kerf=3))
    for dia, r in results.items():
        total_input = sum(c.panjang_mm * c.jumlah
                          for c in inputs if c.dia == dia)
        assert r.total_panjang_terpakai_mm == total_input
        assert _total_potongan_hasil(r) == total_input


# ── E — potongan > stok ────────────────────────────────────
def test_kasus_e_potongan_lebih_dari_stok():
    with pytest.raises(ValueError):
        optimize([_cut(10, 13000, 1)], _cfg())


# ── F — pembatasan pola ────────────────────────────────────
def test_kasus_f_pembatasan_pola():
    rng = random.Random(7)
    inputs = [_cut(16, rng.randint(800, 4000), rng.randint(1, 3))
              for _ in range(60)]
    r = optimize(inputs, _cfg(kerf=2, max_pola=8, batasi=True))
    assert r.pola_sesudah_batasi <= 8
    # konservasi tetap
    total_input = sum(c.panjang_mm * c.jumlah for c in inputs)
    assert _total_potongan_hasil(r) == total_input
    # waste dengan pembatasan >= tanpa
    assert r.waste_pct >= r.waste_pct_tanpa_batasi - 0.01


def test_kasus_f_tanpa_batasi_sama_dengan_before():
    rng = random.Random(7)
    inputs = [_cut(16, rng.randint(800, 4000), rng.randint(1, 3))
              for _ in range(60)]
    r = optimize(inputs, _cfg(kerf=2, max_pola=8, batasi=True))
    assert r.pola_sebelum_batasi >= r.pola_sesudah_batasi


# ── G — sisa reusable ──────────────────────────────────────
def test_kasus_g_sisa_reusable():
    cfg = _cfg(kerf=0, sisa_min=1000)
    r = optimize([_cut(10, 10500, 1), _cut(10, 11200, 1)], cfg)
    # batang 1: 12000-10500 = 1500 → reusable; batang 2: 800 → bukan
    reusable = {p.sisa_mm: p.reusable for p in r.patterns}
    assert reusable[1500] is True
    assert reusable[800] is False
    assert r.sisa_reusable_mm == 1500


# ── optimize_all pisah per diameter ────────────────────────
def test_optimize_all_terpisah_per_diameter():
    inputs = [_cut(10, 3000, 2), _cut(13, 4000, 2)]
    results = optimize_all(inputs, _cfg(kerf=0))
    assert set(results.keys()) == {10, 13}
    assert results[10].total_batang == 1
    assert results[13].total_batang == 1
    # potongan D10 tidak boleh tercampur di hasil D13
    for p in results[13].patterns:
        assert all(x != 3000 for x in p.potongan)


# ── CLI: jalankan dari CSV ─────────────────────────────────
def test_cli_standalone_csv(tmp_path):
    csv_path = tmp_path / "potongan.csv"
    csv_path.write_text("dia,panjang_mm,jumlah\n10,3000,5\n13,4000,2\n")
    import subprocess
    r = subprocess.run(
        [sys.executable, str(REPO / "src" / "cli.py"), "optimize",
         str(csv_path), "--config", str(CONFIG_DIR)],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "OPTIMIZER" in r.stdout
    assert "10 mm" in r.stdout and "13 mm" in r.stdout
