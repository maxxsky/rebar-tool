"""Tests project setup (F3.6) — spec 08-SPEC-project-setup.md §10.

Wajib: CRUD, 409 duplikat, arsip, revisi-wajib, migrasi, _meta,
uji silang config web-made vs hand-written (hasil identik via CLI).
"""

import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "web"))

from config_loader import load_all, list_projects, load_project, migrate_legacy  # noqa: E402
from models import ConfigError  # noqa: E402

CONFIG_DIR = REPO / "config"


@pytest.fixture(scope="module")
def client():
    from app import app
    app.config["TESTING"] = True
    return app.test_client()


# ── payload valid minimal (diameter 10 & 19 lengkap utk template B1) ──
def payload_valid(kode="TEST01", revisi="Rev.1"):
    return {
        "kode": kode,
        "config": {
            "proyek": {"nama": "Proyek Test", "kode": kode},
            "sumber": {"dokumen": "GS-XX", "revisi": revisi,
                       "tanggal": "2026-08-01", "catatan": "tes"},
            "stok": {"panjang_batang_mm": 12000, "kerf_mm": 3,
                     "sisa_min_simpan_mm": 1000},
            "selimut_beton_mm": {"balok": 40, "kolom": 40, "plat": 20},
            "panjang_penyaluran_mm": {10: 400, 13: 520, 19: 760},
            "lap_splice_mm": {},
            "unit_weight_kg_per_m": {10: 0.617, 13: 1.042, 19: 2.226},
            "hook": {"tail_135_mm": {10: 80}, "tail_90_mm": {10: 120},
                     "diameter_bengkok_faktor": 4,
                     "koreksi_bengkokan_aktif": False},
            "sengkang": {"zona_tumpuan_faktor": 0.25,
                         "jarak_sengkang_pertama_mm": 50,
                         "metode_hitung": "kontinyu"},
            "optimizer": {"max_pola": 8, "batasi_pola": False},
        },
        "templates": {
            "balok": {
                "B1": {
                    "deskripsi": "tes", "b_mm": 300, "h_mm": 600,
                    "tulangan": [
                        {"posisi": "atas", "dia": 19, "jumlah": 4,
                         "tumpuan_kedua_ujung": True}],
                    "sengkang": {"dia": 10, "jarak_tumpuan_mm": 150,
                                 "jarak_lapangan_mm": 200, "kaki": 2,
                                 "hook_sudut": 135},
                }
            }
        },
    }


def cleanup(kode):
    for d in ("projects", "templates"):
        p = CONFIG_DIR / d / f"{kode}.yaml"
        if p.exists():
            p.unlink()
    arsip = CONFIG_DIR / "projects" / "_arsip"
    if arsip.exists():
        for p in arsip.glob(f"{kode}_*.yaml"):
            p.unlink()


# ── migrasi ────────────────────────────────────────────────
def test_migrasi_legacy_jalan_atau_sudah():
    assert (CONFIG_DIR / "projects").exists()


def test_migrasi_tidak_menimpa_saat_ada_proyek():
    # sudah ada proyek (dari migrasi / test lain) → migrate no-op
    if any((CONFIG_DIR / "projects").glob("*.yaml")):
        assert migrate_legacy(CONFIG_DIR) is False


# ── GET /api/projects ──────────────────────────────────────
def test_api_projects_list(client):
    d = client.get("/api/projects").get_json()
    assert d["ok"] is True
    assert isinstance(d["projects"], list)
    assert any("kode" in p for p in d["projects"])


# ── POST buat baru ─────────────────────────────────────────
def test_post_proyek_baru(client):
    cleanup("TEST01")
    r = client.post("/api/projects", json=payload_valid("TEST01"))
    assert r.status_code == 201, r.get_json()
    assert r.get_json()["kode"] == "TEST01"
    # file ada + _meta tertulis
    p = CONFIG_DIR / "projects" / "TEST01.yaml"
    assert p.exists()
    d = yaml.safe_load(p.read_text())
    assert d["_meta"]["dibuat_via"] == "web"
    assert "_meta" in yaml.safe_load(
        (CONFIG_DIR / "templates" / "TEST01.yaml").read_text())
    cleanup("TEST01")


def test_post_kode_duplikat_409(client):
    cleanup("DUP01")
    client.post("/api/projects", json=payload_valid("DUP01"))
    r = client.post("/api/projects", json=payload_valid("DUP01"))
    assert r.status_code == 409
    assert r.get_json()["duplicate"] is True
    cleanup("DUP01")


def test_post_invalid_diameter_400(client):
    cleanup("BAD01")
    p = payload_valid("BAD01")
    # hapus Ld utk dia 19 yang dipakai template → loader tolak
    del p["config"]["panjang_penyaluran_mm"][19]
    r = client.post("/api/projects", json=p)
    assert r.status_code == 400
    msg = r.get_json()["error"]
    assert "Diameter 19" in msg
    # tidak tersimpan
    assert not (CONFIG_DIR / "projects" / "BAD01.yaml").exists()
    cleanup("BAD01")


def test_post_kode_invalid(client):
    r = client.post("/api/projects", json=payload_valid("BAD KODE"))
    assert r.status_code == 400


# ── PUT edit + revisi wajib ────────────────────────────────
def test_put_nilai_berubah_revisi_sama_ditolak(client):
    cleanup("REV01")
    client.post("/api/projects", json=payload_valid("REV01", "Rev.1"))
    p = payload_valid("REV01", "Rev.1")  # revisi sama
    p["config"]["panjang_penyaluran_mm"][19] = 800  # nilai teknis berubah
    r = client.put("/api/projects/REV01", json=p)
    assert r.status_code == 400
    assert "revisi" in r.get_json()["error"].lower()
    cleanup("REV01")


def test_put_revisi_berubah_tersimpan_dan_diarsip(client):
    cleanup("REV02")
    client.post("/api/projects", json=payload_valid("REV02", "Rev.1"))
    p = payload_valid("REV02", "Rev.2")  # revisi beda
    p["config"]["panjang_penyaluran_mm"][19] = 800
    r = client.put("/api/projects/REV02", json=p)
    assert r.status_code == 200, r.get_json()
    # file lama diarsip
    arsip = CONFIG_DIR / "projects" / "_arsip"
    assert list(arsip.glob("REV02_*.yaml")), "file lama harus diarsipkan"
    # nilai baru tersimpan (key diameter string via JSON → normalize di loader)
    d = yaml.safe_load((CONFIG_DIR / "projects" / "REV02.yaml").read_text())
    ld = {int(k): v for k, v in d["panjang_penyaluran_mm"].items()}
    assert ld[19] == 800
    cleanup("REV02")


# ── GET yaml ───────────────────────────────────────────────
def test_get_yaml(client):
    cleanup("YML01")
    client.post("/api/projects", json=payload_valid("YML01"))
    r = client.get("/api/projects/YML01/yaml")
    assert r.status_code == 200
    assert b"proyek" in r.data
    cleanup("YML01")


# ── uji silang: config web-made dipakai CLI ────────────────
def test_uji_silang_config_web_vs_tulis_tangan(client, tmp_path):
    from bbs import agregasi, generate_bbs
    from models import ElemenInput
    from optimizer import optimize_all

    # 1. buat via web
    cleanup("SIL01")
    r = client.post("/api/projects", json=payload_valid("SIL01"))
    assert r.status_code == 201
    cfg_web, tpl_web = load_project(CONFIG_DIR, "SIL01")

    # 2. tulis tangan nilai yang sama persis (tanpa _meta)
    p = payload_valid("SIL01")
    td = tmp_path / "config"
    td.mkdir()
    (td / "project.yaml").write_text(yaml.safe_dump(p["config"]))
    (td / "templates.yaml").write_text(yaml.safe_dump(p["templates"]))
    cfg_manual, tpl_manual = load_all(td)

    # 3. hitung kedua-duanya
    elemen = [ElemenInput(tipe="B1", bentang_bersih_mm=6000, jumlah=1,
                          lokasi="x")]
    cuts_w = generate_bbs(tpl_web, elemen, cfg_web)
    cuts_m = generate_bbs(tpl_manual, elemen, cfg_manual)
    agg_w = agregasi(cuts_w)
    agg_m = agregasi(cuts_m)
    res_w = optimize_all(agg_w, cfg_web)
    res_m = optimize_all(agg_m, cfg_manual)

    key_w = {(c.dia, c.panjang_mm): c.jumlah for c in agg_w}
    key_m = {(c.dia, c.panjang_mm): c.jumlah for c in agg_m}
    assert key_w == key_m, "BBS web-made != hand-written"
    for dia in res_w:
        assert res_w[dia].total_batang == res_m[dia].total_batang
        assert res_w[dia].total_panjang_terpakai_mm == \
            res_m[dia].total_panjang_terpakai_mm
    cleanup("SIL01")


# ── /api/hitung dengan kode ────────────────────────────────
def test_api_hitung_dengan_kode(client):
    cleanup("HIT01")
    client.post("/api/projects", json=payload_valid("HIT01"))
    r = client.post("/api/hitung", json={
        "kode": "HIT01",
        "elemen": [{"tipe": "B1", "bentang_bersih_mm": 6000, "jumlah": 1}],
    })
    d = r.get_json()
    assert d["ok"] is True, d
    assert len(d["bbs"]) >= 1
    cleanup("HIT01")
