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
    bengkokan = dict(sk.bengkokan) if sk.bengkokan else None
    if bengkokan is None and cfg.koreksi_bend_aktif:
        # asumsi bentuk standar dipakai — catat, jangan diam-diam (PATCH-06 §1.6)
        asumsi = _bengkokan_default(sk.hook_sudut)
        pesan = (f"WARNING: template '{tpl.nama}' sengkang tidak menyebut "
                 f"bengkokan; dipakai asumsi sengkang persegi 2 kaki "
                 f"{asumsi.get(90, 0)}×90° + {asumsi.get(sk.hook_sudut, 0)}×"
                 f"{sk.hook_sudut}°. Verifikasi ke BBS asli sebelum "
                 f"mengaktifkan koreksi bengkokan.")
        if pesan not in cfg.warnings:
            cfg.warnings.append(pesan)
        bengkokan = asumsi
    panjang = keliling_sengkang(tpl.b_mm, tpl.h_mm, sk.dia, sk.hook_sudut,
                                cfg, elemen=tpl.tipe, bengkokan=bengkokan)
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
                     lokasi=lokasi, bar_mark=bar_mark, posisi=tul.posisi)
        out.append(generate_tulangan_utama(tul, bentang, cfg, meta))

    meta_sk = _Meta(tipe_elemen=tpl.nama, jumlah_elemen=elemen.jumlah,
                    lokasi=lokasi, bar_mark=f"{prefix}{tpl.nama}-SK",
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
