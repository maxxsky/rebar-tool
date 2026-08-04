"""Tests config loader (F0) — spec 01-SPEC-config.md §7.

Wajib:
- config lengkap → lolos
- diameter hilang di ld → error menyebut lokasi template
- cover × 2 >= h_mm → error
- warning masuk config.warnings tapi tidak menghentikan
"""

import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from config_loader import (load_all, load_project_config, load_templates,
                           validate_config_templates)
from models import ConfigError, ProjectConfig

CONFIG_DIR = REPO / "config"


@pytest.fixture
def contoh_config():
    return load_project_config(CONFIG_DIR / "project.yaml")


@pytest.fixture
def contoh_template():
    return load_templates(CONFIG_DIR / "templates.yaml")


def _tulis(tmp_path, data, nama="project.yaml"):
    p = tmp_path / nama
    p.write_text(yaml.safe_dump(data))
    return p


# ── config lengkap → lolos ──────────────────────────────────
def test_config_lengkap_lolos():
    cfg, templates = load_all(CONFIG_DIR)
    assert isinstance(cfg, ProjectConfig)
    assert cfg.nama == "Nama Proyek"
    assert cfg.stok.panjang_batang_mm == 12000
    assert cfg.ld[19] == 760
    assert cfg.hook_tail[135][10] == 80
    assert len(templates) == 2
    assert "B1" in templates and "B2" in templates


# ── diameter hilang di ld → error dengan lokasi template ────
def test_diameter_hilang_di_ld():
    data = yaml.safe_load(open(CONFIG_DIR / "project.yaml"))
    del data["panjang_penyaluran_mm"][19]  # dipakai balok.B1 tulangan dia 19
    tmp = _tulis_config_dir(data)
    with pytest.raises(ConfigError) as exc:
        load_all(tmp)
    msg = str(exc.value)
    assert "Diameter 19 dipakai di" in msg
    assert "balok.B1" in msg or "B1" in msg
    assert "panjang_penyaluran_mm" in msg


def test_diameter_hilang_di_hook_sengkang():
    data = yaml.safe_load(open(CONFIG_DIR / "project.yaml"))
    del data["hook"]["tail_135_mm"][10]  # B1 & B2 sengkang dia 10 hook 135
    tmp = _tulis_config_dir(data)
    with pytest.raises(ConfigError) as exc:
        load_all(tmp)
    msg = str(exc.value)
    assert "hook_sudut 135" in msg
    assert "tail_135_mm" in msg


# ── semua error dikumpulkan sekaligus ───────────────────────
def test_error_dikumpulkan_sekaligus():
    data = yaml.safe_load(open(CONFIG_DIR / "project.yaml"))
    del data["panjang_penyaluran_mm"][19]
    del data["unit_weight_kg_per_m"][16]   # dua error sekaligus
    tmp = _tulis_config_dir(data)
    with pytest.raises(ConfigError) as exc:
        load_all(tmp)
    msg = str(exc.value)
    assert "Diameter 19" in msg
    assert "Diameter 16" in msg


# ── cover × 2 >= h_mm → error ───────────────────────────────
def test_cover_2x_melebihi_dimensi():
    data = yaml.safe_load(open(CONFIG_DIR / "templates.yaml"))
    data["balok"]["B2"]["h_mm"] = 60  # cover balok 40 → 2×40=80 >= 60
    tmp = _tulis_path(data, "templates.yaml")
    with pytest.raises(ConfigError) as exc:
        cfg = load_project_config(CONFIG_DIR / "project.yaml")
        templates = load_templates(tmp)
        errors = []
        validate_config_templates(cfg, templates, errors)
        if errors:
            raise ConfigError("\n".join(errors))
    assert "selimut_beton×2" in str(exc.value)


def test_cover_2x_melebihi_b_mm():
    data = yaml.safe_load(open(CONFIG_DIR / "templates.yaml"))
    data["balok"]["B1"]["b_mm"] = 70  # 2×40=80 >= 70
    tmp = _tulis_path(data, "templates.yaml")
    with pytest.raises(ConfigError):
        cfg = load_project_config(CONFIG_DIR / "project.yaml")
        templates = load_templates(tmp)
        errors = []
        validate_config_templates(cfg, templates, errors)
        if errors:
            raise ConfigError("\n".join(errors))


# ── warning tidak menghentikan, masuk cfg.warnings ──────────
def test_warning_masuk_warnings():
    data = yaml.safe_load(open(CONFIG_DIR / "project.yaml"))
    data["stok"]["kerf_mm"] = 25  # > 20 → WARNING
    tmp = _tulis_path(data)
    cfg = load_project_config(tmp)
    assert any("kerf" in w.lower() for w in cfg.warnings)


def test_jarak_tumpuan_lebih_besar_dari_lapangan_warning():
    data = yaml.safe_load(open(CONFIG_DIR / "templates.yaml"))
    data["balok"]["B1"]["sengkang"]["jarak_tumpuan_mm"] = 250  # > lapangan 200
    tmp = _tulis_path(data, "templates.yaml")
    cfg = load_project_config(CONFIG_DIR / "project.yaml")
    templates = load_templates(tmp)
    errors = []
    validate_config_templates(cfg, templates, errors)
    assert not errors
    assert any("jarak_tumpuan" in w for w in cfg.warnings)


# ── sanity check negatif / nol ──────────────────────────────
def test_dimensi_negatif_error():
    data = yaml.safe_load(open(CONFIG_DIR / "project.yaml"))
    data["stok"]["panjang_batang_mm"] = -500
    tmp = _tulis_path(data)
    with pytest.raises(ConfigError):
        load_project_config(tmp)


# ── zona_tumpuan_faktor di luar 0-0.5 → error ───────────────
def test_zona_tumpuan_faktor_error():
    data = yaml.safe_load(open(CONFIG_DIR / "project.yaml"))
    data["sengkang"]["zona_tumpuan_faktor"] = 0.8
    tmp = _tulis_path(data)
    with pytest.raises(ConfigError):
        load_project_config(tmp)


# ── normalisasi key diameter (int vs str) ───────────────────
def test_diameter_str_dinormalisasi():
    data = yaml.safe_load(open(CONFIG_DIR / "project.yaml"))
    data["panjang_penyaluran_mm"] = {"10": 400, "13": 520}
    tmp = _tulis_path(data)
    cfg = load_project_config(tmp)
    assert 10 in cfg.ld and 13 in cfg.ld
    assert isinstance(list(cfg.ld.keys())[0], int)


def _tulis_path(data, nama="project.yaml"):
    """Tulis data ke file sementara, return PATH FILE."""
    import tempfile
    d = Path(tempfile.mkdtemp())
    p = d / nama
    p.write_text(yaml.safe_dump(data))
    return p


def _tulis_config_dir(data):
    """Tulis project.yaml termodifikasi ke folder yg JADI juga templates.yaml
    (untuk test yang butuh load_all(config_dir))."""
    import shutil
    import tempfile
    d = Path(tempfile.mkdtemp())
    shutil.copy(CONFIG_DIR / "templates.yaml", d / "templates.yaml")
    (d / "project.yaml").write_text(yaml.safe_dump(data))
    return d
