"""Generator BBS — balok saja, tanpa sambungan (F2).

Spec 02-SPEC-bbs.md. Aturan:
- L_potong = bentang + n_ujung × Ld; > stok → LengthExceedsStockError (bukan silent).
- Sengkang: keliling dalam selimut + 2×tail hook + koreksi bengkokan (default 0).
- Jumlah sengkang: zonasi tumpuan/lapangan, metode "kontinyu" (default) | "per_zona".
- Semua panjang internal mm integer.
"""

from math import ceil, floor

from models import (ConfigError, Cut, ElemenInput, ElementTemplate,
                    LengthExceedsStockError, ProjectConfig, TemplateSengkang,
                    TemplateTulangan)

# shape codes (spec 02 §2/§3)
SHAPE_LURUS = "01"
SHAPE_SENGKANG = "51"


# ── koreksi bengkokan (spec 02 §3.1, PATCH-06 §1) ──────────
def bend_deduction(dia: int, bengkokan: dict, cfg: ProjectConfig) -> int:
    """Total pengurangan panjang akibat bengkokan.

    Nilai POSITIF; pemanggil yang mengurangkannya (PATCH-06 §1.6).

    bengkokan: {sudut: jumlah}, mis. {90: 3, 135: 2} untuk sengkang
    persegi 2 kaki hook 135°.
    Besaran per bengkokan = bend_faktor[sudut] × dia, dari config —
    TIDAK hardcoded (aturan §3.1). Default koreksi OFF sampai F4.
    """
    if not cfg.koreksi_bend_aktif:
        return 0
    # 09-SPEC §8: hook_total = panjang hook_tail SUDAH termasuk lengkungan,
    # jadi bend deduction tidak dikurangi lagi (sudah ada di angka hook).
    if cfg.hook_konvensi == "hook_total":
        return 0
    total = 0
    for sudut, n in bengkokan.items():
        if sudut not in cfg.bend_faktor:
            raise ConfigError(
                f"bend_deduction_faktor untuk {sudut}° tidak ada di config, "
                f"tapi dipakai di template sengkang. Tambahkan ke hook: "
                f"bend_deduction_faktor: {{{sudut}: <kelipatan dia>}} "
                f"atau hapus sudut {sudut} dari sengkang.bengkokan.")
        total += n * cfg.bend_faktor[sudut] * dia
    return total


def _bengkokan_default(hook_sudut: int) -> dict:
    """Bentuk standar sengkang persegi 2 kaki: 3× bengkokan 90° + 2× hook.

    Dipakai kalau template tidak menyebut `bengkokan` — asumsi dicatat
    di output (PATCH-06 §1.6), jangan diam-diam.
    """
    return {90: 3, hook_sudut: 2}


# ── panjang potong universal (10-SPEC §4) ──────────────────
def panjang_potong(shape, vars_, dia, hook_sudut, cfg, elemen="balok",
                   bentang=None) -> tuple[int, tuple[int, ...]]:
    """Panjang potong dari definisi shape — rumus universal.

    Σ segmen + Σ hook − Σ bend deduction.
    Menggantikan jalur terpisah untuk tulangan lurus & sengkang.

    shape: ShapeDef (dari cfg.shapes). vars_: nilai dari template.vars.
    hook_sudut: int | None — untuk bengkokan/hook 'hook' (ikut template).
    """
    from shapes import evaluasi_ekspresi

    # variabel dasar (10-SPEC §3.1) — L = bentang dari input
    v = {
        "b": vars_.get("b_mm", 0),
        "h": vars_.get("h_mm", 0),
        "c": cfg.cover.get(elemen, 0),
        "d": dia,
        "Ld": cfg.ld.get(dia, 0),
        "L": bentang if bentang is not None else 0,
    }
    # vars_ dari template: angka langsung, atau ekspresi yang di-resolve
    # terhadap variabel dasar (mis. {"L": "L + 2*Ld"} — migrasi §6).
    for k, x in vars_.items():
        if k in ("b_mm", "h_mm"):
            continue
        if isinstance(x, (int, float)):
            v[k] = float(x)
        elif isinstance(x, str):
            v[k] = evaluasi_ekspresi(x, v, f"shape.{shape.kode}.vars.{k}")

    segmen = []
    for s in shape.segmen:
        val = evaluasi_ekspresi(s.panjang, v, f"shape.{shape.kode}.{s.id}")
        segmen.append(int(round(val)))

    hook = 0
    for hk in shape.hook:
        sudut = hook_sudut if hk.sudut == "hook" else hk.sudut
        if sudut not in cfg.hook_tail:
            raise ConfigError(
                f"Shape '{shape.kode}' pakai hook {sudut}°, "
                f"tapi hook_tail untuk sudut itu tidak ada di config.")
        if dia not in cfg.hook_tail[sudut]:
            raise ConfigError(
                f"Shape '{shape.kode}': hook_tail {sudut}° untuk D{dia} "
                f"tidak ada di config.")
        hook += hk.jumlah * cfg.hook_tail[sudut][dia]

    bengkokan = {}
    for bd in shape.bengkokan:
        sudut = hook_sudut if bd.sudut == "hook" else bd.sudut
        bengkokan[sudut] = bengkokan.get(sudut, 0) + bd.jumlah

    bend = bend_deduction(dia, bengkokan, cfg)
    if cfg.hook_konvensi == "hook_total":
        bend = 0

    panjang = sum(segmen) + hook - bend
    if panjang <= 0:
        raise ValueError(
            f"Shape '{shape.kode}' menghasilkan panjang {panjang} mm. "
            f"Cek dimensi elemen dan faktor bend deduction.")
    return panjang, tuple(segmen)


def _get_shape(cfg, kode, pemakai):
    """Shape dari cfg.shapes; fallback bawaan kalau cfg.shapes kosong
    (jalur legacy — test lama & load_project_config langsung)."""
    shape = (cfg.shapes or {}).get(kode)
    if shape is None and not cfg.shapes:
        from shapes import shapes_bawaan
        shape = shapes_bawaan().get(kode)
    if shape is None:
        raise ConfigError(
            f"Shape '{kode}' dipakai {pemakai} tapi tidak ada di shapes.yaml.")
    return shape


# ── tulangan utama ──────────────────────────────────────────
def generate_tulangan_utama(tul: TemplateTulangan, bentang: int, cfg: ProjectConfig,
                            meta) -> Cut:
    """Tulangan dengan shape dari template (default '01' batang lurus)."""
    shape_kode = getattr(tul, 'shape', None) or '01'
    shape = _get_shape(cfg, shape_kode, f"template '{meta.tipe_elemen}'")
    # vars dari template; jalur legacy (SimpleNamespace tanpa vars) →
    # reproduksi perilaku lama: L = bentang + n_ujung×Ld
    vars_ = getattr(tul, 'vars', None)
    if not vars_:
        n_ujung = 2 if getattr(tul, 'tumpuan_kedua_ujung', True) else 1
        vars_ = {"L": f"L + {n_ujung}*Ld"}
    vars_ = {**vars_, "b_mm": meta.b_mm, "h_mm": meta.h_mm}
    panjang, segmen = panjang_potong(shape, vars_, tul.dia, None, cfg,
                                     elemen=meta.tipe_elemen, bentang=bentang)

    if panjang > cfg.stok.panjang_batang_mm:
        raise LengthExceedsStockError(
            f"{meta.bar_mark}: panjang potong {panjang} mm melebihi batang stok "
            f"{cfg.stok.panjang_batang_mm} mm. Lap splice belum diimplementasi (F6).")

    return Cut(
        dia=tul.dia, panjang_mm=panjang, jumlah=tul.jumlah * meta.jumlah_elemen,
        bar_mark=meta.bar_mark, tipe_elemen=meta.tipe_elemen,
        posisi=meta.posisi, shape_code=shape_kode,
        lokasi=meta.lokasi, segmen_mm=segmen)


# ── sengkang ────────────────────────────────────────────────
def keliling_sengkang(b, h, dia, hook_sudut, cfg, elemen="balok",
                      bengkokan=None) -> int:
    """Panjang potong sengkang persegi 2 kaki — dalam selimut beton.

    bengkokan: {sudut: jumlah} — PATCH-06 §1.6. Kalau None, pakai bentuk
    standar 3×90° + 2×hook (asumsi dicatat pemanggil).
    """
    c = cfg.cover[elemen]
    lebar_dalam = b - 2 * c
    tinggi_dalam = h - 2 * c
    if lebar_dalam <= 0 or tinggi_dalam <= 0:
        raise ConfigError(
            f"Selimut beton {c} mm terlalu besar untuk penampang {b}x{h} — "
            f"sengkang jadi {lebar_dalam}x{tinggi_dalam} (negatif).")

    keliling = 2 * (lebar_dalam + tinggi_dalam)
    hook = 2 * cfg.hook_tail[hook_sudut][dia]
    bk = bengkokan if bengkokan is not None else _bengkokan_default(hook_sudut)
    bend = bend_deduction(dia, bk, cfg)   # nilai POSITIF → dikurangi

    panjang = keliling + hook - bend

    # cek kewarasan (PATCH-06 §1.6): hasil ≤ 0 atau turun > 30% dari
    # keliling+hook = tanda faktor deduction salah isi (fail loud).
    basis = keliling + hook
    if panjang <= 0 or (bend > 0 and bend > 0.30 * basis):
        raise ConfigError(
            f"Hasil panjang sengkang {panjang} mm tidak wajar (basis "
            f"{basis} mm, bend deduction {bend} mm). Cek nilai "
            f"hook.bend_deduction_faktor — kemungkinan salah isi.")

    return panjang


def hitung_jumlah_sengkang(bentang: int, sk: TemplateSengkang,
                           cfg: ProjectConfig) -> int:
    """Jumlah sengkang per balok — metode kontinyu (default) atau per_zona."""
    faktor = cfg.sengkang_cfg.zona_tumpuan_faktor
    Lt = round(faktor * bentang)
    Ll = bentang - 2 * Lt

    if Ll < 0:
        raise ValueError(
            f"Zona tumpuan ({Lt}×2) melebihi bentang ({bentang}). "
            f"Cek zona_tumpuan_faktor.")

    d0 = cfg.sengkang_cfg.jarak_sengkang_pertama_mm

    n_tump_kiri = 1 + floor(max(0, Lt - d0) / sk.jarak_tumpuan_mm)
    n_tump_kanan = n_tump_kiri

    if cfg.sengkang_cfg.metode_hitung == "per_zona":
        # alternatif tanpa `-1` — konvensi perencana beda (spec 02 §4.3)
        n_lap = ceil(Ll / sk.jarak_lapangan_mm) if Ll > 0 else 0
        n_lap = max(0, n_lap)
    else:
        # "kontinyu" — sengkang batas antar-zona hanya dihitung sekali
        n_lap = ceil(Ll / sk.jarak_lapangan_mm) - 1 if Ll > 0 else 0
        n_lap = max(0, n_lap)

    return n_tump_kiri + n_lap + n_tump_kanan


def generate_sengkang(tpl: ElementTemplate, bentang: int, cfg: ProjectConfig,
                      meta) -> Cut:
    sk = tpl.sengkang
    # 10-SPEC: sengkang pakai shape dari template (default '51')
    shape = _get_shape(cfg, sk.shape, f"template '{tpl.nama}' sengkang")
    vars_ = {"b_mm": tpl.b_mm, "h_mm": tpl.h_mm}
    panjang, segmen = panjang_potong(shape, vars_, sk.dia, sk.hook_sudut,
                                     cfg, elemen=tpl.tipe, bentang=bentang)
    c = cfg.cover[tpl.tipe]
    lebar_dalam = tpl.b_mm - 2 * c
    tinggi_dalam = tpl.h_mm - 2 * c
    n = hitung_jumlah_sengkang(bentang, sk, cfg)
    return Cut(
        dia=sk.dia, panjang_mm=panjang, jumlah=n * meta.jumlah_elemen,
        bar_mark=meta.bar_mark, tipe_elemen=meta.tipe_elemen,
        posisi="sengkang", shape_code=sk.shape,
        lokasi=meta.lokasi, segmen_mm=tuple(segmen) if segmen else
        (lebar_dalam, tinggi_dalam, lebar_dalam, tinggi_dalam))


# ── generate satu elemen ────────────────────────────────────
def generate_elemen(tpl: ElementTemplate, elemen: ElemenInput,
                    cfg: ProjectConfig, gambar_kode=None) -> list[Cut]:
    """Semua Cut untuk satu kelompok elemen identik.

    gambar_kode: prefix bar mark (08 §4.3) — "GS-02/B1-A". None = tanpa prefix.
    """
    bentang = elemen.bentang_bersih_mm
    lokasi = elemen.lokasi
    prefix = f"{gambar_kode}/" if gambar_kode else ""
    out: list[Cut] = []

    for i, tul in enumerate(tpl.tulangan):
        bar_mark = f"{prefix}{tpl.nama}-{tul.posisi[0].upper()}{i + 1}"
        meta = _Meta(tipe_elemen=tpl.nama, jumlah_elemen=elemen.jumlah,
                     lokasi=lokasi, bar_mark=bar_mark, posisi=tul.posisi,
                     b_mm=tpl.b_mm, h_mm=tpl.h_mm)
        out.append(generate_tulangan_utama(tul, bentang, cfg, meta))

    meta_sk = _Meta(tipe_elemen=tpl.nama, jumlah_elemen=elemen.jumlah,
                    lokasi=lokasi, bar_mark=f"{prefix}{tpl.nama}-SK",
                    posisi="sengkang", b_mm=tpl.b_mm, h_mm=tpl.h_mm)
    out.append(generate_sengkang(tpl, bentang, cfg, meta_sk))
    return out


class _Meta:
    __slots__ = ("tipe_elemen", "jumlah_elemen", "lokasi", "bar_mark",
                 "posisi", "b_mm", "h_mm")

    def __init__(self, tipe_elemen, jumlah_elemen, lokasi, bar_mark, posisi,
                 b_mm=0, h_mm=0):
        self.tipe_elemen = tipe_elemen
        self.jumlah_elemen = jumlah_elemen
        self.lokasi = lokasi
        self.bar_mark = bar_mark
        self.posisi = posisi
        self.b_mm = b_mm
        self.h_mm = h_mm


# ── generate semua elemen + agregasi ────────────────────────
def generate_bbs(templates: dict[str, ElementTemplate],
                 elemen_list: list[ElemenInput],
                 cfg: ProjectConfig, gambar_kode=None) -> list[Cut]:
    """Semua Cut dari semua elemen (belum diagregasi).

    gambar_kode: prefix bar mark (08 §4.3) — web & CLI konsisten.
    None = tanpa prefix (pemakaian legacy load_all).
    """
    out: list[Cut] = []
    for el in elemen_list:
        if el.tipe not in templates:
            raise ConfigError(
                f"Tipe '{el.tipe}' tidak ada di templates.yaml. "
                f"Tipe yang dikenal: {', '.join(sorted(templates))}")
        tpl = templates[el.tipe]
        out.extend(generate_elemen(tpl, el, cfg, gambar_kode=gambar_kode))
    return out


def agregasi(cuts: list[Cut]) -> list[Cut]:
    """Gabungkan Cut identik dalam (dia, panjang_mm); jumlah diakumulasi.

    bar_mark asal disimpan sebagai daftar di segmen metadata baru — spec 02 §6:
    BBS sheet tetap menampilkan per bar mark, optimizer cukup (dia, panjang).
    """
    groups: dict[tuple[int, int], dict] = {}
    for c in cuts:
        key = (c.dia, c.panjang_mm)
        if key not in groups:
            groups[key] = {
                "dia": c.dia, "panjang": c.panjang_mm, "jumlah": 0,
                "bar_marks": [], "posisi": c.posisi, "lokasi": c.lokasi,
                "shape": c.shape_code, "segmen": c.segmen_mm,
                "tipe": c.tipe_elemen,
            }
        g = groups[key]
        g["jumlah"] += c.jumlah
        if c.bar_mark and c.bar_mark not in g["bar_marks"]:
            g["bar_marks"].append(c.bar_mark)

    out = []
    for g in groups.values():
        out.append(Cut(
            dia=g["dia"], panjang_mm=g["panjang"], jumlah=g["jumlah"],
            bar_mark=",".join(g["bar_marks"]), tipe_elemen=g["tipe"],
            posisi=g["posisi"], shape_code=g["shape"], lokasi=g["lokasi"],
            segmen_mm=g["segmen"]))
    return sorted(out, key=lambda c: (c.dia, -c.panjang_mm))
