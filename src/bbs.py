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


# ── koreksi bengkokan (spec 02 §3.1) ────────────────────────
def koreksi_bengkokan(dia: int, cfg: ProjectConfig, jumlah_bengkokan: int = 0) -> int:
    """Selisih panjang akibat radius bengkokan.

    Default 0. Aktif via config.hook.koreksi_bengkokan_aktif — TAPI besaran
    belum diverifikasi terhadap BBS asli (F4). Kalau diaktifkan tanpa nilai
    yang sudah terbukti → fail loud, jangan pakai angka tebakan.
    """
    if not cfg.koreksi_bend_aktif:
        return 0
    raise ConfigError(
        "koreksi_bengkokan_aktif=true tetapi besaran koreksi belum terverifikasi "
        "terhadap BBS asli (F4). Matikan config ini, atau isi nilai koreksi yang "
        "sudah dibuktikan dari verifikasi. Jangan biarkan alat memakai angka "
        "tebakan — brief §3.1.")


# ── tulangan utama ──────────────────────────────────────────
def generate_tulangan_utama(tul: TemplateTulangan, bentang: int, cfg: ProjectConfig,
                            meta) -> Cut:
    """Tulangan lurus dengan penyaluran di ujung."""
    ld = cfg.ld[tul.dia]          # fail loud sudah dijamin F0 (validasi config)
    n_ujung = 2 if tul.tumpuan_kedua_ujung else 1
    L = bentang + n_ujung * ld

    if L > cfg.stok.panjang_batang_mm:
        raise LengthExceedsStockError(
            f"{meta.bar_mark}: panjang potong {L} mm melebihi batang stok "
            f"{cfg.stok.panjang_batang_mm} mm. Lap splice belum diimplementasi (F6).")

    return Cut(
        dia=tul.dia, panjang_mm=L, jumlah=tul.jumlah * meta.jumlah_elemen,
        bar_mark=meta.bar_mark, tipe_elemen=meta.tipe_elemen,
        posisi=meta.posisi, shape_code=SHAPE_LURUS,
        lokasi=meta.lokasi, segmen_mm=(L,))


# ── sengkang ────────────────────────────────────────────────
def keliling_sengkang(b, h, dia, hook_sudut, cfg, elemen="balok") -> int:
    """Panjang potong sengkang persegi 2 kaki — dalam selimut beton."""
    c = cfg.cover[elemen]
    lebar_dalam = b - 2 * c
    tinggi_dalam = h - 2 * c
    if lebar_dalam <= 0 or tinggi_dalam <= 0:
        raise ConfigError(
            f"Selimut beton {c} mm terlalu besar untuk penampang {b}x{h} — "
            f"sengkang jadi {lebar_dalam}x{tinggi_dalam} (negatif).")

    keliling = 2 * (lebar_dalam + tinggi_dalam)
    hook = 2 * cfg.hook_tail[hook_sudut][dia]
    bend = koreksi_bengkokan(dia, cfg, jumlah_bengkokan=3)

    return keliling + hook + bend


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
    panjang = keliling_sengkang(tpl.b_mm, tpl.h_mm, sk.dia, sk.hook_sudut,
                                cfg, elemen=tpl.tipe)
    c = cfg.cover[tpl.tipe]
    lebar_dalam = tpl.b_mm - 2 * c
    tinggi_dalam = tpl.h_mm - 2 * c
    n = hitung_jumlah_sengkang(bentang, sk, cfg)
    return Cut(
        dia=sk.dia, panjang_mm=panjang, jumlah=n * meta.jumlah_elemen,
        bar_mark=meta.bar_mark, tipe_elemen=meta.tipe_elemen,
        posisi="sengkang", shape_code=SHAPE_SENGKANG,
        lokasi=meta.lokasi, segmen_mm=(lebar_dalam, tinggi_dalam,
                                       lebar_dalam, tinggi_dalam))


# ── generate satu elemen ────────────────────────────────────
def generate_elemen(tpl: ElementTemplate, elemen: ElemenInput,
                    cfg: ProjectConfig) -> list[Cut]:
    """Semua Cut untuk satu kelompok elemen identik."""
    bentang = elemen.bentang_bersih_mm
    lokasi = elemen.lokasi
    out: list[Cut] = []

    for i, tul in enumerate(tpl.tulangan):
        bar_mark = f"{tpl.nama}-{tul.posisi[0].upper()}{i + 1}"
        meta = _Meta(tipe_elemen=tpl.nama, jumlah_elemen=elemen.jumlah,
                     lokasi=lokasi, bar_mark=bar_mark, posisi=tul.posisi)
        out.append(generate_tulangan_utama(tul, bentang, cfg, meta))

    meta_sk = _Meta(tipe_elemen=tpl.nama, jumlah_elemen=elemen.jumlah,
                    lokasi=lokasi, bar_mark=f"{tpl.nama}-SK",
                    posisi="sengkang")
    out.append(generate_sengkang(tpl, bentang, cfg, meta_sk))
    return out


class _Meta:
    __slots__ = ("tipe_elemen", "jumlah_elemen", "lokasi", "bar_mark", "posisi")

    def __init__(self, tipe_elemen, jumlah_elemen, lokasi, bar_mark, posisi):
        self.tipe_elemen = tipe_elemen
        self.jumlah_elemen = jumlah_elemen
        self.lokasi = lokasi
        self.bar_mark = bar_mark
        self.posisi = posisi


# ── generate semua elemen + agregasi ────────────────────────
def generate_bbs(templates: dict[str, ElementTemplate],
                 elemen_list: list[ElemenInput],
                 cfg: ProjectConfig) -> list[Cut]:
    """Semua Cut dari semua elemen (belum diagregasi)."""
    out: list[Cut] = []
    for el in elemen_list:
        if el.tipe not in templates:
            raise ConfigError(
                f"Tipe '{el.tipe}' tidak ada di templates.yaml. "
                f"Tipe yang dikenal: {', '.join(sorted(templates))}")
        tpl = templates[el.tipe]
        out.extend(generate_elemen(tpl, el, cfg))
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
