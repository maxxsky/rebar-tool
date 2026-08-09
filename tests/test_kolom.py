"""Tests 12-SPEC Kolom — sengkang daftar, dimensi utama L, zona panjang,
max()/min() di parser.

Dua test pertama paling penting: balok TIDAK berubah setelah migrasi.
"""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "web"))

import dataclasses
import tempfile
from bbs import generate_bbs, generate_elemen, hitung_jumlah_sengkang
from config_loader import load_all, load_templates, _parse_template
from models import ConfigError, ElemenInput, SengkangConfig, TemplateSengkang
from shapes import evaluasi_ekspresi, parse_ekspresi

CONFIG_DIR = REPO / "config"


@pytest.fixture(scope="module")
def client():
    from app import app
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture(scope="module")
def cfg():
    c, _ = load_all(CONFIG_DIR)
    return c


@pytest.fixture(scope="module")
def templates():
    _, t = load_all(CONFIG_DIR)
    return t


# ── 1. migrasi sengkang objek → daftar — balok identik ─────
def test_migrasi_sengkang_objek_ke_daftar(cfg, templates):
    # sengkang template B1 sekarang tuple (hasil migrasi objek lama)
    sk = templates["B1"].sengkang
    assert isinstance(sk, tuple) and len(sk) == 1
    assert sk[0].dia == 10
    assert sk[0].jumlah_per_set == 1
    # hitung tetap 1640 × 34
    elemen = [ElemenInput(tipe="B1", bentang_bersih_mm=6000, jumlah=1)]
    cuts = generate_bbs(templates, elemen, cfg)
    sengkang = [c for c in cuts if c.posisi == "sengkang"]
    assert len(sengkang) == 1
    assert sengkang[0].panjang_mm == 1640
    assert sengkang[0].jumlah == 34


# ── 2. balok tidak berubah — B1 & B2 identik ────────────────
def test_balok_tidak_berubah(cfg, templates):
    elemen = [ElemenInput(tipe="B1", bentang_bersih_mm=6000, jumlah=12),
              ElemenInput(tipe="B2", bentang_bersih_mm=4000, jumlah=20)]
    cuts = generate_bbs(templates, elemen, cfg)
    counts = {}
    for c in cuts:
        key = (c.dia, c.panjang_mm)
        counts[key] = counts.get(key, 0) + c.jumlah
    # golden lama
    assert counts[(19, 7520)] == 84
    assert counts[(13, 7040)] == 24
    assert counts[(10, 1640)] == 408


# ── 3. kolom tulangan utama — K1 tinggi 3500, stek 990 ─────
def _kolom_template(cfg):
    """Template kolom K1: 8D19, sengkang luar + ikat."""
    tpl = _parse_template("kolom", "K1", {
        "b_mm": 400, "h_mm": 400,
        "label_L": "Tinggi bersih",
        "bantuan_L": "Muka atas pelat bawah ke muka bawah balok.",
        "tulangan": [
            {"posisi": "utama", "dia": 19, "jumlah": 8, "shape": "01",
             "vars": {"L": "H + stek", "stek": 990}},
        ],
        "sengkang": [
            {"nama": "sengkang luar", "dia": 10, "shape": "51",
             "hook_sudut": 135, "kaki": 2, "jumlah_per_set": 1,
             "jarak_tumpuan_mm": 100, "jarak_lapangan_mm": 150},
            {"nama": "sengkang ikat", "dia": 10, "shape": "51",
             "hook_sudut": 135, "kaki": 2, "jumlah_per_set": 2,
             "jarak_tumpuan_mm": 100, "jarak_lapangan_mm": 150},
        ],
    })
    return tpl


def test_kolom_tulangan_utama(cfg):
    tpl = _kolom_template(cfg)
    elemen = [ElemenInput(tipe="K1", bentang_bersih_mm=3500, jumlah=1)]
    cuts = generate_elemen(tpl, elemen[0], cfg)
    utama = [c for c in cuts if c.posisi == "utama"]
    # L = 3500 + 990 = 4490 (8 batang)
    assert len(utama) == 1
    assert utama[0].panjang_mm == 4490
    assert utama[0].jumlah == 8


# ── 4. kolom dua kelompok sengkang — 3× jumlah set ──────────
def test_kolom_sengkang_dua_kelompok(cfg):
    tpl = _kolom_template(cfg)
    elemen = [ElemenInput(tipe="K1", bentang_bersih_mm=3500, jumlah=1)]
    cuts = generate_elemen(tpl, elemen[0], cfg)
    sk = [c for c in cuts if c.posisi == "sengkang"]
    assert len(sk) == 2
    # jumlah batang: luar 1×n, ikat 2×n → ikat 2× luar
    luar = [c for c in sk if c.bar_mark.endswith("a")][0]
    ikat = [c for c in sk if c.bar_mark.endswith("b")][0]
    assert ikat.jumlah == 2 * luar.jumlah
    # bar mark akhiran a/b karena 2 kelompok
    assert luar.bar_mark.endswith("a")
    assert ikat.bar_mark.endswith("b")


# ── 5. zona metode panjang — hitung tangan ──────────────────
def test_zona_metode_panjang(cfg):
    c2 = dataclasses.replace(
        cfg, sengkang_cfg=dataclasses.replace(
            cfg.sengkang_cfg, zona_metode="panjang",
            zona_lo_ekspresi="max(h, L/6, 450)"))
    sk = TemplateSengkang(dia=10, jarak_tumpuan_mm=100,
                          jarak_lapangan_mm=150, kaki=2, hook_sudut=135)
    # h = 400 (dari cfg? — pakai ekspresi dengan h tersedia di vars; utk
    # hitung_jumlah_sengkang zona panjang, h diambil dari... test langsung
    # pakai ekspresi dgn L saja: max(L/6, 450)
    # L=3500: L/6=583.3, 450 → max = 583
    c3 = dataclasses.replace(
        cfg, sengkang_cfg=dataclasses.replace(
            cfg.sengkang_cfg, zona_metode="panjang",
            zona_lo_ekspresi="max(L/6, 450)"))
    n = hitung_jumlah_sengkang(3500, sk, c3)
    # Lt=583, Ll=3500-1166=2334
    # tumpuan: 1 + floor((583-50)/100)=1+5=6 per sisi → 12
    # lapangan: ceil(2334/150)-1 = 16-1 = 15
    assert n == 12 + 15  # 27


# ── 6. zona rasio tidak berubah ─────────────────────────────
def test_zona_metode_rasio_tidak_berubah(cfg):
    sk = TemplateSengkang(dia=10, jarak_tumpuan_mm=150,
                          jarak_lapangan_mm=200, kaki=2, hook_sudut=135)
    n = hitung_jumlah_sengkang(6000, sk, cfg)
    assert n == 34  # golden


# ── 7. max/min ekspresi ─────────────────────────────────────
def test_max_min_ekspresi():
    assert evaluasi_ekspresi("max(h, L/6, 450)",
                             {"h": 400, "L": 3500}, "x") == 583.3333333333334
    assert evaluasi_ekspresi("max(h, L/6, 450)",
                             {"h": 700, "L": 3500}, "x") == 700
    assert evaluasi_ekspresi("min(h, 500)", {"h": 700}, "x") == 500


# ── 8. parser tetap aman setelah max/min ────────────────────
def test_parser_tetap_aman():
    for payload in ["__import__('os').system('x')",
                    "open('/etc/passwd')",
                    "max() if True else 1",
                    "L + __import__('os')"]:
        with pytest.raises(ConfigError):
            parse_ekspresi(payload, "shape.21")


# ── 9. kolom sambungan — tinggi > stok → terpecah ───────────
def test_kolom_sambungan(cfg):
    tpl = _kolom_template(cfg)
    elemen = [ElemenInput(tipe="K1", bentang_bersih_mm=12000, jumlah=1)]
    cuts = generate_elemen(tpl, elemen[0], cfg)
    utama = [c for c in cuts if c.posisi == "utama" and c.bagian]
    # L = 12000 + 990 = 12990 > 12000 → pecah; 8 batang × 2 potongan = 16
    assert len(utama) == 16
    # potongan a (1/2) dan b (2/2) ada
    assert any(c.bagian == (1, 2) for c in utama)
    assert any(c.bagian == (2, 2) for c in utama)
    assert all(c.panjang_mm <= cfg.stok.panjang_batang_mm for c in utama)


# ── 10. spiral ditolak ──────────────────────────────────────
def test_spiral_ditolak():
    with pytest.raises(ConfigError, match="spiral"):
        _parse_template("kolom", "KX", {
            "b_mm": 400, "h_mm": 400,
            "tulangan": [{"posisi": "utama", "dia": 19, "jumlah": 8}],
            "sengkang": [{"dia": 10, "shape": "spiral",
                          "hook_sudut": 135}]})


# ── 11. L_mm alias bentang_bersih_mm (via API) ──────────────
def test_L_mm_alias(client):
    payload_lama = {"proyek": "PRJ-001", "gambar": "GS-01",
                    "elemen": [{"tipe": "B1", "bentang_bersih_mm": 6000,
                                "jumlah": 1}]}
    payload_baru = {"proyek": "PRJ-001", "gambar": "GS-01",
                    "elemen": [{"tipe": "B1", "L_mm": 6000, "jumlah": 1}]}
    r1 = client.post("/api/hitung", json=payload_lama).get_json()
    r2 = client.post("/api/hitung", json=payload_baru).get_json()
    b1 = {(b["dia"], b["panjang_mm"]): b["jumlah"] for b in r1["bbs"]}
    b2 = {(b["dia"], b["panjang_mm"]): b["jumlah"] for b in r2["bbs"]}
    assert b1 == b2
