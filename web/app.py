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
from config_loader import (load_all, load_layered, list_drawings,       # noqa: E402
                           list_projects, migrate_legacy,               # noqa: E402
                           migrate_legacy_layered, load_project,         # noqa: E402
                           resolve_config, load_drawing)                # noqa: E402
from export import generate_excel               # noqa: E402
from models import (ConfigError, Cut, ElemenInput, InfeasiblePatternError,
                    LengthExceedsStockError, TOOL_VERSION)   # noqa: E402
from optimizer import optimize_all              # noqa: E402

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

CONFIG_DIR = ROOT / "config"

# migrasi config lama → projects/ sekali (F3.6 §7)
migrate_legacy(CONFIG_DIR)
# migrasi berlapis (08) — jalan kalau belum ada folder berlapis
migrate_legacy_layered(CONFIG_DIR)


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
        # 12-SPEC §3.1: L_mm nama utama; bentang_bersih_mm alias tetap diterima
        bentang_raw = row.get("L_mm", row.get("bentang_bersih_mm"))
        # 13-SPEC §2: L2_mm — dimensi kedua (plat)
        l2_raw = row.get("L2_mm", 0)
        jumlah_raw = row.get("jumlah")
        lokasi = str(row.get("lokasi", "")).strip()
        if not tipe:
            errors.append(f"Baris {idx}: tipe kosong")
            continue
        try:
            bentang = int(bentang_raw)
        except (TypeError, ValueError):
            errors.append(f"Baris {idx}: L_mm / bentang_bersih_mm tidak valid: "
                          f"{bentang_raw!r}")
            continue
        if bentang <= 0:
            errors.append(f"Baris {idx}: L_mm / bentang_bersih_mm harus "
                          f"positif: {bentang}")
            continue
        try:
            l2 = int(l2_raw) if l2_raw not in (None, "") else 0
        except (TypeError, ValueError):
            errors.append(f"Baris {idx}: L2_mm tidak valid: {l2_raw!r}")
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
                                  jumlah=jumlah, lokasi=lokasi, L2_mm=l2))
    return elemen, errors


ALLOWED_OVERRIDES = ("metode_hitung", "zona_tumpuan_faktor", "kerf_mm",
                     "sisa_min_simpan_mm")


def _num(v, nama):
    try:
        return float(v)
    except (TypeError, ValueError):
        raise ConfigError(f"Override {nama}: harus angka, dapat {v!r}")


def _apply_override(cfg, override: dict):
    """Override config — dataclasses.replace, tidak menyentuh file (PATCH-02).

    Mendukung dua bentuk:
    - flat legacy (4 field): metode_hitung, zona_tumpuan_faktor, kerf_mm,
      sisa_min_simpan_mm (07-SPEC-webui §4)
    - nested luas (PATCH-02 §1.3 'Pakai sekali'): stok, cover, ld, lap,
      unit_weight, hook_tail, bend_factor, koreksi_bend_aktif, sengkang
    """
    if not override:
        return cfg

    KNOWN = {"metode_hitung", "zona_tumpuan_faktor", "kerf_mm",
             "sisa_min_simpan_mm", "stok", "cover", "ld", "lap",
             "unit_weight", "hook_tail", "bend_factor",
             "koreksi_bend_aktif", "bend_deduction_faktor", "hook_konvensi",
             "lap_metode", "lap_berselang_offset_mm", "sengkang"}
    asing = set(override) - KNOWN
    if asing:
        raise ConfigError(
            f"Override tidak dikenal: {', '.join(sorted(asing))}. "
            f"Didukung: {', '.join(sorted(KNOWN))}")

    sk = cfg.sengkang_cfg
    stok = cfg.stok
    ld = dict(cfg.ld)
    lap = dict(cfg.lap)
    uw = dict(cfg.unit_weight)
    cover = dict(cfg.cover)
    hook_tail = {s: dict(m) for s, m in cfg.hook_tail.items()}
    bend = cfg.bend_factor
    bend_f = dict(cfg.bend_faktor)
    koreksi = cfg.koreksi_bend_aktif
    konvensi = cfg.hook_konvensi
    metode = cfg.lap_metode
    off = cfg.lap_berselang_offset_mm

    # ── flat legacy (4 field) ──
    if "metode_hitung" in override:
        m = override["metode_hitung"]
        if m not in ("kontinyu", "per_zona"):
            raise ConfigError(
                f"metode_hitung harus 'kontinyu' atau 'per_zona', dapat {m!r}")
        sk = dataclasses.replace(sk, metode_hitung=m)
    if "zona_tumpuan_faktor" in override:
        f = _num(override["zona_tumpuan_faktor"], "zona_tumpuan_faktor")
        if not (0.0 <= f <= 0.5):
            raise ConfigError(f"zona_tumpuan_faktor = {f} harus 0-0.5")
        sk = dataclasses.replace(sk, zona_tumpuan_faktor=f)
    if "kerf_mm" in override:
        stok = dataclasses.replace(stok, kerf_mm=int(_num(override["kerf_mm"], "kerf_mm")))
    if "sisa_min_simpan_mm" in override:
        stok = dataclasses.replace(
            stok, sisa_min_simpan_mm=int(_num(override["sisa_min_simpan_mm"],
                                              "sisa_min_simpan_mm")))

    # ── nested luas (PATCH-02) ──
    if "stok" in override:
        s = override["stok"]
        for k in ("panjang_batang_mm", "kerf_mm", "sisa_min_simpan_mm"):
            if k in s:
                stok = dataclasses.replace(stok, **{k: int(_num(s[k], f"stok.{k}"))})
    if "cover" in override:
        for k, v in override["cover"].items():
            cover[k] = int(_num(v, f"cover.{k}"))
    if "ld" in override:
        ld = {int(k): int(_num(v, f"ld.{k}")) for k, v in override["ld"].items()}
    if "lap" in override:
        lap = {int(k): int(_num(v, f"lap.{k}")) for k, v in override["lap"].items()}
    if "unit_weight" in override:
        uw = {int(k): _num(v, f"unit_weight.{k}")
              for k, v in override["unit_weight"].items()}
    if "hook_tail" in override:
        for sudut, m in override["hook_tail"].items():
            sudut_i = int(sudut)
            hook_tail[sudut_i] = {int(d): int(_num(v, f"hook_tail.{sudut}.{d}"))
                                  for d, v in m.items()}
    if "bend_factor" in override:
        bend = int(_num(override["bend_factor"], "bend_factor"))
    if "koreksi_bend_aktif" in override:
        koreksi = bool(override["koreksi_bend_aktif"])
    if "bend_deduction_faktor" in override:
        bend_f = {int(k): int(_num(v, f"bend_deduction_faktor.{k}"))
                  for k, v in override["bend_deduction_faktor"].items()}
    if "hook_konvensi" in override:
        konvensi = str(override["hook_konvensi"])
        if konvensi not in ("tail_terpisah", "hook_total"):
            raise ConfigError(
                f"hook_konvensi harus 'tail_terpisah' atau 'hook_total', "
                f"dapat {konvensi!r}")
    if "lap_metode" in override:
        lm = str(override["lap_metode"])
        if lm not in ("sisa_di_ujung", "bagi_rata", "berselang"):
            raise ConfigError(
                f"lap_metode harus 'sisa_di_ujung', 'bagi_rata', atau "
                f"'berselang', dapat {lm!r}")
        metode = lm
    if "lap_berselang_offset_mm" in override:
        off = int(_num(override["lap_berselang_offset_mm"],
                       "lap_berselang_offset_mm"))
    if "sengkang" in override:
        s = override["sengkang"]
        if "zona_tumpuan_faktor" in s:
            sk = dataclasses.replace(sk, zona_tumpuan_faktor=float(
                _num(s["zona_tumpuan_faktor"], "sengkang.zona_tumpuan_faktor")))
        if "jarak_sengkang_pertama_mm" in s:
            sk = dataclasses.replace(sk, jarak_sengkang_pertama_mm=int(
                _num(s["jarak_sengkang_pertama_mm"], "sengkang.jarak_sengkang_pertama_mm")))
        if "metode_hitung" in s:
            m = s["metode_hitung"]
            if m not in ("kontinyu", "per_zona"):
                raise ConfigError(
                    f"metode_hitung harus 'kontinyu' atau 'per_zona', dapat {m!r}")
            sk = dataclasses.replace(sk, metode_hitung=m)

    return dataclasses.replace(cfg, sengkang_cfg=sk, stok=stok, ld=ld, lap=lap,
                               unit_weight=uw, cover=cover, hook_tail=hook_tail,
                               bend_factor=bend, bend_faktor=bend_f,
                               koreksi_bend_aktif=koreksi,
                               hook_konvensi=konvensi,
                               lap_metode=metode,
                               lap_berselang_offset_mm=off)


def _templates_dict(templates):
    out = {}
    for nama, t in templates.items():
        out[nama] = {
            "tipe": t.tipe,
            "deskripsi": t.deskripsi,
            "b_mm": t.b_mm,
            "h_mm": t.h_mm,
            "label_L": t.label_L,
            "bantuan_L": t.bantuan_L,
            "tulangan": [{"posisi": x.posisi, "dia": x.dia,
                          "jumlah": x.jumlah,
                          "tumpuan_kedua_ujung": x.tumpuan_kedua_ujung,
                          "shape": x.shape, "vars": dict(x.vars),
                          "zona_sambung_terlarang": list(
                              x.zona_sambung_terlarang)}
                         for x in t.tulangan],
            # 12-SPEC §2: sengkang daftar kelompok
            "sengkang": [{"nama": s.nama, "dia": s.dia,
                          "jarak_tumpuan_mm": s.jarak_tumpuan_mm,
                          "jarak_lapangan_mm": s.jarak_lapangan_mm,
                          "kaki": s.kaki,
                          "hook_sudut": s.hook_sudut,
                          "bengkokan": dict(s.bengkokan),
                          "shape": s.shape,
                          "jumlah_per_set": s.jumlah_per_set}
                         for s in t.sengkang],
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
        "bend_deduction_faktor": {str(k): v for k, v in
                                  sorted(cfg.bend_faktor.items())},
        "metode_hitung": cfg.sengkang_cfg.metode_hitung,
        "zona_tumpuan_faktor": cfg.sengkang_cfg.zona_tumpuan_faktor,
        "jarak_sengkang_pertama_mm": cfg.sengkang_cfg.jarak_sengkang_pertama_mm,
        "koreksi_bend_aktif": cfg.koreksi_bend_aktif,
        "hook_konvensi": cfg.hook_konvensi,
        "lap_metode": cfg.lap_metode,
        "lap_berselang_offset_mm": cfg.lap_berselang_offset_mm,
        "unit_weight": {str(k): v for k, v in sorted(cfg.unit_weight.items())},
        "warnings": list(cfg.warnings),
    }


def _opt_dict(res, unit_weight=None):
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
        # PATCH-06 §4: berat dihitung backend — JS tidak menghitung ulang
        "berat_kg": round(res.total_panjang_terpakai_mm / 1000 *
                          (unit_weight or {}).get(res.dia, 0), 2),
    }


def _bbs_dict(c, unit_weight=None):
    """c = Cut (bisa agregat). total_m & berat_kg DARI BACKEND — JS & Excel
    memakai nilai yang sama, tidak menghitung ulang (PATCH-06 §4)."""
    total_m = c.panjang_mm / 1000 * c.jumlah
    return {"bar_mark": c.bar_mark, "lokasi": c.lokasi, "tipe": c.tipe_elemen,
            "posisi": c.posisi, "shape": c.shape_code, "dia": c.dia,
            "panjang_mm": c.panjang_mm, "jumlah": c.jumlah,
            "total_m": round(total_m, 3),
            "berat_kg": round(total_m * (unit_weight or {}).get(c.dia, 0), 2),
            "bagian": c.bagian,
            "sambungan_di_mm": list(c.sambungan_di_mm),
            "segmen_mm": list(c.segmen_mm)}


def _lap_report(cuts, cfg) -> dict:
    """Tambahan baja akibat lap splice per diameter (11-SPEC §6).

    Teoretis = panjang elemen tanpa lewatan; total = Σ potongan (termasuk
    lewatan); % tambahan = (total−teoretis)/teoretis.
    """
    import re
    # kelompokkan per bar_mark dasar (tanpa akhiran a/b) + dia
    groups: dict[tuple, dict] = {}
    for c in cuts:
        if not c.bagian:
            continue
        base = re.sub(r"[a-z]+$", "", c.bar_mark)
        n_pot = c.bagian[1]
        g = groups.setdefault((base, c.dia),
                              {"dia": c.dia, "total": 0, "jumlah": 0,
                               "n_pot": n_pot})
        g["total"] += c.panjang_mm * c.jumlah
        g["jumlah"] += c.jumlah
        g["n_pot"] = max(g["n_pot"], n_pot)
    out = {}
    for (base, dia), g in groups.items():
        Lp = cfg.lap.get(dia, 0)
        n_pot = max(1, g["n_pot"])
        # jumlah batang tersambung = jumlah potongan / potongan per batang
        n_batang = round(g["jumlah"] / n_pot) if n_pot else 0
        total = g["total"]
        tambahan = n_batang * (n_pot - 1) * Lp
        teoretis = total - tambahan
        pct = (total - teoretis) / teoretis * 100 if teoretis else 0
        out[dia] = {
            "teoretis_m": round(teoretis / 1000, 3),
            "tambahan_m": round(tambahan / 1000, 3),
            "total_m": round(total / 1000, 3),
            "pct": round(pct, 1),
            "batang_tersambung": n_batang,
        }
    return out


def _hitung(cfg, templates, elemen, gambar_kode=None):
    """Inti perhitungan — modul yang SAMA dengan CLI.

    gambar_kode: prefix bar_mark (08 §4.3) — diterapkan DI bbs.generate_bbs
    supaya web & CLI konsisten (PATCH-03 #3).
    """
    # validasi tipe
    for el in elemen:
        if el.tipe not in templates:
            raise ConfigError(
                f"Tipe '{el.tipe}' tidak ada di templates.yaml. "
                f"Tersedia: {', '.join(sorted(templates))}")
    cuts = generate_bbs(templates, elemen, cfg, gambar_kode=gambar_kode)
    agg = agregasi(cuts)
    hasil_opt = optimize_all(agg, cfg)
    return cuts, agg, hasil_opt


# ── akses VPS (PATCH-02 §3) — opsi 3 default ───────────────
# Bind bukan 127.0.0.1 → baca boleh publik, TULIS hanya dari localhost.
def tulis_local_only(f):
    from functools import wraps
    @wraps(f)
    def w(*a, **k):
        addr = request.remote_addr or ""
        if addr not in ("127.0.0.1", "::1"):
            return jsonify({
                "ok": False,
                "error": "Endpoint tulis hanya bisa dipakai dari localhost "
                         "(akses VPS publik = baca saja). SSH ke VPS atau "
                         "gunakan SSH tunnel."}), 403
        return f(*a, **k)
    return w


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
    def nd(d):
        return {str(k): v for k, v in (d or {}).items()}
    def hook_sig(h):
        h = h or {}
        return {str(s): nd(m) for s, m in h.items() if isinstance(m, dict)}
    return {
        "cover": nd(cfg.get("selimut_beton_mm")),
        "ld": nd(cfg.get("panjang_penyaluran_mm")),
        "lap": nd(cfg.get("lap_splice_mm")),
        "hook": hook_sig(cfg.get("hook")),
        "sengkang": {str(k): v for k, v in (cfg.get("sengkang") or {}).items()},
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
    # normalize key → str biar setara dengan payload JSON
    def nd(d):
        return {str(k): v for k, v in (d or {}).items()}
    def hook_sig(h):
        h = h or {}
        return {str(s): nd(m) for s, m in h.items() if isinstance(m, dict)}
    return {"cover": nd(cfg_d.get("selimut_beton_mm")),
            "ld": nd(cfg_d.get("panjang_penyaluran_mm")),
            "lap": nd(cfg_d.get("lap_splice_mm")),
            "hook": hook_sig(cfg_d.get("hook")),
            "sengkang": {str(k): v for k, v in (cfg_d.get("sengkang") or {}).items()},
            "templates": tpl_d}


@app.get("/api/projects")
def api_projects():
    return jsonify({"ok": True, "projects": list_projects(CONFIG_DIR)})


@app.get("/api/projects/<kode>")
def api_project_get(kode):
    import yaml
    # berlapis: projects/{kode}/project.yaml (default proyek)
    berlapis_f = CONFIG_DIR / "projects" / kode / "project.yaml"
    if berlapis_f.exists():
        tpl_f = CONFIG_DIR / "projects" / kode / "templates.yaml"
        if tpl_f.exists():
            cfg_d = yaml.safe_load(berlapis_f.read_text())
            tpl_d = yaml.safe_load(tpl_f.read_text())
            cfg_d.pop("_meta", None)
            tpl_d.pop("_meta", None)
            return jsonify({"ok": True, "kode": kode,
                            "config": cfg_d, "templates": tpl_d,
                            "berlapis": True})
    # flat legacy: projects/{kode}.yaml
    p = CONFIG_DIR / "projects" / f"{kode}.yaml"
    t = CONFIG_DIR / "templates" / f"{kode}.yaml"
    if not p.exists() or not t.exists():
        return jsonify({"ok": False, "error": f"Proyek '{kode}' tidak ada."}), 404
    cfg_d = yaml.safe_load(p.read_text())
    tpl_d = yaml.safe_load(t.read_text())
    cfg_d.pop("_meta", None)
    tpl_d.pop("_meta", None)
    return jsonify({"ok": True, "kode": kode,
                    "config": cfg_d, "templates": tpl_d, "berlapis": False})


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
    """Ubah default proyek / templates — flat legacy & berlapis (08 §9)."""
    import shutil
    import tempfile
    import yaml
    data = request.get_json(force=True) or {}
    new_kode = str(data.get("kode", kode))
    if new_kode != kode:
        return jsonify({"ok": False,
                        "error": "Kode tidak bisa diubah lewat edit."}), 400
    cfg_d = data.get("config") or {}
    tpl_d = data.get("templates") or {}

    # validasi via loader (tempfile) — satu sumber kebenaran
    try:
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            (td / "project.yaml").write_text(yaml.safe_dump(cfg_d, allow_unicode=True))
            (td / "templates.yaml").write_text(yaml.safe_dump(tpl_d, allow_unicode=True))
            load_all(td)
    except ConfigError as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    # ── berlapis: tulis ke projects/{kode}/ ──
    pdir = CONFIG_DIR / "projects" / kode
    if (pdir / "project.yaml").exists():
        # revisi wajib kalau nilai teknis default berubah
        from datetime import datetime
        old_cfg = yaml.safe_load((pdir / "project.yaml").read_text())
        old_cfg.pop("_meta", None)
        old_tpl = yaml.safe_load((pdir / "templates.yaml").read_text())
        old_tpl.pop("_meta", None)
        old_sig = _signature_patch02(old_cfg, old_tpl)
        new_sig = _signature_patch02(cfg_d, tpl_d)
        if new_sig != old_sig:
            old_rev = str((old_cfg.get("sumber") or {}).get("revisi", "")).strip()
            new_rev = str(cfg_d.get("sumber", {}).get("revisi", "")).strip()
            if old_rev and new_rev == old_rev:
                return jsonify({"ok": False, "error":
                    "Nilai teknis proyek berubah tapi revisi gambar masih sama "
                    f"({old_rev}). Perbarui field revisi."}), 400
        # arsip
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        arsip_dir = CONFIG_DIR / "projects" / kode / "_arsip"
        arsip_dir.mkdir(exist_ok=True)
        shutil.copy2(pdir / "project.yaml", arsip_dir / f"project_{ts}.yaml")
        shutil.copy2(pdir / "templates.yaml", arsip_dir / f"templates_{ts}.yaml")
        meta = (f"_meta:\n  diubah_via: web\n  diubah_pada: "
                f"{datetime.now().astimezone().replace(microsecond=0).isoformat()}\n")
        (pdir / "project.yaml").write_text(meta + yaml.safe_dump(cfg_d, allow_unicode=True))
        (pdir / "templates.yaml").write_text(meta + yaml.safe_dump(tpl_d, allow_unicode=True))
        return jsonify({"ok": True, "kode": kode, "berlapis": True})

    # ── flat legacy (F3.6) ──
    old_sig = _signature_teknis_dari_file(kode)
    if old_sig is None:
        return jsonify({"ok": False, "error": f"Proyek '{kode}' tidak ada."}), 404
    new_sig = _signature_teknis(data)
    if new_sig != old_sig:
        old_rev = _revisi_dari_file(kode)
        new_rev = str(cfg_d.get("sumber", {}).get("revisi", "")).strip()
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
    return jsonify({"ok": True, "kode": kode, "berlapis": False})


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


# ── drawings berlapis (08-SPEC-config-berlapis) ────────────
def _drawing_path(proyek, gambar):
    return CONFIG_DIR / "projects" / proyek / "drawings" / f"{gambar}.yaml"


def _asal_nilai(proj_cfg_d, override_d):
    """Asal tiap nilai: 'proyek' atau 'gambar'. Deep compare per key."""
    out = {}
    # cover
    out["selimut_beton_mm"] = {
        str(k): {"nilai": v, "asal": "gambar" if str(k) in
                 {str(x) for x in (override_d.get("selimut_beton_mm") or {})}
                 else "proyek"}
        for k, v in (proj_cfg_d.get("selimut_beton_mm") or {}).items()}
    ovr_cover = override_d.get("selimut_beton_mm") or {}
    for k, v in ovr_cover.items():
        out["selimut_beton_mm"][str(k)] = {"nilai": v, "asal": "gambar"}
    # ld
    out["panjang_penyaluran_mm"] = {
        str(k): {"nilai": v, "asal": "gambar" if str(k) in
                 {str(x) for x in (override_d.get("panjang_penyaluran_mm") or {})}
                 else "proyek"}
        for k, v in (proj_cfg_d.get("panjang_penyaluran_mm") or {}).items()}
    ovr_ld = override_d.get("panjang_penyaluran_mm") or {}
    for k, v in ovr_ld.items():
        out["panjang_penyaluran_mm"][str(k)] = {"nilai": v, "asal": "gambar"}
    # lap
    out["lap_splice_mm"] = {
        str(k): {"nilai": v, "asal": "gambar" if str(k) in
                 {str(x) for x in (override_d.get("lap_splice_mm") or {})}
                 else "proyek"}
        for k, v in (proj_cfg_d.get("lap_splice_mm") or {}).items()}
    ovr_lap = override_d.get("lap_splice_mm") or {}
    for k, v in ovr_lap.items():
        out["lap_splice_mm"][str(k)] = {"nilai": v, "asal": "gambar"}
    # hook tail
    out["hook_tail"] = {}
    ovr_hook = override_d.get("hook") or {}
    for sudut in ("tail_135_mm", "tail_90_mm"):
        base = (proj_cfg_d.get("hook") or {}).get(sudut, {})
        ovr = ovr_hook.get(sudut, {})
        out["hook_tail"][sudut] = {
            str(k): {"nilai": v, "asal": "gambar" if str(k) in
                     {str(x) for x in ovr} else "proyek"}
            for k, v in base.items()}
        for k, v in ovr.items():
            out["hook_tail"][sudut][str(k)] = {"nilai": v, "asal": "gambar"}
    # sengkang
    out["sengkang"] = {}
    base_sk = proj_cfg_d.get("sengkang") or {}
    ovr_sk = override_d.get("sengkang") or {}
    for k in ("zona_tumpuan_faktor", "jarak_sengkang_pertama_mm", "metode_hitung"):
        out["sengkang"][k] = {"nilai": ovr_sk.get(k, base_sk.get(k)),
                              "asal": "gambar" if k in ovr_sk else "proyek"}
    return out


@app.get("/api/projects/<proyek>/drawings")
def api_drawings(proyek):
    return jsonify({"ok": True, "proyek": proyek,
                    "drawings": list_drawings(CONFIG_DIR / "projects", proyek)})


@app.get("/api/projects/<proyek>/shapes")
def api_shapes_get(proyek):
    """Baca shapes.yaml proyek (10-SPEC) — format mentah untuk editor UI."""
    import yaml
    p = CONFIG_DIR / "projects" / proyek / "shapes.yaml"
    if not p.exists():
        return jsonify({"ok": False,
                        "error": f"Proyek '{proyek}' belum punya shapes.yaml."}), 404
    d = yaml.safe_load(p.read_text()) or {}
    d.pop("_meta", None)
    return jsonify({"ok": True, "shapes": d})


@app.put("/api/projects/<proyek>/shapes")
@tulis_local_only
def api_shapes_put(proyek):
    """Simpan shapes.yaml proyek — validasi via load_shapes (satu sumber)."""
    import shutil
    from datetime import datetime
    import yaml
    from shapes import load_shapes
    data = request.get_json(force=True) or {}
    shapes_d = data.get("shapes")
    if not isinstance(shapes_d, dict) or not shapes_d:
        return jsonify({"ok": False, "error": "shapes wajib mapping non-kosong."}), 400
    pdir = CONFIG_DIR / "projects" / proyek
    p = pdir / "shapes.yaml"
    if not p.exists():
        return jsonify({"ok": False,
                        "error": f"Proyek '{proyek}' belum punya shapes.yaml."}), 404
    # validasi lewat loader — ConfigError → tolak
    import tempfile
    try:
        with tempfile.TemporaryDirectory() as td:
            tp = Path(td) / "shapes.yaml"
            tp.write_text(yaml.safe_dump(shapes_d, allow_unicode=True))
            load_shapes(tp)
    except ConfigError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    # arsip lama
    arsip = pdir / "_arsip"
    arsip.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    shutil.copy2(p, arsip / f"shapes_{ts}.yaml")
    meta = (f"_meta:\n  diubah_via: web\n  diubah_pada: "
            f"{datetime.now().astimezone().replace(microsecond=0).isoformat()}\n")
    p.write_text(meta + yaml.safe_dump(shapes_d, allow_unicode=True))
    return jsonify({"ok": True, "kode": proyek})


@app.get("/api/projects/<proyek>/drawings/<gambar>")
def api_drawing_get(proyek, gambar):
    import yaml
    p = _drawing_path(proyek, gambar)
    if not p.exists():
        return jsonify({"ok": False,
                        "error": f"Gambar '{gambar}' tidak ada."}), 404
    d = yaml.safe_load(p.read_text()) or {}
    d.pop("_meta", None)
    # config efektif + asal nilai
    try:
        cfg, templates, info = load_layered(CONFIG_DIR / "projects", proyek, gambar)
    except ConfigError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    # dict cfg default proyek utk perbandingan asal
    proj_d = yaml.safe_load(
        (CONFIG_DIR / "projects" / proyek / "project.yaml").read_text())
    proj_d.pop("_meta", None)
    asal = _asal_nilai(proj_d, d.get("override") or {})
    return jsonify({"ok": True, "kode": gambar,
                    "drawing": {k: v for k, v in d.items() if k != "override"},
                    "override": d.get("override", {}),
                    "asal": asal,
                    "config_efektif": _config_dict(cfg),
                    "templates": _templates_dict(templates)})


@app.post("/api/projects/<proyek>/drawings")
@tulis_local_only
def api_drawing_create(proyek):
    import yaml
    data = request.get_json(force=True) or {}
    kode = str(data.get("kode", "")).strip()
    if not _valid_kode(kode):
        return jsonify({"ok": False,
                        "error": "kode gambar tidak valid."}), 400
    nama = str(data.get("nama", "")).strip()
    revisi = str(data.get("revisi", "")).strip()
    tanggal = str(data.get("tanggal", "")).strip()
    if not nama or not revisi or not tanggal:
        return jsonify({"ok": False,
                        "error": "nama, revisi, dan tanggal wajib."}), 400
    p = _drawing_path(proyek, kode)
    if p.exists():
        return jsonify({"ok": False,
                        "error": f"Gambar '{kode}' sudah ada."}), 409
    from datetime import datetime
    ts = datetime.now().astimezone().replace(microsecond=0).isoformat()
    drawing = {
        "kode": kode, "nama": nama, "revisi": revisi, "tanggal": tanggal,
        "catatan": str(data.get("catatan", "")),
        "override": {},
        "_meta": {"dibuat_via": "web", "dibuat_pada": ts},
    }
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(drawing, allow_unicode=True))
    return jsonify({"ok": True, "kode": kode}), 201


@app.put("/api/projects/<proyek>/drawings/<gambar>")
@tulis_local_only
def api_drawing_update(proyek, gambar):
    """Simpan override gambar — arsip lama + revisi wajib (per gambar)."""
    import shutil
    import tempfile
    import yaml
    data = request.get_json(force=True) or {}
    p = _drawing_path(proyek, gambar)
    if not p.exists():
        return jsonify({"ok": False,
                        "error": f"Gambar '{gambar}' tidak ada."}), 404
    old_d = yaml.safe_load(p.read_text()) or {}
    old_ovr = old_d.get("override", {}) or {}
    new_ovr = data.get("override", {}) or {}

    # validasi hasil resolusi via loader (tempfile): gambar baru + override
    # cek kelengkapan diameter terhadap template
    try:
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            proj_src = CONFIG_DIR / "projects" / proyek / "project.yaml"
            tpl_src = CONFIG_DIR / "projects" / proyek / "templates.yaml"
            td_proj = td / "proj"
            td_proj.mkdir()
            (td_proj / "project.yaml").write_text(proj_src.read_text())
            (td_proj / "templates.yaml").write_text(tpl_src.read_text())
            (td_proj / "drawings").mkdir()
            (td_proj / "drawings" / f"{gambar}.yaml").write_text(
                yaml.safe_dump({"override": new_ovr}))
            load_layered(td, "proj", gambar)
    except ConfigError as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    # revisi wajib kalau override berubah
    if new_ovr != old_ovr:
        old_rev = str(old_d.get("revisi", "")).strip()
        new_rev = str(data.get("revisi", data.get("revisi", old_rev)) or "").strip()
        if data.get("revisi"):
            new_rev = str(data["revisi"]).strip()
        koreksi = bool(data.get("koreksi_bukan_revisi", False))
        catatan = str(data.get("catatan", "")).strip()
        if old_rev and new_rev == old_rev and not koreksi:
            return jsonify({"ok": False, "error":
                f"Nilai teknis berubah tapi revisi gambar masih sama "
                f"({old_rev}). Kalau ini koreksi salah ketik, tulis alasannya "
                f"di catatan dan centang 'koreksi, bukan revisi gambar'. "
                f"Kalau gambar memang direvisi, isi revisi yang baru."}), 400
        if koreksi and not catatan:
            return jsonify({"ok": False,
                            "error": "Catatan wajib diisi kalau centang "
                                     "'koreksi, bukan revisi gambar'."}), 400

    # arsip per gambar
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    arsip_dir = CONFIG_DIR / "projects" / proyek / "_arsip"
    arsip_dir.mkdir(exist_ok=True)
    arsip = arsip_dir / f"{gambar}_{ts}.yaml"
    shutil.copy2(p, arsip)

    # tulis baru (override saja + metadata; _meta diubah_dari)
    new_d = {
        "kode": gambar,
        "nama": str(data.get("nama", old_d.get("nama", gambar))),
        "revisi": new_rev or str(old_d.get("revisi", "")),
        "tanggal": str(data.get("tanggal", old_d.get("tanggal", ""))),
        "catatan": str(data.get("catatan", old_d.get("catatan", ""))),
        "override": new_ovr,
        "_meta": {"dibuat_via": "web",
                  "dibuat_pada": datetime.now().astimezone()
                  .replace(microsecond=0).isoformat(),
                  "diubah_dari": arsip.name},
    }
    p.write_text(yaml.safe_dump(new_d, allow_unicode=True))
    return jsonify({"ok": True, "kode": gambar, "arsip": arsip.name})


@app.get("/api/projects/<proyek>/drawings/<gambar>/yaml")
def api_drawing_yaml(proyek, gambar):
    p = _drawing_path(proyek, gambar)
    if not p.exists():
        return jsonify({"ok": False,
                        "error": f"Gambar '{gambar}' tidak ada."}), 404
    return send_file(p, as_attachment=True,
                     download_name=f"{gambar}.yaml", mimetype="text/yaml")


@app.get("/api/config")
def api_config():
    cfg, templates = load_all(ROOT / "config")
    return jsonify({"ok": True, "config": _config_dict(cfg),
                    "templates": _templates_dict(templates)})


# ── simpan config dari panel (PATCH-02 §1) ─────────────────
def _signature_patch02(cfg_d, tpl_d):
    """Nilai teknis dari gambar — KECUALI kerf & sisa_min (PATCH-02 §1.4).

    Key diameter dinormalisasi ke str — file YAML (int key) vs payload JSON
    (string key) harus dibandingkan setara."""
    def nd(d):
        return {str(k): v for k, v in (d or {}).items()}

    def hook_sig(h):
        h = h or {}
        return {str(s): nd(m) for s, m in h.items() if isinstance(m, dict)}

    return {
        "stok_panjang": (cfg_d.get("stok") or {}).get("panjang_batang_mm"),
        "cover": nd(cfg_d.get("selimut_beton_mm")),
        "ld": nd(cfg_d.get("panjang_penyaluran_mm")),
        "lap": nd(cfg_d.get("lap_splice_mm")),
        "lap_metode": (cfg_d.get("lap_splice") or {}).get("metode",
                                                          "sisa_di_ujung"),
        "hook": hook_sig(cfg_d.get("hook")),
        "hook_konvensi": (cfg_d.get("hook") or {}).get("konvensi", "tail_terpisah"),
        "sengkang": {str(k): v for k, v in (cfg_d.get("sengkang") or {}).items()},
        # templates TIDAK masuk signature — definisi elemen, bukan nilai teknis
        # gambar (PATCH-05: nambah tipe elemen tidak wajib revisi).
    }


@app.patch("/api/config")
@tulis_local_only
def api_config_update():
    """Simpan config proyek aktif. Validasi via loader + arsip + revisi wajib."""
    import tempfile
    import yaml
    data = request.get_json(force=True) or {}
    kode = data.get("kode") or ""
    if not kode:
        return jsonify({"ok": False, "error": "kode proyek wajib."}), 400
    cfg_d = data.get("config") or {}
    tpl_d = data.get("templates") or {}

    # validasi via tempfile → loader
    try:
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            (td / "project.yaml").write_text(
                yaml.safe_dump(cfg_d, allow_unicode=True))
            (td / "templates.yaml").write_text(
                yaml.safe_dump(tpl_d, allow_unicode=True))
            load_all(td)  # ConfigError → ditangkap
    except ConfigError as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    # revisi wajib kalau nilai teknis berubah
    proj_path = CONFIG_DIR / "projects" / f"{kode}.yaml"
    tpl_path = CONFIG_DIR / "templates" / f"{kode}.yaml"
    if proj_path.exists():
        old_cfg = yaml.safe_load(proj_path.read_text())
        old_cfg.pop("_meta", None)
        old_tpl = yaml.safe_load(tpl_path.read_text())
        old_tpl.pop("_meta", None)
        old_sig = _signature_patch02(old_cfg, old_tpl)
        new_sig = _signature_patch02(cfg_d, tpl_d)
        if new_sig != old_sig:
            old_rev = str((old_cfg.get("sumber") or {}).get("revisi", "")).strip()
            new_rev = str(cfg_d.get("sumber", {}).get("revisi", "")).strip()
            koreksi = bool(data.get("koreksi_bukan_revisi", False))
            catatan = str(data.get("catatan", "")).strip()
            if old_rev and new_rev == old_rev and not koreksi:
                return jsonify({"ok": False, "error":
                    f"Nilai teknis berubah tapi revisi gambar masih sama "
                    f"({old_rev}). Kalau ini koreksi salah ketik, tulis "
                    f"alasannya di catatan dan centang 'koreksi, bukan revisi "
                    f"gambar'. Kalau gambar memang direvisi, isi revisi yang "
                    f"baru."}), 400
            if koreksi and not catatan:
                return jsonify({"ok": False,
                                "error": "Catatan wajib diisi kalau centang "
                                         "'koreksi, bukan revisi gambar'."}), 400

    # arsip file lama
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    arsip_dir = CONFIG_DIR / "_arsip"
    arsip_dir.mkdir(exist_ok=True)
    arsip_old = None
    if proj_path.exists():
        arsip_old = arsip_dir / f"project_{ts}.yaml"
        proj_path.rename(arsip_old)
    if tpl_path.exists():
        (arsip_dir / f"templates_{ts}.yaml").write_text(tpl_path.read_text())
        tpl_path.unlink()

    # tulis baru + _meta
    meta = (f"_meta:\n  diubah_via: web\n"
            f"  diubah_pada: {datetime.now().astimezone().replace(microsecond=0).isoformat()}\n"
            f"  diubah_dari: {arsip_old.name if arsip_old else '-'}\n")
    proj_path.write_text(meta + yaml.safe_dump(cfg_d, allow_unicode=True))
    tpl_path.write_text(meta + yaml.safe_dump(tpl_d, allow_unicode=True))
    return jsonify({"ok": True, "kode": kode,
                    "arsip": arsip_old.name if arsip_old else None})


def _load_config(proyek=None, gambar=None):
    """Load config — berlapis (proyek+gambar, 08) / flat legacy / legacy."""
    if proyek and gambar:
        return load_layered(CONFIG_DIR / "projects", proyek, gambar)   # (cfg, templates, info)
    if proyek:
        cfg, templates = load_project(CONFIG_DIR, proyek)  # flat F3.6
        return cfg, templates, None
    return (*load_all(CONFIG_DIR), None)


def _override_diff(cfg_lama, cfg_baru) -> list[str]:
    """Daftar field yang berubah karena override — utk banner & Excel."""
    lines = []
    if cfg_lama.stok.panjang_batang_mm != cfg_baru.stok.panjang_batang_mm:
        lines.append(f"stok.panjang_batang_mm: {cfg_lama.stok.panjang_batang_mm} → {cfg_baru.stok.panjang_batang_mm}")
    if cfg_lama.stok.kerf_mm != cfg_baru.stok.kerf_mm:
        lines.append(f"kerf_mm: {cfg_lama.stok.kerf_mm} → {cfg_baru.stok.kerf_mm}")
    if cfg_lama.stok.sisa_min_simpan_mm != cfg_baru.stok.sisa_min_simpan_mm:
        lines.append(f"sisa_min_simpan_mm: {cfg_lama.stok.sisa_min_simpan_mm} → {cfg_baru.stok.sisa_min_simpan_mm}")
    for zona in set(cfg_lama.cover) | set(cfg_baru.cover):
        if cfg_lama.cover.get(zona) != cfg_baru.cover.get(zona):
            lines.append(f"cover.{zona}: {cfg_lama.cover.get(zona)} → {cfg_baru.cover.get(zona)}")
    for d in set(cfg_lama.ld) | set(cfg_baru.ld):
        if cfg_lama.ld.get(d) != cfg_baru.ld.get(d):
            lines.append(f"Ld D{d}: {cfg_lama.ld.get(d)} → {cfg_baru.ld.get(d)}")
    for d in set(cfg_lama.lap) | set(cfg_baru.lap):
        if cfg_lama.lap.get(d) != cfg_baru.lap.get(d):
            lines.append(f"lap D{d}: {cfg_lama.lap.get(d)} → {cfg_baru.lap.get(d)}")
    for d in set(cfg_lama.unit_weight) | set(cfg_baru.unit_weight):
        if cfg_lama.unit_weight.get(d) != cfg_baru.unit_weight.get(d):
            lines.append(f"unit_weight D{d}: {cfg_lama.unit_weight.get(d)} → {cfg_baru.unit_weight.get(d)}")
    for s in set(cfg_lama.hook_tail) | set(cfg_baru.hook_tail):
        a, b = cfg_lama.hook_tail.get(s, {}), cfg_baru.hook_tail.get(s, {})
        for d in set(a) | set(b):
            if a.get(d) != b.get(d):
                lines.append(f"hook {s}° D{d}: {a.get(d)} → {b.get(d)}")
    if cfg_lama.sengkang_cfg != cfg_baru.sengkang_cfg:
        sk_l, sk_b = cfg_lama.sengkang_cfg, cfg_baru.sengkang_cfg
        for f in ("zona_tumpuan_faktor", "jarak_sengkang_pertama_mm", "metode_hitung"):
            if getattr(sk_l, f) != getattr(sk_b, f):
                lines.append(f"sengkang.{f}: {getattr(sk_l, f)} → {getattr(sk_b, f)}")
    if cfg_lama.koreksi_bend_aktif != cfg_baru.koreksi_bend_aktif:
        lines.append(f"koreksi_bengkokan: {cfg_lama.koreksi_bend_aktif} → {cfg_baru.koreksi_bend_aktif}")
    if cfg_lama.hook_konvensi != cfg_baru.hook_konvensi:
        lines.append(f"konvensi hook: {cfg_lama.hook_konvensi} → {cfg_baru.hook_konvensi}")
    if cfg_lama.lap_metode != cfg_baru.lap_metode:
        lines.append(f"metode lap splice: {cfg_lama.lap_metode} → {cfg_baru.lap_metode}")
    for s in set(cfg_lama.bend_faktor) | set(cfg_baru.bend_faktor):
        if cfg_lama.bend_faktor.get(s) != cfg_baru.bend_faktor.get(s):
            lines.append(f"bend_deduction_faktor {s}°: "
                         f"{cfg_lama.bend_faktor.get(s)} → {cfg_baru.bend_faktor.get(s)}")
    return lines


@app.post("/api/hitung")
def api_hitung():
    data = request.get_json(force=True) or {}
    rows = data.get("elemen", [])
    override = data.get("override", {}) or {}
    proyek = data.get("proyek") or data.get("kode") or ""
    gambar = data.get("gambar") or ""
    if not rows:
        return jsonify({"ok": False, "error": "Tidak ada baris elemen."}), 400

    # PATCH-06 §2 — proyek & gambar WAJIB. Tanpa keduanya, perhitungan diam-diam
    # memakai default dan user bisa dapat hasil dari gambar yang salah.
    # Kosong → 400, sebut field yang kurang + daftar gambar tersedia.
    if not proyek:
        return jsonify({"ok": False, "error":
            "Field 'proyek' wajib diisi."}), 400
    if not gambar:
        daftar = [d["kode"] for d in
                  list_drawings(CONFIG_DIR / "projects", proyek)]
        tersedia = ", ".join(daftar) if daftar else "(proyek belum punya gambar)"
        return jsonify({"ok": False, "error":
            f"Field 'gambar' wajib diisi. Proyek '{proyek}' — "
            f"gambar tersedia: {tersedia}."}), 400

    try:
        cfg, templates, info = _load_config(proyek, gambar)
    except ConfigError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    elemen, errors = _baca_elemen_json(rows)
    if errors:
        return jsonify({"ok": False, "error": "\n".join(errors)}), 400
    # 13-SPEC §2: plat wajib punya L2_mm
    for i, el in enumerate(elemen, 1):
        if templates.get(el.tipe, None) is not None and \
                templates[el.tipe].tipe == "plat" and not el.L2_mm:
            return jsonify({"ok": False,
                            "error": f"Baris {i}: tipe 'plat' wajib diisi "
                                     f"L2_mm (dimensi kedua)."}), 400

    try:
        cfg_efektif = _apply_override(cfg, override)
        cuts, agg, hasil_opt = _hitung(cfg_efektif, templates, elemen,
                                       gambar_kode=gambar or (info or {}).get("kode"))
    except (ConfigError, LengthExceedsStockError, InfeasiblePatternError,
            ValueError) as e:
        resp = {"ok": False, "error": str(e)}
        if isinstance(e, InfeasiblePatternError):
            resp["bug_internal"] = True
        return jsonify(resp), 400

    diff = _override_diff(cfg, cfg_efektif)

    # agregasi per diameter utk BBS tampilan — berat & total DARI BACKEND
    uw = cfg_efektif.unit_weight
    bbs_rows = [_bbs_dict(c, uw) for c in agg]
    total_berat = sum(c.panjang_mm / 1000 * c.jumlah * uw[c.dia]
                      for c in agg)
    total_panjang_m = sum(c.panjang_mm / 1000 * c.jumlah for c in agg)
    total_batang = sum(r.total_batang for r in hasil_opt.values())
    total_waste = sum(r.total_sisa_mm for r in hasil_opt.values())

    return jsonify({
        "ok": True,
        "proyek": proyek, "gambar": gambar, "info_gambar": info,
        "config": _config_dict(cfg_efektif),
        "override_aktif": list(override.keys()),
        "override_diff": diff,
        "bbs": bbs_rows,
        "lap_report": _lap_report(cuts, cfg_efektif),
        "optimizer": {str(d): _opt_dict(r, uw) for d, r in
                      sorted(hasil_opt.items())},
        "total": {
            "berat_kg": round(total_berat, 2),
            "total_panjang_m": round(total_panjang_m, 3),
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
    proyek = data.get("proyek") or data.get("kode") or ""
    gambar = data.get("gambar") or ""
    if not rows:
        return jsonify({"ok": False, "error": "Tidak ada baris elemen."}), 400

    # PATCH-06 §2 — proyek & gambar WAJIB (sama seperti /api/hitung)
    if not proyek:
        return jsonify({"ok": False, "error":
            "Field 'proyek' wajib diisi."}), 400
    if not gambar:
        daftar = [d["kode"] for d in
                  list_drawings(CONFIG_DIR / "projects", proyek)]
        tersedia = ", ".join(daftar) if daftar else "(proyek belum punya gambar)"
        return jsonify({"ok": False, "error":
            f"Field 'gambar' wajib diisi. Proyek '{proyek}' — "
            f"gambar tersedia: {tersedia}."}), 400

    try:
        cfg, templates, info = _load_config(proyek, gambar)
    except ConfigError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    elemen, errors = _baca_elemen_json(rows)
    if errors:
        return jsonify({"ok": False, "error": "\n".join(errors)}), 400
    # 13-SPEC §2: plat wajib punya L2_mm
    for i, el in enumerate(elemen, 1):
        if templates.get(el.tipe, None) is not None and \
                templates[el.tipe].tipe == "plat" and not el.L2_mm:
            return jsonify({"ok": False,
                            "error": f"Baris {i}: tipe 'plat' wajib diisi "
                                     f"L2_mm (dimensi kedua)."}), 400
    try:
        cfg_efektif = _apply_override(cfg, override)
        cuts, agg, hasil_opt = _hitung(cfg_efektif, templates, elemen,
                                       gambar_kode=gambar or (info or {}).get("kode"))
    except (ConfigError, LengthExceedsStockError, InfeasiblePatternError,
            ValueError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    diff = _override_diff(cfg, cfg_efektif)
    lap_rep = _lap_report(cuts, cfg_efektif)
    out_dir = ROOT / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    g = (gambar or (info or {}).get("kode") or "")
    nama = f"BBS_{cfg_efektif.kode}"
    if g:
        nama += f"_{g}"
    nama += f"_{ts}.xlsx"
    out_path = out_dir / nama
    generate_excel(cfg_efektif, elemen, cuts, hasil_opt, ROOT / "config",
                   out_path, override_info=diff, gambar_info=info,
                   lap_report=lap_rep)
    return send_file(out_path, as_attachment=True,
                     download_name=out_path.name)


if __name__ == "__main__":
    # Bind 0.0.0.0 — akses dari luar via VPS_IP:8097 (Brahma request, 2026-08-05)
    app.run(host="0.0.0.0", port=8097, debug=False)
