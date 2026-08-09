"""Config loader — baca & validasi config YAML (F0).

Aturan project:
- Tidak ada nilai teknis hardcoded di kode. Semua dari config.
- Fail loud: kalau config tidak lengkap, kumpulkan SEMUA error
  sekaligus lalu raise — jangan berhenti di error pertama.
- Config immutable setelah load (frozen dataclass).
"""

from datetime import datetime
from pathlib import Path

import yaml

from models import ConfigError, ElementTemplate, OptimizerConfig, \
    PlatConfig, ProjectConfig, SengkangConfig, SourceInfo, StockConfig, \
    TOOL_VERSION, TemplateSengkang, TemplateTulangan

ALLOWED_ALOKASI_TIPES = ("balok", "kolom", "plat")  # 13-SPEC F8 — plat ketiga
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

    # ── bend deduction per sudut (PATCH-06 §1.5) ──
    bend_faktor = {}
    bd_raw = hook_raw.get("bend_deduction_faktor") or {}
    if bd_raw:
        if not isinstance(bd_raw, dict):
            errors.append("hook.bend_deduction_faktor: harus mapping sudut -> "
                          "kelipatan diameter")
        else:
            for sudut, faktor in bd_raw.items():
                try:
                    s = int(sudut)
                    f = _norm_int(faktor, f"{sudut}", "hook.bend_deduction_faktor",
                                  allow_zero=True)
                except ConfigError as e:
                    errors.append(str(e))
                    continue
                bend_faktor[s] = f

    # ── sengkang ──
    sk_raw = data.get("sengkang") or {}
    zona_raw = data.get("sengkang_zona") or {}
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
    metode = sk_raw.get("metode_hitung", "kontinyu")
    if metode not in ("kontinyu", "per_zona"):
        errors.append(f"sengkang.metode_hitung harus 'kontinyu' atau 'per_zona', "
                      f"dapat {metode!r}")
        metode = "kontinyu"
    # 12-SPEC §4: zona sengkang — "rasio" (balok) | "panjang" (kolom)
    zona_metode = str(zona_raw.get("metode", "rasio"))
    if zona_metode not in ("rasio", "panjang"):
        errors.append(f"sengkang_zona.metode harus 'rasio' atau 'panjang', "
                      f"dapat {zona_metode!r}")
        zona_metode = "rasio"
    lo_expr = str(zona_raw.get("lo", ""))
    if zona_metode == "panjang" and not lo_expr.strip():
        errors.append(
            "sengkang_zona.lo wajib diisi utk metode 'panjang' "
            "(ekspresi panjang zona pengekangan, mis. 'max(h, L/6, 450)').")
    if lo_expr.strip():
        from shapes import parse_ekspresi
        try:
            parse_ekspresi(lo_expr, "sengkang_zona.lo")
        except ConfigError as e:
            errors.append(str(e))
    sengkang_cfg = SengkangConfig(zona_tumpuan_faktor=faktor,
                                  jarak_sengkang_pertama_mm=jarak_pertama,
                                  metode_hitung=metode,
                                  zona_metode=zona_metode,
                                  zona_lo_ekspresi=lo_expr)

    # ── optimizer ──
    opt_raw = data.get("optimizer") or {}
    try:
        max_pola = _norm_int(opt_raw.get("max_pola", 8), "max_pola", "optimizer")
    except ConfigError as e:
        errors.append(str(e))
        max_pola = 8
    batasi = opt_raw.get("batasi_pola", False)
    if batasi is True:
        errors.append(
            "optimizer.batasi_pola=true ditolak (PATCH-01): pembatasan pola "
            "dihapus dari optimizer. Pola 'SISA/CAMPURAN' tidak bisa dieksekusi "
            "dan menyembunyikan batang tanpa pola. Set batasi_pola: false — "
            "output pola yang panjang tapi benar lebih baik daripada daftar "
            "pendek berisi instruksi mustahil.")
    elif not isinstance(batasi, bool):
        errors.append(f"optimizer.batasi_pola harus boolean, dapat {batasi!r}")
        batasi = False
    optimizer_cfg = OptimizerConfig(max_pola=max_pola, batasi_pola=False)

    # ── lap splice metode (11-SPEC §3) ──
    lap_raw = data.get("lap_splice") or {}
    lap_metode = str(lap_raw.get("metode", "sisa_di_ujung"))
    if lap_metode not in ("sisa_di_ujung", "bagi_rata", "berselang"):
        errors.append(
            f"lap_splice.metode harus 'sisa_di_ujung', 'bagi_rata', atau "
            f"'berselang', dapat {lap_metode!r}")
        lap_metode = "sisa_di_ujung"
    try:
        lap_offset = _norm_int(lap_raw.get("berselang_offset_mm", 0),
                               "berselang_offset_mm", "lap_splice",
                               allow_zero=True)
    except ConfigError as e:
        errors.append(str(e))
        lap_offset = 0

    # ── plat (13-SPEC §3) ──
    plat_raw = data.get("plat") or {}
    try:
        plat_tepi = _norm_int(plat_raw.get("jarak_tepi_mm", 50),
                              "jarak_tepi_mm", "plat")
    except ConfigError as e:
        errors.append(str(e))
        plat_tepi = 50
    plat_metode = str(plat_raw.get("metode_hitung", "floor_plus_1"))
    if plat_metode not in ("floor_plus_1", "ceil"):
        errors.append(
            f"plat.metode_hitung harus 'floor_plus_1' atau 'ceil', "
            f"dapat {plat_metode!r}")
        plat_metode = "floor_plus_1"
    plat_cfg = PlatConfig(jarak_tepi_mm=plat_tepi,
                          metode_hitung=plat_metode)

    # ── koreksi bengkokan (spec 02 §3.1) — default OFF ──
    koreksi_bend = hook_raw.get("koreksi_bengkokan_aktif", False)
    if not isinstance(koreksi_bend, bool):
        errors.append(f"hook.koreksi_bengkokan_aktif harus boolean, dapat {koreksi_bend!r}")
        koreksi_bend = False
    if koreksi_bend:
        warnings.append(
            "WARNING: koreksi_bengkokan AKTIF — besaran koreksi belum diverifikasi "
            "terhadap BBS asli (F4). Pastikan angka tail dari gambar belum termasuk "
            "koreksi, kalau ragu matikan.")

    # ── konvensi hook (09-SPEC §8) — asuransi verifikasi tertunda ──
    hook_konvensi = str(hook_raw.get("konvensi", "tail_terpisah"))
    if hook_konvensi not in ("tail_terpisah", "hook_total"):
        errors.append(
            f"hook.konvensi harus 'tail_terpisah' atau 'hook_total', "
            f"dapat {hook_konvensi!r}")
        hook_konvensi = "tail_terpisah"
    if hook_konvensi == "hook_total":
        warnings.append(
            "WARNING: hook.konvensi = hook_total — panjang hook_tail sudah "
            "termasuk lengkungan, bend deduction TIDAK dikurangi. Verifikasi "
            "ke BBS asli sebelum memakai (09-SPEC §8).")

    return ProjectConfig(
        nama=nama, kode=kode, sumber=sumber, stok=stok, cover=cover,
        ld=ld, lap=lap, hook_tail=hook_tail, bend_factor=bend_factor,
        bend_faktor=bend_faktor, unit_weight=uw, sengkang_cfg=sengkang_cfg,
        warnings=warnings, optimizer=optimizer_cfg,
        koreksi_bend_aktif=koreksi_bend, hook_konvensi=hook_konvensi,
        lap_metode=lap_metode, lap_berselang_offset_mm=lap_offset,
        plat_cfg=plat_cfg)


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
        if tipe == "_meta":
            continue  # metadata file (F3.6) — bukan template elemen
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
    # plat tidak punya b/h (13-SPEC) — izinkan 0
    b = _norm_int(tpl.get("b_mm", 0), "b_mm", f"template.{tipe}.{nama}",
                  allow_zero=tipe == "plat")
    h = _norm_int(tpl.get("h_mm", 0), "h_mm", f"template.{tipe}.{nama}",
                  allow_zero=tipe == "plat")
    deskripsi = str(tpl.get("deskripsi", ""))
    # 12-SPEC §3: label & bantuan dimensi utama — default balok
    label_L = str(tpl.get("label_L", "Bentang bersih"))
    bantuan_L = str(tpl.get(
        "bantuan_L", "Muka ke muka tumpuan, bukan as-ke-as."))

    tulangan_raw = tpl.get("tulangan") or []
    tulangan = []
    for i, t in enumerate(tulangan_raw):
        path = f"template.{tipe}.{nama}.tulangan[{i}]"
        dia = _norm_dia(t.get("dia"))
        posisi = str(t.get("posisi", ""))
        if not posisi:
            raise ConfigError(f"{path}: posisi wajib (atas/bawah/pinggang)")
        # 13-SPEC §3.1: tepat satu dari jumlah / jarak_mm (plat)
        ada_jumlah = t.get("jumlah") is not None
        ada_jarak = t.get("jarak_mm") is not None
        if ada_jumlah == ada_jarak:
            raise ConfigError(
                f"{path}: tepat satu dari 'jumlah' atau 'jarak_mm' harus "
                f"ada (dua-duanya atau nol = salah). Plat memakai jarak_mm, "
                f"balok/kolom memakai jumlah.")
        if ada_jumlah:
            try:
                jumlah = _norm_int(t.get("jumlah"), "jumlah", path)
            except ConfigError as e:
                raise ConfigError(str(e))
            jarak_mm = 0
        else:
            jumlah = 0
            try:
                jarak_mm = _norm_int(t.get("jarak_mm"), "jarak_mm", path)
            except ConfigError as e:
                raise ConfigError(str(e))
        # 13-SPEC §3.1: arah (plat) — "X" | "Y"
        arah = str(t.get("arah", "")).upper()
        if arah not in ("", "X", "Y"):
            raise ConfigError(
                f"{path}.arah: harus 'X' atau 'Y' (plat), dapat {arah!r}")
        # 13-SPEC §4: zona — default 1 (membentang penuh)
        try:
            zona = _norm_int(t.get("zona", 1), "zona", path)
        except ConfigError as e:
            raise ConfigError(str(e))
        # 10-SPEC §5: shape + vars — default "01" batang lurus.
        # Migrasi §6: template lama (tanpa vars) mereproduksi perilaku asli
        # tulangan utama = bentang + n_ujung×Ld (tumpuan_kedua_ujung).
        shape = str(t.get("shape", "01"))
        vars_ = t.get("vars")
        if vars_ is None:
            n_ujung = 2 if t.get("tumpuan_kedua_ujung", True) else 1
            vars_ = {"L": f"L + {n_ujung}*Ld"}
        vars_ = dict(vars_)
        # 11-SPEC §4: zona sambung terlarang — [(dari, sampai)] rasio bentang
        zona_sambung = []
        for z in (t.get("zona_sambung_terlarang") or []):
            try:
                zona_sambung.append((float(z.get("dari")), float(z.get("sampai"))))
            except (TypeError, ValueError, AttributeError):
                raise ConfigError(
                    f"{path}.zona_sambung_terlarang: tiap zona harus "
                    f"{{dari, sampai}} rasio (0-1)")
        tulangan.append(TemplateTulangan(
            posisi=posisi, dia=dia, jumlah=jumlah,
            tumpuan_kedua_ujung=bool(t.get("tumpuan_kedua_ujung", True)),
            shape=shape, vars=vars_, zona_sambung_terlarang=tuple(zona_sambung),
            arah=arah, jarak_mm=jarak_mm, zona=zona))

    # 12-SPEC §2: sengkang jadi DAFTAR; objek tunggal (lama) → bungkus
    sk_raw = tpl.get("sengkang")
    if sk_raw is None:
        raise ConfigError(f"template.{tipe}.{nama}: sengkang wajib")
    sk_list = sk_raw if isinstance(sk_raw, list) else [sk_raw]
    sengkang = []
    sk_path0 = f"template.{tipe}.{nama}.sengkang"
    # kelompok pertama jadi sumber jarak default utk yang tidak diisi
    jarak_default = None
    for si, sk in enumerate(sk_list):
        sk_path = f"{sk_path0}[{si}]"
        if not isinstance(sk, dict):
            raise ConfigError(f"{sk_path}: definisi sengkang harus mapping")
        # 12-SPEC §6: spiral ditolak — fitur belum ada, jangan hasil salah
        sk_shape = str(sk.get("shape", "51"))
        if sk_shape in ("spiral", "SPIRAL"):
            raise ConfigError(
                f"{sk_path}: shape 'spiral' (kolom bulat) belum didukung. "
                f"Tunda sampai fase shape spiral tersedia.")
        sk_dia = _norm_dia(sk.get("dia"))
        sk_kaki = _norm_int(sk.get("kaki"), "kaki", sk_path)
        sk_hook = sk.get("hook_sudut")
        try:
            sk_hook = int(sk_hook)
        except (TypeError, ValueError):
            raise ConfigError(
                f"{sk_path}.hook_sudut: harus angka (90 atau 135), dapat {sk_hook!r}")
        if sk_hook not in ALLOWED_SENGKANG_HOOK:
            raise ConfigError(f"{sk_path}.hook_sudut: hanya 90 atau 135, dapat {sk_hook}")
        # jarak: kelompok kedua+ mewarisi dari pertama kalau kosong (§2)
        sk_tt_raw = sk.get("jarak_tumpuan_mm")
        sk_tl_raw = sk.get("jarak_lapangan_mm")
        if si > 0 and jarak_default and sk_tt_raw is None:
            sk_tt_raw = jarak_default[0]
        if si > 0 and jarak_default and sk_tl_raw is None:
            sk_tl_raw = jarak_default[1]
        sk_tt = _norm_int(sk_tt_raw, "jarak_tumpuan_mm", sk_path)
        sk_tl = _norm_int(sk_tl_raw, "jarak_lapangan_mm", sk_path)
        if si == 0:
            jarak_default = (sk_tt, sk_tl)
        # PATCH-06 §1.6: bengkokan per sudut — opsional
        bengkokan = {}
        bk_raw = sk.get("bengkokan") or {}
        if bk_raw:
            if not isinstance(bk_raw, dict):
                raise ConfigError(
                    f"{sk_path}.bengkokan: harus mapping sudut -> jumlah")
            for sudut, n in bk_raw.items():
                try:
                    bengkokan[int(sudut)] = _norm_int(n, str(sudut),
                                                      f"{sk_path}.bengkokan")
                except ConfigError as e:
                    raise ConfigError(str(e))
        jumlah_set = _norm_int(sk.get("jumlah_per_set", 1),
                               "jumlah_per_set", sk_path)
        sengkang.append(TemplateSengkang(
            dia=sk_dia, jarak_tumpuan_mm=sk_tt, jarak_lapangan_mm=sk_tl,
            kaki=sk_kaki, hook_sudut=sk_hook,
            nama=str(sk.get("nama", f"sengkang {si + 1}")),
            bengkokan=bengkokan, shape=sk_shape,
            jumlah_per_set=jumlah_set))

    return ElementTemplate(
        nama=nama, tipe=tipe, deskripsi=deskripsi, b_mm=b, h_mm=h,
        tulangan=tuple(tulangan), sengkang=tuple(sengkang),
        label_L=label_L, bantuan_L=bantuan_L)


# ── validasi silang config ↔ template (spec §5.1) ───────────
def validate_config_templates(cfg: ProjectConfig,
                              templates: dict[str, ElementTemplate],
                              errors: list[str]) -> None:
    """Kumpulkan semua error kelengkapan silang config ↔ template."""
    for nama, tpl in templates.items():
        # sanity dimensi — zona cover sesuai tipe elemen (balok/kolom);
        # plat tidak punya b/h (13-SPEC) → skip
        for zona in (tpl.tipe,):
            cover = cfg.cover.get(zona)
            if cover is not None and tpl.tipe != "plat":
                if cover * 2 >= tpl.b_mm:
                    errors.append(
                        f"ERROR: template '{nama}' selimut_beton×2 ({cover * 2} mm) "
                        f">= b_mm ({tpl.b_mm} mm) — sengkang jadi negatif")
                if cover * 2 >= tpl.h_mm:
                    errors.append(
                        f"ERROR: template '{nama}' selimut_beton×2 ({cover * 2} mm) "
                        f">= h_mm ({tpl.h_mm} mm) — sengkang jadi negatif")

        # diameter tulangan — cek ld + unit_weight (tulangan lurus TIDAK butuh hook tail)
        for i, t in enumerate(tpl.tulangan):
            path = f"template '{nama}.tulangan[{i}]'"
            _cek_diameter(cfg, t.dia, path, errors)
        # diameter sengkang (daftar, 12-SPEC §2) — cek tiap kelompok
        for si, sk in enumerate(tpl.sengkang):
            if sk.jarak_tumpuan_mm > sk.jarak_lapangan_mm:
                cfg.warnings.append(
                    f"WARNING: template '{nama}' sengkang[{si}] jarak_tumpuan_mm "
                    f"({sk.jarak_tumpuan_mm}) > jarak_lapangan_mm "
                    f"({sk.jarak_lapangan_mm}) — biasanya terbalik")
            _cek_diameter(cfg, sk.dia,
                          f"template '{nama}.sengkang[{si}]'", errors,
                          sk.hook_sudut)

        # 10-SPEC §8: shape dipakai template tapi tidak ada di shapes.yaml.
        # Skip kalau cfg.shapes kosong — pemanggil langsung (test lama, jalur
        # legacy) tidak load shapes; load_all/load_layered selalu mengisinya.
        if cfg.shapes:
            for i, t in enumerate(tpl.tulangan):
                if t.shape not in cfg.shapes:
                    errors.append(
                        f"  Shape '{t.shape}' dipakai di template '{nama}."
                        f"tulangan[{i}]'\n"
                        f"  tapi tidak ada di shapes.yaml. "
                        f"Shape yang ada: {', '.join(sorted(cfg.shapes))}")
            for si, sk in enumerate(tpl.sengkang):
                if sk.shape not in cfg.shapes:
                    errors.append(
                        f"  Shape '{sk.shape}' dipakai di template "
                        f"'{nama}.sengkang[{si}]'\n"
                        f"  tapi tidak ada di shapes.yaml. "
                        f"Shape yang ada: {', '.join(sorted(cfg.shapes))}")
                # §8: jumlah bengkokan > jumlah segmen + 1 → warning
                sh = cfg.shapes.get(sk.shape)
                if sh and sh.segmen:
                    n_b = sum(b.jumlah for b in sh.bengkokan)
                    if n_b > len(sh.segmen) + 1:
                        cfg.warnings.append(
                            f"WARNING: shape '{sk.shape}' dipakai template "
                            f"'{nama}.sengkang[{si}]': {n_b} bengkokan > "
                            f"{len(sh.segmen)} segmen — biasanya salah hitung.")


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
    import dataclasses
    from shapes import load_shapes, tulis_shapes_bawaan

    config_dir = Path(config_dir)
    cfg = load_project_config(config_dir / "project.yaml")
    templates = load_templates(config_dir / "templates.yaml")

    # 10-SPEC §6: shapes.yaml bawaan kalau belum ada — SEBELUM validasi
    # (validasi silang template↔shape butuh daftar shape).
    shapes_p = tulis_shapes_bawaan(config_dir / "shapes.yaml")
    shapes = load_shapes(shapes_p)
    cfg = dataclasses.replace(cfg, shapes=shapes)

    errors: list[str] = []
    validate_config_templates(cfg, templates, errors)
    if errors:
        raise ConfigError(
            "Config tidak lengkap.\n\n" + "\n\n".join(errors) +
            "\n\nPerbaiki config lalu jalankan ulang.")
    return cfg, templates


# ── multi-proyek berlapis (08-SPEC-config-berlapis) ────────
# Struktur baru:
#   config/projects/{kode}/project.yaml      — nilai umum + default teknis
#   config/projects/{kode}/templates.yaml    — template elemen (milik proyek)
#   config/projects/{kode}/drawings/{g}.yaml — override per gambar + metadata
#
# Resolusi: deep merge default proyek ← override gambar. Yang tidak disebut
# di gambar = diwarisi. Hasil = ProjectConfig biasa → bbs/optimizer tak berubah.


def _deep_merge_dict(base: dict, ovr: dict) -> dict:
    """Deep merge per key, BUKAN replace per grup."""
    out = dict(base or {})
    for k, v in (ovr or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge_dict(out[k], v)
        else:
            out[k] = v
    return out


def resolve_config(cfg: ProjectConfig, drawing_override: dict) -> ProjectConfig:
    """Gabungkan default proyek dengan override gambar (deep merge)."""
    import dataclasses
    ovr = drawing_override or {}
    cfg_d = {
        "stok": {"panjang_batang_mm": cfg.stok.panjang_batang_mm,
                 "kerf_mm": cfg.stok.kerf_mm,
                 "sisa_min_simpan_mm": cfg.stok.sisa_min_simpan_mm},
        "selimut_beton_mm": dict(cfg.cover),
        "panjang_penyaluran_mm": dict(cfg.ld),
        "lap_splice_mm": dict(cfg.lap),
        "unit_weight_kg_per_m": dict(cfg.unit_weight),
        "hook": {"tail_135_mm": dict(cfg.hook_tail.get(135, {})),
                 "tail_90_mm": dict(cfg.hook_tail.get(90, {})),
                 "diameter_bengkok_faktor": cfg.bend_factor,
                 "koreksi_bengkokan_aktif": cfg.koreksi_bend_aktif,
                 "konvensi": cfg.hook_konvensi,
                 "bend_deduction_faktor": dict(cfg.bend_faktor)},
        "sengkang": {"zona_tumpuan_faktor": cfg.sengkang_cfg.zona_tumpuan_faktor,
                     "jarak_sengkang_pertama_mm":
                         cfg.sengkang_cfg.jarak_sengkang_pertama_mm,
                     "metode_hitung": cfg.sengkang_cfg.metode_hitung,
                     "zona_metode": cfg.sengkang_cfg.zona_metode,
                     "zona_lo_ekspresi": cfg.sengkang_cfg.zona_lo_ekspresi},
        "lap_splice": {"metode": cfg.lap_metode,
                       "berselang_offset_mm": cfg.lap_berselang_offset_mm},
        "plat": {"jarak_tepi_mm": cfg.plat_cfg.jarak_tepi_mm,
                 "metode_hitung": cfg.plat_cfg.metode_hitung},
    }
    merged = _deep_merge_dict(cfg_d, ovr)

    # hook_tail: key 'tail_135_mm'/'tail_90_mm' → sudut int
    hook_tail = {}
    for s, m in merged["hook"].items():
        if isinstance(m, dict):
            sudut = 135 if "135" in str(s) else 90
            hook_tail[sudut] = {int(d): int(v) for d, v in m.items()}

    sk = cfg.sengkang_cfg
    m = merged["sengkang"]
    if (m.get("zona_tumpuan_faktor") != sk.zona_tumpuan_faktor
            or m.get("jarak_sengkang_pertama_mm") != sk.jarak_sengkang_pertama_mm
            or m.get("metode_hitung") != sk.metode_hitung
            or m.get("zona_metode") != sk.zona_metode
            or m.get("zona_lo_ekspresi") != sk.zona_lo_ekspresi):
        sk = SengkangConfig(zona_tumpuan_faktor=m["zona_tumpuan_faktor"],
                            jarak_sengkang_pertama_mm=m["jarak_sengkang_pertama_mm"],
                            metode_hitung=m.get("metode_hitung", "kontinyu"),
                            zona_metode=m.get("zona_metode", "rasio"),
                            zona_lo_ekspresi=m.get("zona_lo_ekspresi", ""))
    return dataclasses.replace(
        cfg,
        cover={int(k) if str(k).isdigit() else k: v
               for k, v in merged["selimut_beton_mm"].items()},
        ld={int(k): int(v) for k, v in merged["panjang_penyaluran_mm"].items()},
        lap={int(k): int(v) for k, v in merged["lap_splice_mm"].items()},
        unit_weight={int(k): float(v)
                     for k, v in merged["unit_weight_kg_per_m"].items()},
        hook_tail=hook_tail,
        bend_factor=int(merged["hook"].get("diameter_bengkok_faktor", 4)),
        bend_faktor={int(k): int(v) for k, v in
                     (merged["hook"].get("bend_deduction_faktor") or {}).items()},
        koreksi_bend_aktif=bool(merged["hook"].get("koreksi_bengkokan_aktif", False)),
        hook_konvensi=str(merged["hook"].get("konvensi", "tail_terpisah")),
        sengkang_cfg=sk,
        stok=StockConfig(panjang_batang_mm=int(merged["stok"]["panjang_batang_mm"]),
                         kerf_mm=int(merged["stok"]["kerf_mm"]),
                         sisa_min_simpan_mm=int(merged["stok"]["sisa_min_simpan_mm"])),
        lap_metode=str((merged.get("lap_splice") or {}).get("metode",
                                                            cfg.lap_metode)),
        lap_berselang_offset_mm=int(
            (merged.get("lap_splice") or {}).get("berselang_offset_mm",
                                                 cfg.lap_berselang_offset_mm)),
        plat_cfg=PlatConfig(
            jarak_tepi_mm=int((merged.get("plat") or {}).get(
                "jarak_tepi_mm", cfg.plat_cfg.jarak_tepi_mm)),
            metode_hitung=str((merged.get("plat") or {}).get(
                "metode_hitung", cfg.plat_cfg.metode_hitung)),
        ),
    )


def load_drawing(projects_dir, proyek, gambar) -> dict:
    """Baca drawing {g}.yaml → dict (override + metadata). Raises ConfigError."""
    import yaml
    p = Path(projects_dir) / proyek / "drawings" / f"{gambar}.yaml"
    if not p.exists():
        raise ConfigError(f"Gambar '{gambar}' tidak ada di proyek '{proyek}'.")
    d = yaml.safe_load(p.read_text()) or {}
    d.pop("_meta", None)
    return d


def list_drawings(projects_dir, proyek) -> list[dict]:
    """Daftar gambar: kode, nama, revisi, tanggal, jumlah override."""
    import yaml
    ddir = Path(projects_dir) / proyek / "drawings"
    out = []
    if not ddir.exists():
        return out
    for p in sorted(ddir.glob("*.yaml")):
        d = yaml.safe_load(p.read_text()) or {}
        ovr = d.get("override", {}) or {}
        out.append({
            "kode": p.stem,
            "nama": d.get("nama", p.stem),
            "revisi": d.get("revisi", ""),
            "tanggal": d.get("tanggal", ""),
            "catatan": d.get("catatan", ""),
            "n_override": sum(len(v) for v in ovr.values()
                              if isinstance(v, dict)),
        })
    return out


def load_layered(projects_dir, proyek, gambar):
    """Load proyek + resolusi gambar → (ProjectConfig, templates, drawing_info).

    Validasi dijalankan pada HASIL RESOLUSI — pesan menyebut gambar.
    """
    import yaml
    from pathlib import Path as _P
    base = _P(projects_dir) / proyek
    proj_f = base / "project.yaml"
    tpl_f = base / "templates.yaml"
    if not proj_f.exists() or not tpl_f.exists():
        raise ConfigError(f"Proyek '{proyek}' tidak lengkap (project.yaml/templates.yaml).")
    cfg = load_project_config(proj_f)
    templates = load_templates(tpl_f)

    # 10-SPEC §6: shapes.yaml per proyek — bawaan kalau belum ada (SEBELUM
    # validasi — validasi silang template↔shape butuh daftar shape).
    import dataclasses
    from shapes import load_shapes, tulis_shapes_bawaan
    shapes_p = tulis_shapes_bawaan(base / "shapes.yaml")
    shapes = load_shapes(shapes_p)
    cfg = dataclasses.replace(cfg, shapes=shapes)

    drawing = load_drawing(projects_dir, proyek, gambar)
    cfg_res = resolve_config(cfg, drawing.get("override"))

    errors: list[str] = []
    validate_config_templates(cfg_res, templates, errors)
    if errors:
        rev = drawing.get("revisi", "")
        raise ConfigError(
            f"ERROR: Config gambar {gambar} ({rev}) tidak lengkap.\n\n"
            + "\n\n".join(e.replace("ERROR: ", "")
                          for e in errors)
            + f"\n\nDiameter yang kurang bisa diisi di override gambar "
              f"{gambar} atau di default proyek {proyek}.")

    info = {"kode": gambar, "nama": drawing.get("nama", gambar),
            "revisi": drawing.get("revisi", ""),
            "tanggal": drawing.get("tanggal", ""),
            "catatan": drawing.get("catatan", "")}
    return cfg_res, templates, info


def migrate_legacy_layered(config_dir):
    """Migrasi config/project.yaml → projects/{kode}/ (berlapis) sekali.

    - project.yaml → projects/{kode}/project.yaml
    - templates.yaml → projects/{kode}/templates.yaml
    - drawings/{kode_gambar}.yaml — kode gambar diekstrak dari sumber.dokumen
      (mis. "Gambar Struktur GS-01" → kode GS-01, nama "Gambar Struktur").
      Kalau pola kode tidak ketemu → kode "MIGRASI" + _meta.catatan_migrasi.
    """
    import re as _re
    import yaml
    config_dir = Path(config_dir)
    proj_file = config_dir / "project.yaml"
    if not proj_file.exists():
        return False
    # cek sudah ada folder berlapis
    if any((config_dir / "projects").glob("*/project.yaml")):
        return False
    data = yaml.safe_load(proj_file.read_text())
    kode = str((data.get("proyek") or {}).get("kode", "PRJ-001"))
    if not kode or not all(c.isalnum() or c in "_-" for c in kode):
        kode = "PRJ-001"

    pdir = config_dir / "projects" / kode
    (pdir / "drawings").mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().replace(microsecond=0).isoformat() + "+00:00"
    meta = f"_meta:\n  dibuat_via: migrasi\n  dibuat_pada: {ts}\n"

    (pdir / "project.yaml").write_text(meta + proj_file.read_text())
    (pdir / "templates.yaml").write_text(meta +
        (config_dir / "templates.yaml").read_text())

    # gambar dari blok sumber — kode diekstrak dari sumber.dokumen
    sumber = data.get("sumber") or {}
    dokumen = str(sumber.get("dokumen", ""))
    gkode = _ekstrak_kode_gambar(dokumen)
    gnama = _ekstrak_nama_gambar(dokumen) or (gkode or "Migrasi otomatis")
    catatan_migrasi = ""
    if gkode is None:
        gkode = "MIGRASI"
        catatan_migrasi = ("Kode gambar tidak terdeteksi dari sumber.dokumen "
                           "— ganti manual dengan kode gambar yang benar.")
    drawing = {
        "kode": gkode,
        "nama": gnama,
        "revisi": str(sumber.get("revisi", "")),
        "tanggal": str(sumber.get("tanggal", "")),
        "catatan": str(sumber.get("catatan", "")),
        "override": {},
        "_meta": {"dibuat_via": "migrasi", "dibuat_pada": ts},
    }
    if catatan_migrasi:
        drawing["_meta"]["catatan_migrasi"] = catatan_migrasi
    (pdir / "drawings" / f"{gkode}.yaml").write_text(
        yaml.safe_dump(drawing, allow_unicode=True))
    return True


def _ekstrak_kode_gambar(dokumen: str):
    """Token berpola kode gambar (huruf-angka dengan hubung, mis. GS-01).

    Return kode uppercase atau None kalau tidak ketemu.
    """
    import re as _re
    if not dokumen:
        return None
    m = _re.search(r"\b([A-Za-z]{1,4}-\d{1,4})\b", dokumen)
    return m.group(1).upper() if m else None


def _ekstrak_nama_gambar(dokumen: str):
    """Nama gambar = bagian sebelum kode gambar, di-strip.

    "Gambar Struktur GS-01" → "Gambar Struktur". Return "" kalau kosong.
    """
    import re as _re
    if not dokumen:
        return ""
    m = _re.search(r"\b[A-Za-z]{1,4}-\d{1,4}\b", dokumen)
    if m:
        return dokumen[: m.start()].strip()
    return dokumen.strip()


def load_project(projects_dir, kode) -> tuple[ProjectConfig, dict[str, ElementTemplate]]:
    """Load satu proyek (config + templates) dengan validasi silang.

    Raises ConfigError kalau proyek tidak ada atau config tidak lengkap.
    """
    projects_dir = Path(projects_dir)
    cfg = load_project_config(projects_dir / "projects" / f"{kode}.yaml")
    templates = load_templates(projects_dir / "templates" / f"{kode}.yaml")

    errors: list[str] = []
    validate_config_templates(cfg, templates, errors)
    if errors:
        raise ConfigError(
            f"Proyek '{kode}' tidak lengkap.\n\n" + "\n\n".join(errors) +
            "\n\nPerbaiki config lalu jalankan ulang.")
    return cfg, templates


def list_projects(projects_dir) -> list[dict]:
    """Daftar proyek: kode, nama, sumber, jumlah template.

    Baca dua bentuk: folder berlapis (08) dan file flat (F3.6 legacy)."""
    projects_dir = Path(projects_dir)
    out = []
    seen = set()
    if not (projects_dir / "projects").exists():
        return out
    # folder berlapis: projects/{kode}/project.yaml
    for p in sorted((projects_dir / "projects").glob("*/project.yaml")):
        kode = p.parent.name
        try:
            cfg = load_project_config(p)
            templates = load_templates(p.parent / "templates.yaml")
        except ConfigError:
            continue
        seen.add(kode)
        out.append({
            "kode": kode, "nama": cfg.nama,
            "sumber": f"{cfg.sumber.dokumen} {cfg.sumber.revisi} "
                      f"({cfg.sumber.tanggal})",
            "jumlah_template": len(templates), "berlapis": True,
        })
    # flat legacy: projects/{kode}.yaml
    for p in sorted((projects_dir / "projects").glob("*.yaml")):
        kode = p.stem
        if kode in seen or kode.startswith("_"):
            continue
        try:
            cfg, templates = load_project(projects_dir, kode)
        except ConfigError:
            continue
        out.append({
            "kode": kode, "nama": cfg.nama,
            "sumber": f"{cfg.sumber.dokumen} {cfg.sumber.revisi} "
                      f"({cfg.sumber.tanggal})",
            "jumlah_template": len(templates), "berlapis": False,
        })
    return out


def migrate_legacy(config_dir):
    """Migrasi config/project.yaml → config/projects/{kode}.yaml sekali.

    Dipanggil saat config/projects/ kosong. File lama TIDAK dihapus.
    """
    config_dir = Path(config_dir)
    proj_file = config_dir / "project.yaml"
    tpl_file = config_dir / "templates.yaml"
    if not proj_file.exists():
        return False
    (config_dir / "projects").mkdir(exist_ok=True)
    (config_dir / "templates").mkdir(exist_ok=True)
    if any((config_dir / "projects").glob("*.yaml")):
        return False  # sudah pernah migrasi / sudah ada proyek

    # baca kode dari file lama
    import yaml
    data = yaml.safe_load(proj_file.read_text())
    kode = str((data.get("proyek") or {}).get("kode", "PRJ-001"))
    if not kode or not all(c.isalnum() or c in "_-" for c in kode):
        kode = "PRJ-001"

    ts = datetime.utcnow().replace(microsecond=0).isoformat() + "+00:00"
    meta_block = (
        "_meta:\n"
        f"  dibuat_via: migrasi\n"
        f"  dibuat_pada: {ts}\n"
        f"  tool_version: {TOOL_VERSION}\n"
    )
    proj_dst = config_dir / "projects" / f"{kode}.yaml"
    proj_dst.write_text(meta_block + proj_file.read_text())
    tpl_dst = config_dir / "templates" / f"{kode}.yaml"
    tpl_dst.write_text(meta_block + tpl_file.read_text())
    return True
