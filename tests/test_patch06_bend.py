"""Tests PATCH-06 §1 — bend deduction pada panjang potong sengkang.

Spec: PATCH-06-bend-deduction.md §1.8.

Aturan:
- koreksi_bengkokan_aktif default false → hasil TIDAK berubah (1640 mm).
- Aktif → bend deduction DIKURANGKAN (tanda minus), bukan ditambahkan.
- Faktor per sudut dari config (bend_deduction_faktor) — tidak hardcoded.
- Sudut dipakai template tapi tidak ada di config → ConfigError.
- Hasil ≤ 0 atau turun > 30% dari keliling+hook → error (kewarasan).
"""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "web"))

import dataclasses
from bbs import bend_deduction, keliling_sengkang
from config_loader import load_all
from models import ConfigError

CONFIG_DIR = REPO / "config"


@pytest.fixture(scope="module")
def cfg():
    c, _ = load_all(CONFIG_DIR)
    return c


def _cfg_aktif(cfg, faktor=None):
    """Config dengan koreksi AKTIF + bend_deduction_faktor."""
    bend_f = faktor if faktor is not None else {45: 1, 90: 2, 135: 3, 180: 4}
    return dataclasses.replace(cfg, koreksi_bend_aktif=True, bend_faktor=bend_f)


# ── 1. nonaktif → hasil tidak berubah (1640) ───────────────
def test_bend_deduction_nonaktif_tidak_mengubah(cfg):
    # B1 300x600, D10, cover 40 → 1640, sama seperti sebelum PATCH-06
    assert cfg.koreksi_bend_aktif is False
    assert bend_deduction(10, {90: 3, 135: 2}, cfg) == 0
    panjang = keliling_sengkang(300, 600, 10, 135, cfg, elemen="balok",
                                bengkokan={90: 3, 135: 2})
    assert panjang == 1640


# ── 2. aktif → berkurang (1640 − 120 = 1520) ───────────────
def test_bend_deduction_aktif_mengurangi(cfg):
    c2 = _cfg_aktif(cfg)
    # D10: 3×2d + 2×3d = 3×20 + 2×30 = 60 + 60 = 120
    assert bend_deduction(10, {90: 3, 135: 2}, c2) == 120
    panjang = keliling_sengkang(300, 600, 10, 135, c2, elemen="balok",
                                bengkokan={90: 3, 135: 2})
    assert panjang == 1640 - 120 == 1520


# ── 3. tanda minus — hasil lebih kecil dari keliling+hook ──
def test_bend_deduction_tanda_minus(cfg):
    c2 = _cfg_aktif(cfg)
    panjang = keliling_sengkang(300, 600, 10, 135, c2, elemen="balok",
                                bengkokan={90: 3, 135: 2})
    basis = keliling_sengkang(300, 600, 10, 135, cfg, elemen="balok",
                              bengkokan={90: 3, 135: 2})
    assert panjang < basis, "bend deduction harus MENGURANGI, bukan menambah"


# ── 4. sudut dipakai template tapi tidak ada di config ─────
def test_bend_deduction_sudut_tidak_ada_di_config(cfg):
    # config hanya punya 90° — template pakai 135° → ConfigError
    c2 = _cfg_aktif(cfg, faktor={90: 2})
    with pytest.raises(ConfigError, match="135"):
        bend_deduction(10, {90: 3, 135: 2}, c2)


# ── 5. hasil tidak wajar → error, bukan panjang negatif ─────
def test_bend_deduction_hasil_tidak_wajar(cfg):
    # faktor 100×d — deduction > 30% dari basis → ConfigError
    c2 = _cfg_aktif(cfg, faktor={45: 100, 90: 100, 135: 100, 180: 100})
    with pytest.raises(ConfigError, match="tidak wajar"):
        keliling_sengkang(300, 600, 10, 135, c2, elemen="balok",
                          bengkokan={90: 3, 135: 2})


# ── PATCH-06 §2 — proyek/gambar wajib di /api/hitung & export ─
@pytest.fixture(scope="module")
def client():
    from app import app
    app.config["TESTING"] = True
    return app.test_client()


def test_hitung_proyek_tanpa_gambar_ditolak(client):
    r = client.post("/api/hitung", json={
        "proyek": "PRJ-001", "elemen": [
            {"tipe": "B1", "bentang_bersih_mm": 6000, "jumlah": 1}]})
    assert r.status_code == 400
    d = r.get_json()
    assert d["ok"] is False
    assert "gambar" in d["error"].lower()
    assert "GS-01" in d["error"]          # daftar gambar tersedia


def test_hitung_gambar_tanpa_proyek_ditolak(client):
    r = client.post("/api/hitung", json={
        "gambar": "GS-01", "elemen": [
            {"tipe": "B1", "bentang_bersih_mm": 6000, "jumlah": 1}]})
    assert r.status_code == 400
    assert "proyek" in r.get_json()["error"].lower()


def test_export_proyek_tanpa_gambar_ditolak(client):
    r = client.post("/api/export", json={
        "proyek": "PRJ-001", "elemen": [
            {"tipe": "B1", "bentang_bersih_mm": 6000, "jumlah": 1}]})
    assert r.status_code == 400
    assert "gambar" in r.get_json()["error"].lower()


def test_hitung_keduanya_kosong_legacy(client):
    # keduanya kosong → path legacy tetap jalan (test lama & F3.5)
    r = client.post("/api/hitung", json={"elemen": [
        {"tipe": "B1", "bentang_bersih_mm": 6000, "jumlah": 1}]})
    assert r.status_code == 200, r.get_json()


# ── PATCH-06 §3-4 — lokasi & berat dari backend ────────────
def test_bbs_row_punya_lokasi_total_dan_berat(client):
    r = client.post("/api/hitung", json={
        "proyek": "PRJ-001", "gambar": "GS-01",
        "elemen": [{"tipe": "B1", "bentang_bersih_mm": 6000, "jumlah": 12,
                    "lokasi": "Lt.2"}]})
    assert r.status_code == 200, r.get_json()
    d = r.get_json()
    assert d["ok"] is True
    sk = [b for b in d["bbs"] if b["posisi"] == "sengkang"][0]
    # §3: lokasi dikirim backend
    assert sk["lokasi"] == "Lt.2"
    # §4: total_m & berat_kg dari backend — konsisten dengan hitung manual
    assert abs(sk["total_m"] - (1640 / 1000 * 408)) < 0.01
    assert abs(sk["berat_kg"] - (1640 / 1000 * 408 * 0.617)) < 0.01
    # total blok punya total_panjang_m
    assert abs(d["total"]["total_panjang_m"] -
               sum(b["total_m"] for b in d["bbs"])) < 0.01
    # optimizer per dia kirim berat_kg — konsisten dgn total panjang terpakai
    opt10 = d["optimizer"]["10"]
    assert abs(opt10["berat_kg"] -
               (opt10["total_panjang_terpakai_mm"] / 1000 * 0.617)) < 0.01
