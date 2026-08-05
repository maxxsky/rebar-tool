"""Tests web UI (F3.5) — spec 07-SPEC-webui.md §9.

Uji silang utama: input sama di web & CLI → angka identik.
"""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "web"))

from bbs import agregasi, generate_bbs
from config_loader import load_all
from models import ElemenInput
from optimizer import optimize_all

CONFIG_DIR = REPO / "config"


@pytest.fixture(scope="module")
def client():
    from app import app
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture(scope="module")
def elemen_payload():
    return {"elemen": [
        {"tipe": "B1", "bentang_bersih_mm": 6000, "jumlah": 12, "lokasi": "Lt.2"},
        {"tipe": "B1", "bentang_bersih_mm": 5400, "jumlah": 8, "lokasi": "Lt.2"},
        {"tipe": "B2", "bentang_bersih_mm": 4000, "jumlah": 20, "lokasi": "Lt.2"},
    ]}


def _hasil_cli(elemen, override=None):
    """Hitung langsung via modul — ini pembanding CLI (uji silang)."""
    cfg, templates = load_all(CONFIG_DIR)
    if override:
        from app import _apply_override
        cfg = _apply_override(cfg, override)
    elemen_obj = [ElemenInput(tipe=e["tipe"], bentang_bersih_mm=int(e["bentang_bersih_mm"]),
                              jumlah=int(e["jumlah"]), lokasi=e.get("lokasi", ""))
                  for e in elemen]
    cuts = generate_bbs(templates, elemen_obj, cfg)
    agg = agregasi(cuts)
    hasil = optimize_all(agg, cfg)
    return agg, hasil


# ── GET /api/config ────────────────────────────────────────
def test_api_config(client):
    d = client.get("/api/config").get_json()
    assert d["ok"] is True
    assert "config" in d and "templates" in d
    assert "B1" in d["templates"] and "B2" in d["templates"]
    assert d["config"]["stok_mm"] == 12000


# ── uji silang utama: web == CLI ───────────────────────────
def test_uji_silang_web_vs_cli(client, elemen_payload):
    r = client.post("/api/hitung", json=elemen_payload)
    assert r.status_code == 200, r.get_json()
    web = r.get_json()

    agg, hasil = _hasil_cli(elemen_payload["elemen"])

    # BBS identik
    web_bbs = {(b["dia"], b["panjang_mm"]): b["jumlah"] for b in web["bbs"]}
    cli_bbs = {(c.dia, c.panjang_mm): c.jumlah for c in agg}
    assert web_bbs == cli_bbs, "BBS web != CLI"

    # optimizer identik
    for dia, res in hasil.items():
        wr = web["optimizer"][str(dia)]
        assert wr["total_batang"] == res.total_batang
        assert wr["total_panjang_terpakai_mm"] == res.total_panjang_terpakai_mm
        assert wr["total_sisa_mm"] == res.total_sisa_mm
        assert abs(wr["waste_pct"] - res.waste_pct) < 1e-9
        web_pola = {(tuple(p["potongan"]), p["frekuensi"]) for p in wr["patterns"]}
        cli_pola = {(p.potongan, p.frekuensi) for p in res.patterns}
        assert web_pola == cli_pola, f"D{dia} pola web != CLI"


# ── override ───────────────────────────────────────────────
def test_override_metode_hitung_mengubah_sengkang(client, elemen_payload):
    base = client.post("/api/hitung", json=elemen_payload).get_json()
    per_zona = client.post("/api/hitung", json={
        **elemen_payload, "override": {"metode_hitung": "per_zona"}}).get_json()
    # jumlah D10 1640 beda antara kontinyu & per_zona
    def jumlah_d10(d):
        return sum(b["jumlah"] for b in d["bbs"] if b["dia"] == 10)
    assert jumlah_d10(base) != jumlah_d10(per_zona)
    assert per_zona["config"]["metode_hitung"] == "per_zona"
    assert "metode_hitung" in per_zona["override_aktif"]


def test_override_zona_tumpuan(client, elemen_payload):
    d = client.post("/api/hitung", json={
        **elemen_payload, "override": {"zona_tumpuan_faktor": 0.3}}).get_json()
    assert d["ok"]
    assert d["config"]["zona_tumpuan_faktor"] == 0.3


def test_override_tidak_menulis_file(client, elemen_payload):
    import hashlib
    p = CONFIG_DIR / "project.yaml"
    before = hashlib.sha256(p.read_bytes()).hexdigest()
    client.post("/api/hitung", json={
        **elemen_payload,
        "override": {"kerf_mm": 5, "sisa_min_simpan_mm": 800,
                     "metode_hitung": "per_zona"}})
    after = hashlib.sha256(p.read_bytes()).hexdigest()
    assert before == after, "override tidak boleh menulis file config"


def test_override_invalid(client, elemen_payload):
    # key asing ditolak (PATCH-02: key dikenal diverifikasi fail-loud)
    d = client.post("/api/hitung", json={
        **elemen_payload, "override": {"foo_bar": 1}}).get_json()
    assert d["ok"] is False
    assert "foo_bar" in d["error"]
    assert "tidak dikenal" in d["error"]


def test_override_luas_ld(client, elemen_payload):
    # override luas (PATCH-02 §1.3): ubah Ld D19 → panjang tulangan berubah.
    # ld di-replace TOTAL — frontend kirim semua diameter (form edit lengkap).
    d = client.post("/api/hitung", json={
        **elemen_payload,
        "override": {"ld": {"10": 400, "13": 520, "16": 640, "19": 1000}},
    }).get_json()
    assert d["ok"] is True, d
    # B1 D19: 6000 + 2×1000 = 8000 (sebelumnya 7520)
    panjang19 = [b["panjang_mm"] for b in d["bbs"] if b["dia"] == 19]
    assert 8000 in panjang19


# ── error baris ────────────────────────────────────────────
def test_error_menyebut_nomor_baris(client):
    d = client.post("/api/hitung", json={"elemen": [
        {"tipe": "B1", "bentang_bersih_mm": 6000, "jumlah": 1},
        {"tipe": "B9", "bentang_bersih_mm": 4000, "jumlah": 1},
    ]}).get_json()
    assert d["ok"] is False
    assert "B9" in d["error"]
    assert "B1, B2" in d["error"]


def test_error_bentang_negatif_menyebut_baris(client):
    d = client.post("/api/hitung", json={"elemen": [
        {"tipe": "B1", "bentang_bersih_mm": -5, "jumlah": 1},
    ]}).get_json()
    assert d["ok"] is False
    assert "Baris 1" in d["error"]


# ── export ─────────────────────────────────────────────────
def test_export_excel(client, elemen_payload, tmp_path):
    r = client.post("/api/export", json=elemen_payload)
    assert r.status_code == 200
    assert r.data[:2] == b"PK"  # zip/xlsx magic
    # file tersimpan di output/
    import glob
    files = sorted(glob.glob(str(REPO / "output" / "BBS_*.xlsx")))
    assert files, "file export harus tersimpan"


# ── config file tidak diubah oleh export ───────────────────
def test_export_tidak_menimpa(client, elemen_payload):
    import glob
    files1 = sorted(glob.glob(str(REPO / "output" / "BBS_*.xlsx")))
    client.post("/api/export", json=elemen_payload)
    files2 = sorted(glob.glob(str(REPO / "output" / "BBS_*.xlsx")))
    assert len(files2) >= len(files1)
