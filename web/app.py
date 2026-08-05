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
from config_loader import load_all              # noqa: E402
from export import generate_excel               # noqa: E402
from models import (ConfigError, Cut, ElemenInput, InfeasiblePatternError,
                    LengthExceedsStockError)    # noqa: E402
from optimizer import optimize_all              # noqa: E402

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False


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


@app.get("/api/config")
def api_config():
    cfg, templates = load_all(ROOT / "config")
    return jsonify({"ok": True, "config": _config_dict(cfg),
                    "templates": _templates_dict(templates)})


@app.post("/api/hitung")
def api_hitung():
    data = request.get_json(force=True) or {}
    rows = data.get("elemen", [])
    override = data.get("override", {}) or {}
    if not rows:
        return jsonify({"ok": False, "error": "Tidak ada baris elemen."}), 400

    cfg, templates = load_all(ROOT / "config")
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
    if not rows:
        return jsonify({"ok": False, "error": "Tidak ada baris elemen."}), 400

    cfg, templates = load_all(ROOT / "config")
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
    # 07-SPEC-webui: bind 127.0.0.1 port 8097 — bukan 0.0.0.0
    app.run(host="127.0.0.1", port=8097, debug=False)
