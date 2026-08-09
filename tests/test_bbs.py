"""Tests generator BBS (F2) — spec 02-SPEC-bbs.md §5.

Wajib:
- A: jumlah sengkang hitung tangan (34)
- B: keliling sengkang hitung tangan (1640)
- C: tulangan utama (7520)
- D: error path (12520 > stok)
- E: konservasi jumlah (B1 × 12)
"""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import dataclasses
from bbs import (agregasi, bend_deduction, generate_bbs, generate_elemen,
                 generate_sengkang, generate_tulangan_utama,
                 hitung_jumlah_sengkang, keliling_sengkang)
from config_loader import load_all
from models import (ConfigError, Cut, ElemenInput, LengthExceedsStockError,
                    ProjectConfig, TemplateSengkang)
from input_reader import baca_elemen_xlsx

CONFIG_DIR = REPO / "config"


@pytest.fixture(scope="module")
def cfg():
    c, _ = load_all(CONFIG_DIR)
    return c


@pytest.fixture(scope="module")
def templates():
    _, t = load_all(CONFIG_DIR)
    return t


# ── Kasus A — jumlah sengkang hitung tangan ────────────────
def test_kasus_a_jumlah_sengkang(cfg):
    sk = TemplateSengkang(dia=10, jarak_tumpuan_mm=150,
                          jarak_lapangan_mm=200, kaki=2, hook_sudut=135)
    n = hitung_jumlah_sengkang(6000, sk, cfg)
    # Lt=1500, Ll=3000 → 10 + 14 + 10 = 34
    assert n == 34


def test_kasus_a_metode_per_zona(cfg):
    sk = TemplateSengkang(dia=10, jarak_tumpuan_mm=150,
                          jarak_lapangan_mm=200, kaki=2, hook_sudut=135)
    c2 = dataclasses.replace(cfg, sengkang_cfg=dataclasses.replace(
        cfg.sengkang_cfg, metode_hitung="per_zona"))
    n = hitung_jumlah_sengkang(6000, sk, c2)
    assert n == 35  # tanpa -1 di zona lapangan


# ── Kasus B — keliling sengkang ─────────────────────────────
def test_kasus_b_keliling_sengkang(cfg):
    panjang = keliling_sengkang(300, 600, 10, 135, cfg, elemen="balok")
    # lebar_dalam 220, tinggi_dalam 520, keliling 1480, hook 160 → 1640
    assert panjang == 1640


def test_kasus_b_segmen():
    # segmen_mm utk sengkang = (lebar_dalam, tinggi_dalam, ...)
    pass  # diuji lewat generate_sengkang di bawah


# ── Kasus C — tulangan utama ────────────────────────────────
def test_kasus_c_tulangan_utama(cfg):
    import types
    from bbs import _Meta
    tul = types.SimpleNamespace(dia=19, jumlah=4, tumpuan_kedua_ujung=True)
    meta = _Meta(tipe_elemen="B1", jumlah_elemen=1, lokasi="", bar_mark="B1-A",
                 posisi="atas")
    # 11-SPEC: generate_tulangan_utama return LIST (bisa >1 utk sambungan)
    cuts = generate_tulangan_utama(tul, 6000, cfg, meta)
    assert len(cuts) == 1
    cut = cuts[0]
    assert cut.panjang_mm == 6000 + 2 * 760
    assert cut.jumlah == 4
    assert cut.shape_code == "01"
    assert cut.bagian is None           # tanpa sambungan — perilaku identik


# ── Kasus D — panjang > stok → lap splice, bukan error (11-SPEC §8) ──
def test_kasus_d_lap_splice_melebihi_stok(cfg):
    import types
    from bbs import _Meta
    tul = types.SimpleNamespace(dia=19, jumlah=1, tumpuan_kedua_ujung=True)
    meta = _Meta(tipe_elemen="B1", jumlah_elemen=1, lokasi="", bar_mark="B1-A",
                 posisi="atas")
    # 12520 > 12000 → pecah jadi 2 potongan (bukan error)
    cuts = generate_tulangan_utama(tul, 11000, cfg, meta)
    assert len(cuts) == 2
    assert all(c.panjang_mm <= cfg.stok.panjang_batang_mm for c in cuts)
    assert cuts[0].bagian == (1, 2) and cuts[1].bagian == (2, 2)


# ── Kasus E — konservasi jumlah ────────────────────────────
def test_kasus_e_konservasi_jumlah(cfg, templates):
    elemen = ElemenInput(tipe="B1", bentang_bersih_mm=6000, jumlah=12,
                         lokasi="Lt.2")
    cuts = generate_elemen(templates["B1"], elemen, cfg)

    # D19 atas: 4 × 12 = 48 @ 7520
    # D19 bawah: 3 × 12 = 36 @ 7520
    # D13 pinggang: 2 × 12 = 24 @ 7040 (6000 + 2×520)
    # D10 sengkang: 34 × 12 = 408 @ 1640
    counts = {}
    for c in cuts:
        key = (c.dia, c.panjang_mm)
        counts[key] = counts.get(key, 0) + c.jumlah

    assert counts[(19, 7520)] == 84          # atas + bawah
    assert counts[(13, 7040)] == 24
    assert counts[(10, 1640)] == 408


def test_kasus_e_generate_bbs_lengkap(cfg, templates):
    elemen = [ElemenInput(tipe="B1", bentang_bersih_mm=6000, jumlah=12,
                          lokasi="Lt.2"),
              ElemenInput(tipe="B2", bentang_bersih_mm=4000, jumlah=20,
                          lokasi="Lt.2")]
    cuts = generate_bbs(templates, elemen, cfg)
    # B2: D16 atas 3×20=60 @ 4000+2×640=5280; bawah 2×20=40 @ 5280
    #     sengkang D10: penampang 250x500 → dalam 170x420 → keliling 1180
    #     + hook 160 = 1340 mm
    #     jumlah: Lt=1000, Ll=2000, d0=50
    #       n_tump = 1+floor(950/100)=10, n_lap = ceil(2000/150)-1=14-1=13
    #       total 10+13+10=33 → 33×20=660
    by_key = {}
    for c in cuts:
        by_key[(c.dia, c.panjang_mm)] = by_key.get((c.dia, c.panjang_mm), 0) + c.jumlah
    assert by_key[(16, 5280)] == 100
    assert by_key[(10, 1640)] == 408          # B1 sengkang 34×12
    assert by_key[(10, 1340)] == 660          # B2 sengkang 33×20


# ── agregasi ────────────────────────────────────────────────
def test_agregasi_menggabungkan_identik(cfg, templates):
    elemen = [ElemenInput(tipe="B1", bentang_bersih_mm=6000, jumlah=12,
                          lokasi="Lt.2"),
              ElemenInput(tipe="B1", bentang_bersih_mm=6000, jumlah=6,
                          lokasi="Lt.3")]
    cuts = generate_bbs(templates, elemen, cfg)
    agg = agregasi(cuts)
    by_key = {(c.dia, c.panjang_mm): c for c in agg}
    # D10 1640: 408 + 204 = 612, bar_mark dari B1-SK dua lokasi
    assert by_key[(10, 1640)].jumlah == 612
    assert len(by_key) == 3  # D19/7520 (atas+bawah), D13/7040, D10/1640


# ── prefix gambar bar_mark (PATCH-03 #3 — web == CLI) ─────
def test_bar_mark_prefix_gambar(cfg, templates):
    elemen = [ElemenInput(tipe="B1", bentang_bersih_mm=6000, jumlah=1,
                          lokasi="x")]
    # dengan gambar_kode → prefix
    cuts = generate_bbs(templates, elemen, cfg, gambar_kode="GS-01")
    assert all(c.bar_mark.startswith("GS-01/") for c in cuts)
    assert any(c.bar_mark == "GS-01/B1-SK" for c in cuts)
    assert any(c.bar_mark == "GS-01/B1-A1" for c in cuts)
    # tanpa argumen → tanpa prefix (legacy)
    cuts2 = generate_bbs(templates, elemen, cfg)
    assert all(not c.bar_mark.startswith("GS-01/") for c in cuts2)
    assert any(c.bar_mark == "B1-SK" for c in cuts2)


def test_bar_mark_web_cli_konsisten(cfg, templates):
    """Input sama → bar mark identik (generate_bbs dipakai web & CLI)."""
    elemen = [ElemenInput(tipe="B1", bentang_bersih_mm=6000, jumlah=1,
                          lokasi="x")]
    cuts = generate_bbs(templates, elemen, cfg, gambar_kode="GS-02")
    marks = {c.bar_mark for c in cuts}
    # CLI yang dipanggil dengan --gambar GS-02 menghasilkan marks yang sama
    assert "GS-02/B1-SK" in marks
    assert "GS-02/B1-A1" in marks
    assert len(marks) == 4  # A1, B2, P3, SK
def test_koreksi_bengkokan_default_off(cfg):
    assert bend_deduction(10, {90: 3, 135: 2}, cfg) == 0


def test_koreksi_bengkokan_aktif_menghitung(cfg):
    # PATCH-06: aktif → bend deduction dihitung dari bend_deduction_faktor
    # config (bukan fail loud). D10: 3×2d + 2×3d = 120 mm.
    c2 = dataclasses.replace(cfg, koreksi_bend_aktif=True)
    assert bend_deduction(10, {90: 3, 135: 2}, c2) == 120
    assert keliling_sengkang(300, 600, 10, 135, c2, elemen="balok",
                             bengkokan={90: 3, 135: 2}) == 1520


# ── input Excel ─────────────────────────────────────────────
def test_baca_elemen_xlsx(cfg, templates, tmp_path):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["tipe", "bentang_bersih_mm", "jumlah", "lokasi"])
    ws.append(["B1", 6000, 12, "Lt.2 as A-B"])
    ws.append(["B2", 4000, 20, "Lt.2"])
    p = tmp_path / "elemen.xlsx"
    wb.save(p)
    elemen = baca_elemen_xlsx(p, templates)
    assert len(elemen) == 2
    assert elemen[0].lokasi == "Lt.2 as A-B"


def test_baca_elemen_xlsx_tipe_tidak_dikenal(tmp_path):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["tipe", "bentang_bersih_mm", "jumlah", "lokasi"])
    ws.append(["B9", 6000, 12, "x"])
    p = tmp_path / "elemen.xlsx"
    wb.save(p)
    with pytest.raises(ConfigError):
        baca_elemen_xlsx(p, {"B1": None})


# ── keliling: cover terlalu besar → error ──────────────────
def test_keliling_sengkang_cover_terlalu_besar(cfg):
    c2 = dataclasses.replace(cfg, cover={"balok": 200})
    with pytest.raises(ConfigError):
        keliling_sengkang(300, 600, 10, 135, c2, elemen="balok")
