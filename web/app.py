"""Web UI — alat verifikasi F4 (F3.5). Spec 07-SPEC-webui.md.

Aturan:
- NOL logika perhitungan di web — semua dari bbs/optimizer/config_loader.
- Override in-memory via dataclasses.replace; TIDAK menulis file config.
- Traceability: parameter efektif tampil di layar yang sama dgn hasil.
- Error tampil apa adanya; InfeasiblePatternError menonjol.
"""

import dataclasses
import sys
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bbs import agregasi, generate_bbs          # noqa: E402
from config_loader import (load_all, load_project, list_projects,      # noqa: E402
                           migrate_legacy)
from export import generate_excel               # noqa: E402
from models import (ConfigError, Cut, ElemenInput, InfeasiblePatternError,
                    LengthExceedsStockError, TOOL_VERSION)   # noqa: E402
from optimizer import optimize_all              # noqa: E402

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

CONFIG_DIR = ROOT / "config"

# migrasi config lama → projects/ sekali (F3.6 §7)
migrate_legacy(CONFIG_DIR)


# ── helpers ────────────────────────────────────────────────
def _baca_elemen_json(rows) -> list[ElemenInput]:
    """Parse input elemen dari JSON — error menyebut nomor baris."""
    errors = []
    elemen = []
    for idx, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            errors.append(f"Baris {idx}: format baris tidak valid")
            continue
        tipe = str(row.get("tipe", "")).strip()
        bentang_raw = row.get("bentang_bersih_mm")
        jumlah_raw = row.get("jumlah")
        lokasi = str(row.get("lokasi", "")).strip()
        if not tipe:
            errors.append(f"Baris {idx}: tipe kosong")
            continue
        try:
            bentang = int(bentang_raw)
        except (TypeError, ValueError):
            errors.append(f"Baris {idx}: bentang_bersih_mm tidak valid: "
                          f"{bentang_raw!r}")
            continue
        if bentang <= 0:
            errors.append(f"Baris {idx}: bentang_bersih_mm harus positif: "
                          f"{bentang}")
            continue
        try:
            jumlah = int(jumlah_raw)
        except (TypeError, ValueError):
            errors.append(f"Baris {idx}: jumlah tidak valid: {jumlah_raw!r}")
            continue
        if jumlah <= 0:
            errors.append(f"Baris {idx}: jumlah harus positif: {jumlah}")
            continue
        elemen.append(ElemenInput(tipe=tipe, bentang_bersih_mm=bentang,
                                  jumlah=jumlah, lokasi=lokasi))
    return elemen, errors


ALLOWED_OVERRIDES = ("metode_hitung", "zona_tumpuan_faktor", "kerf_mm",
                     "sisa_min_simpan_mm")


def _apply_override(cfg, override: dict):
    """Override 4 field — dataclasses.replace, tidak menyentuh file."""
    if not override:
        return cfg
    for k in override:
        if k not in ALLOWED_OVERRIDES:
            raise ConfigError(
                f"Override '{k}' tidak didukung. Hanya: "
                f"{', '.join(ALLOWED_OVERRIDES)}")

    sk = cfg.sengkang_cfg
    stok = cfg.stok
    if "metode_hitung" in override:
        m = override["metode_hitung"]
        if m not in ("kontinyu", "per_zona"):
            raise ConfigError(
                f"metode_hitung harus 'kontinyu' atau 'per_zona', dapat {m!r}")
        sk = dataclasses.replace(sk, metode_hitung=m)
    if "zona_tumpuan_faktor" in override:
        f = float(override["zona_tumpuan_faktor"])
        if not (0.0 <= f <= 0.5):
            raise ConfigError(
                f"zona_tumpuan_faktor = {f} harus 0-0.5")
        sk = dataclasses.replace(sk, zona_tumpuan_faktor=f)
    if "kerf_mm" in override:
        stok = dataclasses.replace(stok, kerf_mm=int(override["kerf_mm"]))
    if "sisa_min_simpan_mm" in override:
        stok = dataclasses.replace(stok,
                                   sisa_min_simpan_mm=int(override["sisa_min_simpan_mm"]))
    return dataclasses.replace(cfg, sengkang_cfg=sk, stok=stok)


def _templates_dict(templates):
    out = {}
    for nama, t in templates.items():
        out[nama] = {
            "tipe": t.tipe,
            "deskripsi": t.deskripsi,
            "b_mm": t.b_mm,
            "h_mm": t.h_mm,
            "tulangan": [{"posisi": x.posisi, "dia": x.dia,
                          "jumlah": x.jumlah,
                          "tumpuan_kedua_ujung": x.tumpuan_kedua_ujung}
                         for x in t.tulangan],
            "sengkang": {"dia": t.sengkang.dia,
                         "jarak_tumpuan_mm": t.sengkang.jarak_tumpuan_mm,
                         "jarak_lapangan_mm": t.sengkang.jarak_lapangan_mm,
                         "kaki": t.sengkang.kaki,
                         "hook_sudut": t.sengkang.hook_sudut},
        }
    return out


def _config_dict(cfg):
    return {
        "nama": cfg.nama,
        "kode": cfg.kode,
        "sumber": f"{cfg.sumber.dokumen} {cfg.sumber.revisi} "
                  f"({cfg.sumber.tanggal})",
        "stok_mm": cfg.stok.panjang_batang_mm,
        "kerf_mm": cfg.stok.kerf_mm,
        "sisa_min_simpan_mm": cfg.stok.sisa_min_simpan_mm,
        "cover": cfg.cover,
        "ld": {str(k): v for k, v in sorted(cfg.ld.items())},
        "hook_tail": {str(s): {str(d): v for d, v in sorted(m.items())}
                      for s, m in sorted(cfg.hook_tail.items())},
        "metode_hitung": cfg.sengkang_cfg.metode_hitung,
        "zona_tumpuan_faktor": cfg.sengkang_cfg.zona_tumpuan_faktor,
        "jarak_sengkang_pertama_mm": cfg.sengkang_cfg.jarak_sengkang_pertama_mm,
        "koreksi_bend_aktif": cfg.koreksi_bend_aktif,
        "unit_weight": {str(k): v for k, v in sorted(cfg.unit_weight.items())},
        "warnings": list(cfg.warnings),
    }


def _opt_dict(res):
    return {
        "dia": res.dia,
        "patterns": [{"potongan": list(p.potongan), "frekuensi": p.frekuensi,
                      "sisa_mm": p.sisa_mm, "reusable": p.reusable}
                     for p in res.patterns],
        "total_batang": res.total_batang,
        "total_panjang_terpakai_mm": res.total_panjang_terpakai_mm,
        "total_kerf_mm": res.total_kerf_mm,
        "total_sisa_mm": res.total_sisa_mm,
        "sisa_reusable_mm": res.sisa_reusable_mm,
        "waste_pct": res.waste_pct,
        "waste_kotor_pct": res.waste_kotor_pct,
        "pola_sebelum_batasi": res.pola_sebelum_batasi,
        "pola_sesudah_batasi": res.pola_sesudah_batasi,
    }


def _bbs_dict(c):
    return {"bar_mark": c.bar_mark, "lokasi": c.lokasi, "tipe": c.tipe_elemen,
            "posisi": c.posisi, "shape": c.shape_code, "dia": c.dia,
            "panjang_mm": c.panjang_mm, "jumlah": c.jumlah,
            "segmen_mm": list(c.segmen_mm)}


def _hitung(cfg, templates, elemen):
    """Inti perhitungan — modul yang SAMA dengan CLI."""
    # validasi tipe
    for el in elemen:
        if el.tipe not in templates:
            raise ConfigError(
                f"Tipe '{el.tipe}' tidak ada di templates.yaml. "
                f"Tersedia: {', '.join(sorted(templates))}")
    cuts = generate_bbs(templates, elemen, cfg)
    agg = agregasi(cuts)
    hasil_opt = optimize_all(agg, cfg)
    return cuts, agg, hasil_opt


# ── routes ─────────────────────────────────────────────────
@app.get("/")
def index():
    return render_template("index.html")


# ── PROJECT SETUP (F3.6) ───────────────────────────────────
def _meta_yaml():
    from datetime import datetime
    ts = datetime.now().astimezone().replace(microsecond=0).isoformat()
    return (f"_meta:\n  dibuat_via: web\n  dibuat_pada: {ts}\n"
            f"  tool_version: {TOOL_VERSION}\n")


def _valid_kode(kode):
    return bool(kode) and all(c.isalnum() or c in "_-" for c in kode)


def _simpan_proyek_baru(payload, arsip_lama=False):
    """Validasi via loader (tempfile) lalu tulis final. Returns (kode, msg)."""
    import tempfile
    import yaml
    kode = str(payload.get("kode", "")).strip()
    if not _valid_kode(kode):
        raise ConfigError(
            f"Kode '{kode}' tidak valid. Gunakan hanya A-Z, a-z, 0-9, _ atau -.")
    proj_path = CONFIG_DIR / "projects" / f"{kode}.yaml"
    tpl_path = CONFIG_DIR / "templates" / f"{kode}.yaml"

    if proj_path.exists():
        if not arsip_lama:
            raise ConfigDuplicate(kode)
        # arsipkan file lama
        arsip = CONFIG_DIR / "projects" / "_arsip"
        arsip.mkdir(exist_ok=True)
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        if proj_path.exists():
            proj_path.rename(arsip / f"{kode}_{ts}.yaml")
        if tpl_path.exists():
            tpl_arsip = CONFIG_DIR / "templates" / "_arsip"
            tpl_arsip.mkdir(exist_ok=True)
            tpl_path.rename(tpl_arsip / f"{kode}_{ts}.yaml")

    # validasi via tempfile → loader (satu sumber kebenaran)
    config_yaml = yaml.safe_dump(payload["config"], allow_unicode=True)
    templates_yaml = yaml.safe_dump(payload["templates"], allow_unicode=True)
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / "project.yaml").write_text(config_yaml)
        (td / "templates.yaml").write_text(templates_yaml)
        cfg, tpls = load_all(td)  # ConfigError → ditangkap caller

    (CONFIG_DIR / "projects").mkdir(exist_ok=True)
    (CONFIG_DIR / "templates").mkdir(exist_ok=True)
    proj_path.write_text(_meta_yaml() + config_yaml)
    tpl_path.write_text(_meta_yaml() + templates_yaml)
    return kode


class ConfigDuplicate(Exception):
    def __init__(self, kode):
        super().__init__(f"Proyek '{kode}' sudah ada.")
        self.kode = kode


def _signature_teknis(payload):
    """Nilai teknis dari gambar — dipakai deteksi 'revisi wajib berubah'."""
    cfg = payload["config"]
    return {
        "cover": cfg.get("selimut_beton_mm", {}),
        "ld": cfg.get("panjang_penyaluran_mm", {}),
        "lap": cfg.get("lap_splice_mm", {}),
        "hook": cfg.get("hook", {}),
        "sengkang": cfg.get("sengkang", {}),
        "templates": payload["templates"],
    }


def _signature_teknis_dari_file(kode):
    """Signature dari file existing — load + dump ulang ke bentuk compare."""
    import yaml
    p = CONFIG_DIR / "projects" / f"{kode}.yaml"
    t = CONFIG_DIR / "templates" / f"{kode}.yaml"
    if not p.exists() or not t.exists():
        return None
    cfg_d = yaml.safe_load(p.read_text())
    tpl_d = yaml.safe_load(t.read_text())
    cfg_d.pop("_meta", None)
    tpl_d.pop("_meta", None)
    return {"cover": cfg_d.get("selimut_beton_mm", {}),
            "ld": cfg_d.get("panjang_penyaluran_mm", {}),
            "lap": cfg_d.get("lap_splice_mm", {}),
            "hook": cfg_d.get("hook", {}),
            "sengkang": cfg_d.get("sengkang", {}),
            "templates": tpl_d}


@app.get("/api/projects")
def api_projects():
    return jsonify({"ok": True, "projects": list_projects(CONFIG_DIR)})


@app.get("/api/projects/<kode>")
def api_project_get(kode):
    p = CONFIG_DIR / "projects" / f"{kode}.yaml"
    t = CONFIG_DIR / "templates" / f"{kode}.yaml"
    if not p.exists() or not t.exists():
        return jsonify({"ok": False, "error": f"Proyek '{kode}' tidak ada."}), 404
    import yaml
    cfg_d = yaml.safe_load(p.read_text())
    tpl_d = yaml.safe_load(t.read_text())
    cfg_d.pop("_meta", None)
    tpl_d.pop("_meta", None)
    return jsonify({"ok": True, "kode": kode,
                    "config": cfg_d, "templates": tpl_d})


@app.post("/api/projects")
def api_project_create():
    data = request.get_json(force=True) or {}
    try:
        kode = _simpan_proyek_baru(data)
    except ConfigDuplicate as e:
        return jsonify({"ok": False, "error": str(e),
                        "duplicate": True, "kode": e.kode}), 409
    except ConfigError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True, "kode": kode}), 201


@app.put("/api/projects/<kode>")
def api_project_update(kode):
    data = request.get_json(force=True) or {}
    new_kode = str(data.get("kode", kode))
    # edit: kode harus sama dengan path
    if new_kode != kode:
        return jsonify({"ok": False,
                        "error": "Kode tidak bisa diubah lewat edit."}), 400
    old_sig = _signature_teknis_dari_file(kode)
    if old_sig is None:
        return jsonify({"ok": False, "error": f"Proyek '{kode}' tidak ada."}), 404
    new_sig = _signature_teknis(data)
    if new_sig != old_sig:
        # nilai teknis berubah → revisi wajib berbeda
        old_rev = _revisi_dari_file(kode)
        new_rev = str(data["config"].get("sumber", {}).get("revisi", "")).strip()
        if old_rev and new_rev == old_rev:
            return jsonify({"ok": False,
                            "error": "Nilai teknis berubah tapi revisi gambar masih "
                                     "sama. Kalau ini koreksi salah ketik, ubah "
                                     "catatan sumber. Kalau gambar memang direvisi, "
                                     "perbarui field revisi."}), 400
    try:
        _simpan_proyek_baru(data, arsip_lama=True)
    except ConfigError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True, "kode": kode})


def _revisi_dari_file(kode):
    import yaml
    p = CONFIG_DIR / "projects" / f"{kode}.yaml"
    if not p.exists():
        return ""
    d = yaml.safe_load(p.read_text())
    return str((d.get("sumber") or {}).get("revisi", "")).strip()


@app.get("/api/projects/<kode>/yaml")
def api_project_yaml(kode):
    p = CONFIG_DIR / "projects" / f"{kode}.yaml"
    if not p.exists():
        return jsonify({"ok": False, "error": f"Proyek '{kode}' tidak ada."}), 404
    return send_file(p, as_attachment=True, download_name=f"{kode}.yaml",
                     mimetype="text/yaml")


@app.get("/api/config")
def api_config():
    cfg, templates = load_all(ROOT / "config")
    return jsonify({"ok": True, "config": _config_dict(cfg),
                    "templates": _templates_dict(templates)})


def _load_config(kode=None):
    """Load config — proyek by kode (F3.6), fallback legacy kalau kode kosong."""
    if kode:
        return load_project(CONFIG_DIR, kode)
    return load_all(CONFIG_DIR)


@app.post("/api/hitung")
def api_hitung():
    data = request.get_json(force=True) or {}
    rows = data.get("elemen", [])
    override = data.get("override", {}) or {}
    kode = data.get("kode") or ""
    if not rows:
        return jsonify({"ok": False, "error": "Tidak ada baris elemen."}), 400

    try:
        cfg, templates = _load_config(kode)
    except ConfigError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    elemen, errors = _baca_elemen_json(rows)
    if errors:
        return jsonify({"ok": False, "error": "\n".join(errors)}), 400

    try:
        cfg_efektif = _apply_override(cfg, override)
        cuts, agg, hasil_opt = _hitung(cfg_efektif, templates, elemen)
    except (ConfigError, LengthExceedsStockError, InfeasiblePatternError,
            ValueError) as e:
        resp = {"ok": False, "error": str(e)}
        if isinstance(e, InfeasiblePatternError):
            resp["bug_internal"] = True
        return jsonify(resp), 400

    # agregasi per diameter utk BBS tampilan
    bbs_rows = [_bbs_dict(c) for c in agg]
    total_berat = sum(c.panjang_mm / 1000 * c.jumlah * cfg_efektif.unit_weight[c.dia]
                      for c in agg)
    total_batang = sum(r.total_batang for r in hasil_opt.values())
    total_waste = sum(r.total_sisa_mm for r in hasil_opt.values())

    return jsonify({
        "ok": True,
        "config": _config_dict(cfg_efektif),
        "override_aktif": list(override.keys()),
        "bbs": bbs_rows,
        "optimizer": {str(d): _opt_dict(r) for d, r in
                      sorted(hasil_opt.items())},
        "total": {
            "berat_kg": round(total_berat, 2),
            "batang": total_batang,
            "sisa_mm": total_waste,
            "baris_bbs": len(bbs_rows),
        },
    })


@app.post("/api/export")
def api_export():
    data = request.get_json(force=True) or {}
    rows = data.get("elemen", [])
    override = data.get("override", {}) or {}
    kode = data.get("kode") or ""
    if not rows:
        return jsonify({"ok": False, "error": "Tidak ada baris elemen."}), 400

    try:
        cfg, templates = _load_config(kode)
    except ConfigError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    elemen, errors = _baca_elemen_json(rows)
    if errors:
        return jsonify({"ok": False, "error": "\n".join(errors)}), 400
    try:
        cfg_efektif = _apply_override(cfg, override)
        cuts, agg, hasil_opt = _hitung(cfg_efektif, templates, elemen)
    except (ConfigError, LengthExceedsStockError, InfeasiblePatternError,
            ValueError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    out_dir = ROOT / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = out_dir / f"BBS_{cfg_efektif.kode}_{ts}.xlsx"
    generate_excel(cfg_efektif, elemen, cuts, hasil_opt, ROOT / "config",
                   out_path)
    return send_file(out_path, as_attachment=True,
                     download_name=out_path.name)


if __name__ == "__main__":
    # Bind 0.0.0.0 — akses dari luar via VPS_IP:8097 (Brahma request, 2026-08-05)
    app.run(host="0.0.0.0", port=8097, debug=False)
