"""Config loader — baca & validasi config YAML (F0).

Aturan project:
- Tidak ada nilai teknis hardcoded di kode. Semua dari config.
- Fail loud: kalau config tidak lengkap, kumpulkan SEMUA error
  sekaligus lalu raise — jangan berhenti di error pertama.
- Config immutable setelah load (frozen dataclass).
"""

from pathlib import Path

import yaml

from models import (ConfigError, ElementTemplate, OptimizerConfig,
                    ProjectConfig, SengkangConfig, SourceInfo, StockConfig,
                    TemplateSengkang, TemplateTulangan)

ALLOWED_ALOKASI_TIPES = ("balok",)          # kolom/plat menyusul (F5/F7)
ALLOWED_SENGKANG_HOOK = (90, 135)
HOOK_SUDUT_KEYS = {90: "tail_90_mm", 135: "tail_135_mm"}


# ── helpers ─────────────────────────────────────────────────
def _norm_dia(value):
    """Diameter sebagai key YAML bisa int (10:) atau str ('10').
    Normalisasi ke int — konsisten, jangan campur tipe."""
    if isinstance(value, bool):
        raise ConfigError(f"Diameter tidak valid: {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    raise ConfigError(f"Diameter tidak valid: {value!r}")


def _norm_int(value, nama, path, allow_zero=False):
    try:
        v = int(value)
    except (TypeError, ValueError):
        raise ConfigError(f"{path}.{nama}: harus angka integer, dapat {value!r}")
    if v < 0 or (v == 0 and not allow_zero):
        raise ConfigError(f"{path}.{nama}: tidak boleh negatif atau nol ({v})")
    return v


def _norm_float(value, nama, path):
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ConfigError(f"{path}.{nama}: harus angka, dapat {value!r}")
    return v


# ── loader utama ────────────────────────────────────────────
def load_project_config(path) -> ProjectConfig:
    """Load config/project.yaml → ProjectConfig, kumpulkan semua error."""
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"Config tidak ditemukan: {path}")

    with open(path) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: config harus berupa mapping YAML")

    errors: list[str] = []
    warnings: list[str] = []
    cfg = _parse_project(data, errors, warnings)
    if errors:
        raise ConfigError(
            "Config tidak lengkap.\n\n" + "\n\n".join(errors) +
            "\n\nPerbaiki config/project.yaml lalu jalankan ulang.")
    return cfg


def _parse_project(data, errors, warnings) -> ProjectConfig:
    proyek = data.get("proyek") or {}
    nama = str(proyek.get("nama", ""))
    kode = str(proyek.get("kode", ""))

    sumber_raw = data.get("sumber") or {}
    sumber = SourceInfo(
        dokumen=str(sumber_raw.get("dokumen", "")),
        revisi=str(sumber_raw.get("revisi", "")),
        tanggal=str(sumber_raw.get("tanggal", "")),
        catatan=str(sumber_raw.get("catatan", "")),
    )

    # ── stok ──
    stok_raw = data.get("stok") or {}
    try:
        panjang = _norm_int(stok_raw.get("panjang_batang_mm"), "panjang_batang_mm", "stok")
        kerf = _norm_int(stok_raw.get("kerf_mm"), "kerf_mm", "stok", allow_zero=True)
        sisa_min = _norm_int(stok_raw.get("sisa_min_simpan_mm"), "sisa_min_simpan_mm", "stok", allow_zero=True)
    except ConfigError as e:
        errors.append(str(e))
        panjang, kerf, sisa_min = 12000, 3, 1000
    if not (6000 <= panjang <= 12000):
        warnings.append(
            f"WARNING: stok.panjang_batang_mm = {panjang} di luar 6000-12000 "
            f"(biasanya salah ketik)")
    if kerf > 20:
        warnings.append(f"WARNING: stok.kerf_mm = {kerf} > 20 (cek lebar mata potong)")
    stok = StockConfig(panjang_batang_mm=panjang, kerf_mm=kerf,
                       sisa_min_simpan_mm=sisa_min)

    # ── cover ──
    cover = {}
    for zona, v in (data.get("selimut_beton_mm") or {}).items():
        try:
            cover[zona] = _norm_int(v, zona, "selimut_beton_mm")
        except ConfigError as e:
            errors.append(str(e))

    # ── dict per diameter ──
    ld = _load_dia_dict(data.get("panjang_penyaluran_mm"), "panjang_penyaluran_mm", errors)
    lap = _load_dia_dict(data.get("lap_splice_mm"), "lap_splice_mm", errors)
    uw = _load_dia_dict(data.get("unit_weight_kg_per_m"), "unit_weight_kg_per_m", errors)

    # ── hook ──
    hook_raw = data.get("hook") or {}
    hook_tail = {}
    for sudut, key in HOOK_SUDUT_KEYS.items():
        hook_tail[sudut] = _load_dia_dict(hook_raw.get(key), f"hook.{key}", errors)
    try:
        bend_factor = _norm_int(hook_raw.get("diameter_bengkok_faktor"),
                                "diameter_bengkok_faktor", "hook", allow_zero=True)
    except ConfigError as e:
        errors.append(str(e))
        bend_factor = 4

    # ── sengkang ──
    sk_raw = data.get("sengkang") or {}
    try:
        faktor = _norm_float(sk_raw.get("zona_tumpuan_faktor"),
                             "zona_tumpuan_faktor", "sengkang")
        jarak_pertama = _norm_int(sk_raw.get("jarak_sengkang_pertama_mm"),
                                  "jarak_sengkang_pertama_mm", "sengkang", allow_zero=True)
    except ConfigError as e:
        errors.append(str(e))
        faktor, jarak_pertama = 0.25, 50
    if not (0.0 <= faktor <= 0.5):
        errors.append(f"sengkang.zona_tumpuan_faktor = {faktor} harus 0-0.5")
    sengkang_cfg = SengkangConfig(zona_tumpuan_faktor=faktor,
                                  jarak_sengkang_pertama_mm=jarak_pertama)

    # ── optimizer ──
    opt_raw = data.get("optimizer") or {}
    try:
        max_pola = _norm_int(opt_raw.get("max_pola", 8), "max_pola", "optimizer")
    except ConfigError as e:
        errors.append(str(e))
        max_pola = 8
    batasi = opt_raw.get("batasi_pola", True)
    if not isinstance(batasi, bool):
        errors.append(f"optimizer.batasi_pola harus boolean, dapat {batasi!r}")
        batasi = True
    optimizer_cfg = OptimizerConfig(max_pola=max_pola, batasi_pola=batasi)

    return ProjectConfig(
        nama=nama, kode=kode, sumber=sumber, stok=stok, cover=cover,
        ld=ld, lap=lap, hook_tail=hook_tail, bend_factor=bend_factor,
        unit_weight=uw, sengkang_cfg=sengkang_cfg, warnings=warnings,
        optimizer=optimizer_cfg)


def _load_dia_dict(raw, path, errors) -> dict:
    """Baca dict {dia: nilai}, normalisasi key ke int."""
    out = {}
    if not isinstance(raw, dict):
        if raw is not None:
            errors.append(f"{path}: harus berupa mapping per diameter")
        return out
    for k, v in raw.items():
        try:
            dia = _norm_dia(k)
        except ConfigError as e:
            errors.append(f"{path}: {e}")
            continue
        out[dia] = v
    return out


# ── templates ───────────────────────────────────────────────
def load_templates(path) -> dict[str, ElementTemplate]:
    """Load config/templates.yaml → {nama_template: ElementTemplate}."""
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"Config template tidak ditemukan: {path}")
    with open(path) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: template harus berupa mapping")

    errors: list[str] = []
    templates: dict[str, ElementTemplate] = {}
    for tipe, items in data.items():
        if tipe not in ALLOWED_ALOKASI_TIPES:
            errors.append(f"template.{tipe}: tipe elemen '{tipe}' belum didukung "
                          f"(hanya: {', '.join(ALLOWED_ALOKASI_TIPES)})")
            continue
        if not isinstance(items, dict):
            errors.append(f"template.{tipe}: harus mapping nama -> definisi")
            continue
        for nama, tpl in items.items():
            try:
                templates[nama] = _parse_template(tipe, nama, tpl)
            except ConfigError as e:
                errors.append(str(e))
    if errors:
        raise ConfigError(
            "Config template tidak lengkap.\n\n" + "\n\n".join(errors) +
            "\n\nPerbaiki config/templates.yaml lalu jalankan ulang.")
    return templates


def _parse_template(tipe, nama, tpl) -> ElementTemplate:
    if not isinstance(tpl, dict):
        raise ConfigError(f"template.{tipe}.{nama}: definisi harus mapping")
    b = _norm_int(tpl.get("b_mm"), "b_mm", f"template.{tipe}.{nama}")
    h = _norm_int(tpl.get("h_mm"), "h_mm", f"template.{tipe}.{nama}")
    deskripsi = str(tpl.get("deskripsi", ""))

    tulangan_raw = tpl.get("tulangan") or []
    tulangan = []
    for i, t in enumerate(tulangan_raw):
        path = f"template.{tipe}.{nama}.tulangan[{i}]"
        dia = _norm_dia(t.get("dia"))
        posisi = str(t.get("posisi", ""))
        if not posisi:
            raise ConfigError(f"{path}: posisi wajib (atas/bawah/pinggang)")
        try:
            jumlah = _norm_int(t.get("jumlah"), "jumlah", path)
        except ConfigError as e:
            raise ConfigError(str(e))
        tulangan.append(TemplateTulangan(
            posisi=posisi, dia=dia, jumlah=jumlah,
            tumpuan_kedua_ujung=bool(t.get("tumpuan_kedua_ujung", True))))

    sk = tpl.get("sengkang")
    if sk is None:
        raise ConfigError(f"template.{tipe}.{nama}: sengkang wajib")
    sk_path = f"template.{tipe}.{nama}.sengkang"
    sk_dia = _norm_dia(sk.get("dia"))
    sk_tt = _norm_int(sk.get("jarak_tumpuan_mm"), "jarak_tumpuan_mm", sk_path)
    sk_tl = _norm_int(sk.get("jarak_lapangan_mm"), "jarak_lapangan_mm", sk_path)
    sk_kaki = _norm_int(sk.get("kaki"), "kaki", sk_path)
    sk_hook = sk.get("hook_sudut")
    try:
        sk_hook = int(sk_hook)
    except (TypeError, ValueError):
        raise ConfigError(f"{sk_path}.hook_sudut: harus angka (90 atau 135), dapat {sk_hook!r}")
    if sk_hook not in ALLOWED_SENGKANG_HOOK:
        raise ConfigError(f"{sk_path}.hook_sudut: hanya 90 atau 135, dapat {sk_hook}")

    return ElementTemplate(
        nama=nama, tipe=tipe, deskripsi=deskripsi, b_mm=b, h_mm=h,
        tulangan=tuple(tulangan),
        sengkang=TemplateSengkang(dia=sk_dia, jarak_tumpuan_mm=sk_tt,
                                  jarak_lapangan_mm=sk_tl, kaki=sk_kaki,
                                  hook_sudut=sk_hook))


# ── validasi silang config ↔ template (spec §5.1) ───────────
def validate_config_templates(cfg: ProjectConfig,
                              templates: dict[str, ElementTemplate],
                              errors: list[str]) -> None:
    """Kumpulkan semua error kelengkapan silang config ↔ template."""
    for nama, tpl in templates.items():
        # sanity dimensi
        for zona in ("balok",):
            cover = cfg.cover.get(zona)
            if cover is not None:
                if cover * 2 >= tpl.b_mm:
                    errors.append(
                        f"ERROR: template '{nama}' selimut_beton×2 ({cover * 2} mm) "
                        f">= b_mm ({tpl.b_mm} mm) — sengkang jadi negatif")
                if cover * 2 >= tpl.h_mm:
                    errors.append(
                        f"ERROR: template '{nama}' selimut_beton×2 ({cover * 2} mm) "
                        f">= h_mm ({tpl.h_mm} mm) — sengkang jadi negatif")
        if tpl.sengkang.jarak_tumpuan_mm > tpl.sengkang.jarak_lapangan_mm:
            cfg.warnings.append(
                f"WARNING: template '{nama}' jarak_tumpuan_mm "
                f"({tpl.sengkang.jarak_tumpuan_mm}) > jarak_lapangan_mm "
                f"({tpl.sengkang.jarak_lapangan_mm}) — biasanya terbalik")

        # diameter tulangan — cek ld + unit_weight (tulangan lurus TIDAK butuh hook tail)
        for i, t in enumerate(tpl.tulangan):
            path = f"template '{nama}.tulangan[{i}]'"
            _cek_diameter(cfg, t.dia, path, errors)
        # diameter sengkang — cek ld + unit_weight + hook tail sesuai hook_sudut
        _cek_diameter(cfg, tpl.sengkang.dia,
                      f"template '{nama}.sengkang'", errors,
                      tpl.sengkang.hook_sudut)


def _cek_diameter(cfg, dia, path, errors, hook_sudut=None):
    if dia not in cfg.ld:
        errors.append(
            f"  Diameter {dia} dipakai di {path}\n"
            f"  tapi tidak ada di config.panjang_penyaluran_mm")
    if dia not in cfg.unit_weight:
        errors.append(
            f"  Diameter {dia} dipakai di {path}\n"
            f"  tapi tidak ada di config.unit_weight_kg_per_m")
    if hook_sudut is not None:
        tail = cfg.hook_tail.get(hook_sudut, {})
        if dia not in tail:
            errors.append(
                f"  Diameter {dia} dipakai di {path}\n"
                f"  dengan hook_sudut {hook_sudut}, tapi tidak ada di "
                f"config.hook.{HOOK_SUDUT_KEYS[hook_sudut]}")


def load_all(config_dir) -> tuple[ProjectConfig, dict[str, ElementTemplate]]:
    """Load project + templates, validasi silang, kumpulkan semua error.

    Raises ConfigError dengan daftar LENGKAP error kalau ada yang gagal.
    """
    config_dir = Path(config_dir)
    cfg = load_project_config(config_dir / "project.yaml")
    templates = load_templates(config_dir / "templates.yaml")

    errors: list[str] = []
    validate_config_templates(cfg, templates, errors)
    if errors:
        raise ConfigError(
            "Config tidak lengkap.\n\n" + "\n\n".join(errors) +
            "\n\nPerbaiki config lalu jalankan ulang.")
    return cfg, templates
