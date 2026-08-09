"""Tests 10-SPEC Shape Library — parser ekspresi + panjang_potong universal.

Golden (harus identik sebelum refactor):
- sengkang B1 → 1640 mm (koreksi OFF)
- tul. atas D19 → 7520 mm
"""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import dataclasses
from bbs import generate_bbs, panjang_potong
from config_loader import load_all
from models import ConfigError, ElemenInput
from shapes import (DEFAULT_SHAPES_YAML, evaluasi_ekspresi, load_shapes,
                    load_shapes_from_text, parse_ekspresi, shapes_bawaan,
                    tulis_shapes_bawaan)

CONFIG_DIR = REPO / "config"


@pytest.fixture(scope="module")
def cfg():
    c, _ = load_all(CONFIG_DIR)
    return c


@pytest.fixture(scope="module")
def templates():
    _, t = load_all(CONFIG_DIR)
    return t


# ── golden — perilaku tidak berubah ─────────────────────────
def test_golden_sengkang_1640(cfg, templates):
    elemen = [ElemenInput(tipe="B1", bentang_bersih_mm=6000, jumlah=1)]
    cuts = generate_bbs(templates, elemen, cfg)
    sk = [c for c in cuts if c.posisi == "sengkang"][0]
    assert sk.panjang_mm == 1640
    assert sk.shape_code == "51"
    assert sk.segmen_mm == (220, 520, 220, 520)


def test_golden_tulangan_utama_7520(cfg, templates):
    elemen = [ElemenInput(tipe="B1", bentang_bersih_mm=6000, jumlah=1)]
    cuts = generate_bbs(templates, elemen, cfg)
    atas = [c for c in cuts if c.posisi == "atas"][0]
    assert atas.panjang_mm == 7520
    assert atas.shape_code == "01"


# ── parser ekspresi — whitelist ─────────────────────────────
def test_parser_ekspresi_ok():
    assert evaluasi_ekspresi("b - 2*c", {"b": 300, "c": 40}, "x") == 220
    assert evaluasi_ekspresi("L + 2*Ld", {"L": 6000, "Ld": 760}, "x") == 7520
    assert evaluasi_ekspresi("(b - 2*c) / 2", {"b": 300, "c": 40}, "x") == 110


def test_parser_variabel_asing_ditolak():
    with pytest.raises(ConfigError, match="xyz"):
        parse_ekspresi("L + xyz", "shape.21")


def test_parser_syntax_error_ditolak():
    with pytest.raises(ConfigError, match="parse"):
        parse_ekspresi("L +* 2", "shape.21")


def test_parser_no_eval():
    # kalau pakai eval(), ekspresi ini jalan — parser harus tolak
    with pytest.raises(ConfigError):
        parse_ekspresi("__import__('os').system('x')", "shape.21")


# ── shapes.yaml bawaan & migrasi ────────────────────────────
def test_shapes_bawaan_ada_01_dan_51():
    sh = shapes_bawaan()
    assert set(sh) >= {"01", "51"}
    assert len(sh["01"].segmen) == 1
    assert sh["01"].segmen[0].panjang == "L"
    assert len(sh["51"].segmen) == 4
    assert sh["51"].segmen[0].panjang == "b - 2*c"
    # 51: 3×90 + 2×hook bengkokan, 2×hook hook
    assert sum(b.jumlah for b in sh["51"].bengkokan) == 5
    assert sum(h.jumlah for h in sh["51"].hook) == 2


def test_migrasi_tulis_bawaan(tmp_path):
    p = tmp_path / "shapes.yaml"
    tulis_shapes_bawaan(p)
    assert p.exists()
    sh = load_shapes(p)
    assert "01" in sh and "51" in sh


# ── panjang_potong — shape 21 bengkok satu ujung ────────────
def test_shape_21_bengkok_satu_ujung(cfg):
    from models import ShapeBengkokan, ShapeDef, ShapeHook, ShapeSegmen
    shape21 = ShapeDef(
        kode="21", nama="Bengkok satu ujung", deskripsi="",
        segmen=(ShapeSegmen("A", "L"), ShapeSegmen("B", "tekuk")),
        bengkokan=(ShapeBengkokan(90, 1),),
        hook=())
    panjang, segmen = panjang_potong(
        shape21, {"L": "L", "tekuk": 200, "b_mm": 300, "h_mm": 600},
        19, None, cfg, elemen="balok", bentang=6000)
    # L=6000 + tekuk 200 = 6200 (koreksi off → bend 0)
    assert panjang == 6200
    assert segmen == (6000, 200)


# ── panjang_potong — hook 'hook' mengikuti hook_sudut ───────
def test_shape_hook_ikut_template(cfg):
    from models import ShapeBengkokan, ShapeDef, ShapeHook, ShapeSegmen
    sh = ShapeDef(
        kode="99", nama="Test hook", deskripsi="",
        segmen=(ShapeSegmen("A", "L"),),
        bengkokan=(),
        hook=(ShapeHook("hook", 2),))
    panjang, _ = panjang_potong(sh, {"b_mm": 300, "h_mm": 600}, 10, 135, cfg,
                                elemen="balok", bentang=1000)
    # 1000 + 2×80 (tail 135 D10) = 1160
    assert panjang == 1160


# ── shape dipakai template tapi tidak ada → ConfigError ─────
def test_shape_hilang_ditolak(cfg, tmp_path):
    # template yang pakai shape '99' (tidak ada di shapes bawaan) → ConfigError
    from config_loader import validate_config_templates
    import types
    tpl = types.SimpleNamespace(
        nama="B9", tipe="balok", b_mm=300, h_mm=600,
        tulangan=(types.SimpleNamespace(shape="99", dia=19),),
        sengkang=(types.SimpleNamespace(shape="51", dia=10, hook_sudut=135,
                                        jarak_tumpuan_mm=150,
                                        jarak_lapangan_mm=200),))
    errors = []
    validate_config_templates(cfg, {"B9": tpl}, errors)
    assert any("99" in e for e in errors), errors
