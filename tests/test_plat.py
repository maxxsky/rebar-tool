"""Tests 13-SPEC Plat — jumlah dari jarak, dua dimensi, zona tumpuan.

Test pertama paling penting: balok & kolom TIDAK berubah.
"""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "web"))

import dataclasses
from bbs import generate_bbs, generate_elemen, hitung_jumlah_dari_jarak
from config_loader import load_all, _parse_template
from models import ConfigError, ElemenInput, PlatConfig

CONFIG_DIR = REPO / "config"


@pytest.fixture(scope="module")
def cfg():
    c, _ = load_all(CONFIG_DIR)
    return c


@pytest.fixture(scope="module")
def templates():
    _, t = load_all(CONFIG_DIR)
    return t


@pytest.fixture(scope="module")
def client():
    from app import app
    app.config["TESTING"] = True
    return app.test_client()


# ── 1. balok & kolom tidak berubah ──────────────────────────
def test_balok_kolom_tidak_berubah(cfg, templates):
    # pakai PRJ-001 (layered) yang punya B1, B2, K1
    from config_loader import load_layered
    c2, t2, _ = load_layered(CONFIG_DIR / "projects", "PRJ-001", "GS-01")
    elemen = [ElemenInput(tipe="B1", bentang_bersih_mm=6000, jumlah=12),
              ElemenInput(tipe="B2", bentang_bersih_mm=4000, jumlah=20),
              ElemenInput(tipe="K1", bentang_bersih_mm=3500, jumlah=2)]
    cuts = generate_bbs(t2, elemen, c2)
    counts = {}
    for c in cuts:
        key = (c.dia, c.panjang_mm)
        counts[key] = counts.get(key, 0) + c.jumlah
    assert counts[(19, 7520)] == 84          # B1 atas+bawah
    assert counts[(13, 7040)] == 24          # B1 pinggang
    assert counts[(10, 1640)] == 408         # B1 sengkang
    assert counts[(19, 4490)] == 16          # K1 (8 × 2)


def _plat_template(cfg):
    """Plat S1: 6000×4000, D10-150 dua arah + tulangan tumpuan zona 2."""
    return _parse_template("plat", "S1", {
        "b_mm": 0, "h_mm": 0,
        "label_L": "Bentang X", "label_L2": "Bentang Y",
        "bantuan_L": "Bentang bersih arah X, muka ke muka tumpuan.",
        "tulangan": [
            {"posisi": "bawah arah X", "dia": 10, "arah": "X", "jarak_mm": 150,
             "shape": "01", "vars": {"L": "Lx + 2*Ld"}},
            {"posisi": "bawah arah Y", "dia": 10, "arah": "Y", "jarak_mm": 150,
             "shape": "01", "vars": {"L": "Ly + 2*Ld"}},
            {"posisi": "tumpuan arah X", "dia": 10, "arah": "X", "jarak_mm": 150,
             "zona": 2, "shape": "01", "vars": {"L": "Lx/4 + Ld + tekuk",
                                                "tekuk": 200}},
        ],
        "sengkang": [],
    })


# ── 2. jumlah dari jarak ────────────────────────────────────
def test_jumlah_dari_jarak(cfg):
    # Ly=6000, jarak 150, tepi 50 → floor(5900/150)+1 = floor(39.33)+1 = 40
    n = hitung_jumlah_dari_jarak(6000, 150, cfg)
    assert n == 40


# ── 3. metode ceil ──────────────────────────────────────────
def test_metode_ceil(cfg):
    c2 = dataclasses.replace(cfg, plat_cfg=PlatConfig(
        jarak_tepi_mm=50, metode_hitung="ceil"))
    n = hitung_jumlah_dari_jarak(6000, 150, c2)
    assert n == ceil_harapan(6000, 150)  # ceil(5900/150) = 40 (sama di sini)
    # kasus yang beda: 5900/150 = 39.33 → floor+1=40, ceil=40 (sama)
    # pakai W yang bikin beda: 6000, jarak 200, tepi 50 → 5900/200=29.5
    # floor+1=30, ceil=30 — cari yang beneran beda: 5800, jarak 200, tepi 50
    # → 5700/200 = 28.5 → floor+1=29, ceil=29. masih sama?
    # beda muncul pas hasil TEPAT bulat: 5850, jarak 150, tepi 50 → 5750/150
    # = 38.33 floor+1=39, ceil=39. hmm.
    # 6000, jarak 100, tepi 50 → 5900/100=59 floor+1=60, ceil=59 → BEDA!
    n2 = hitung_jumlah_dari_jarak(6000, 100, c2)
    assert n2 == 59
    n3 = hitung_jumlah_dari_jarak(6000, 100, cfg)
    assert n3 == 60


def ceil_harapan(W, jarak):
    from math import ceil
    return max(1, ceil((W - 100) / jarak)) if W - 100 > 0 else 0


# ── 4. dua arah — hitung tangan ─────────────────────────────
def test_dua_arah(cfg):
    tpl = _plat_template(cfg)
    el = ElemenInput(tipe="S1", bentang_bersih_mm=6000, jumlah=1, L2_mm=4000)
    cuts = generate_elemen(tpl, el, cfg)
    by_pos = {}
    for c in cuts:
        by_pos.setdefault(c.posisi, []).append(c)
    # arah X: panjang ikut Lx=6000, jumlah dari Ly=4000 → floor(3900/150)+1=27
    x = by_pos["bawah arah X"][0]
    assert x.panjang_mm == 6000 + 2 * 400     # Lx + 2*Ld (Ld D10 = 400)
    assert x.jumlah == 27
    # arah Y: panjang ikut Ly=4000, jumlah dari Lx=6000 → floor(5900/150)+1=40
    y = by_pos["bawah arah Y"][0]
    assert y.panjang_mm == 4000 + 2 * 400
    assert y.jumlah == 40


# ── 5. tulangan zona ────────────────────────────────────────
def test_tulangan_zona(cfg):
    tpl = _plat_template(cfg)
    el = ElemenInput(tipe="S1", bentang_bersih_mm=6000, jumlah=1, L2_mm=4000)
    cuts = generate_elemen(tpl, el, cfg)
    tumpuan = [c for c in cuts if c.posisi == "tumpuan arah X"][0]
    # jumlah = 27 (dari Ly) × zona 2 = 54
    assert tumpuan.jumlah == 54
    # panjang = Lx/4 + Ld + tekuk = 1500 + 400 + 200 = 2100
    assert tumpuan.panjang_mm == 2100


# ── 6. jumlah & jarak bersamaan → ConfigError ───────────────
def test_jumlah_dan_jarak_bersamaan():
    with pytest.raises(ConfigError, match="jumlah"):
        _parse_template("plat", "SX", {
            "b_mm": 0, "h_mm": 0,
            "tulangan": [{"posisi": "x", "dia": 10, "arah": "X",
                          "jarak_mm": 150, "jumlah": 5}],
            "sengkang": []})


# ── 7. tanpa jumlah & jarak → ConfigError ───────────────────
def test_tanpa_jumlah_dan_jarak():
    with pytest.raises(ConfigError, match="jumlah"):
        _parse_template("plat", "SX", {
            "b_mm": 0, "h_mm": 0,
            "tulangan": [{"posisi": "x", "dia": 10, "arah": "X"}],
            "sengkang": []})


# ── 8. L2 wajib utk plat (via API) ──────────────────────────
def test_L2_wajib_untuk_plat(client, tmp_path):
    # template S1 ada di PRJ-001? tambah dulu via API biar test mandiri
    import yaml
    # buat proyek sementara
    p = CONFIG_DIR / "projects" / "PLX1"
    (p / "drawings").mkdir(parents=True, exist_ok=True)
    (p / "project.yaml").write_text(yaml.safe_dump({
        "proyek": {"nama": "PLX", "kode": "PLX1"},
        "sumber": {"dokumen": "D", "revisi": "R1", "tanggal": "2026-01-01"},
        "stok": {"panjang_batang_mm": 12000, "kerf_mm": 3,
                 "sisa_min_simpan_mm": 1000},
        "selimut_beton_mm": {"balok": 40, "kolom": 40, "plat": 20},
        "panjang_penyaluran_mm": {10: 400, 13: 520, 16: 640, 19: 760},
        "lap_splice_mm": {10: 520, 13: 680, 16: 830, 19: 990},
        "unit_weight_kg_per_m": {10: 0.617, 13: 1.042, 16: 1.578, 19: 2.226},
        "hook": {"tail_135_mm": {10: 80}, "tail_90_mm": {10: 120},
                 "diameter_bengkok_faktor": 4,
                 "koreksi_bengkokan_aktif": False},
        "sengkang": {"zona_tumpuan_faktor": 0.25,
                     "jarak_sengkang_pertama_mm": 50},
        "optimizer": {"max_pola": 8, "batasi_pola": False},
        "plat": {"jarak_tepi_mm": 50, "metode_hitung": "floor_plus_1"},
    }))
    (p / "templates.yaml").write_text(yaml.safe_dump({
        "plat": {"S1": {
            "b_mm": 0, "h_mm": 0, "label_L": "Bentang X",
            "label_L2": "Bentang Y",
            "tulangan": [{"posisi": "bawah arah X", "dia": 10, "arah": "X",
                          "jarak_mm": 150,
                          "vars": {"L": "Lx + 2*Ld"}}],
            "sengkang": []}}}))
    (p / "drawings" / "D1.yaml").write_text(yaml.safe_dump(
        {"kode": "D1", "nama": "D", "revisi": "R1", "tanggal": "2026-01-01",
         "override": {}}))
    try:
        # tanpa L2 → 400
        r = client.post("/api/hitung", json={
            "proyek": "PLX1", "gambar": "D1",
            "elemen": [{"tipe": "S1", "L_mm": 6000, "jumlah": 1}]})
        assert r.status_code == 400
        assert "L2_mm" in r.get_json()["error"]
        # dengan L2 → 200
        r2 = client.post("/api/hitung", json={
            "proyek": "PLX1", "gambar": "D1",
            "elemen": [{"tipe": "S1", "L_mm": 6000, "L2_mm": 4000,
                        "jumlah": 1}]})
        assert r2.status_code == 200, r2.get_json()
    finally:
        import shutil
        shutil.rmtree(p, ignore_errors=True)


# ── 9. L2 diabaikan utk balok ───────────────────────────────
def test_L2_diabaikan_untuk_balok(client):
    r1 = client.post("/api/hitung", json={
        "proyek": "PRJ-001", "gambar": "GS-01",
        "elemen": [{"tipe": "B1", "bentang_bersih_mm": 6000, "jumlah": 1}]})
    r2 = client.post("/api/hitung", json={
        "proyek": "PRJ-001", "gambar": "GS-01",
        "elemen": [{"tipe": "B1", "bentang_bersih_mm": 6000, "jumlah": 1,
                    "L2_mm": 9999}]})
    b1 = {(b["dia"], b["panjang_mm"]): b["jumlah"] for b in r1.get_json()["bbs"]}
    b2 = {(b["dia"], b["panjang_mm"]): b["jumlah"] for b in r2.get_json()["bbs"]}
    assert b1 == b2


# ── 10. arah menentukan panjang & jumlah ────────────────────
def test_arah_menentukan_panjang(cfg):
    tpl = _plat_template(cfg)
    el = ElemenInput(tipe="S1", bentang_bersih_mm=6000, jumlah=1, L2_mm=4000)
    cuts = generate_elemen(tpl, el, cfg)
    x = [c for c in cuts if c.posisi == "bawah arah X"][0]
    y = [c for c in cuts if c.posisi == "bawah arah Y"][0]
    # arah X: panjang 6800 (dari Lx), jumlah 27 (dari Ly)
    assert x.panjang_mm == 6800 and x.jumlah == 27
    # arah Y: panjang 4800 (dari Ly), jumlah 40 (dari Lx)
    assert y.panjang_mm == 4800 and y.jumlah == 40
