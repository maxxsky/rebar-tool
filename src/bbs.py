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

    # variabel dasar (10-SPEC §3.1 + 12-SPEC §3.2) — L/H = dimensi utama
    L_val = bentang if bentang is not None else 0
    v = {
        "b": vars_.get("b_mm", 0),
        "h": vars_.get("h_mm", 0),
        "c": cfg.cover.get(elemen, 0),
        "d": dia,
        "Ld": cfg.ld.get(dia, 0),
        "L": L_val,
        "H": L_val,
        "stek": 0,
    }
    # vars_ dari template: angka langsung, atau ekspresi yang di-resolve
    # terhadap variabel dasar (mis. {"L": "L + 2*Ld"} — migrasi §6).
    # DUA PASS: angka dulu, ekspresi setelah — supaya ekspresi bisa refer
    # variabel lain dalam vars yang sama (mis. {"L": "H + stek", "stek": 990}).
    for k, x in vars_.items():
        if k in ("b_mm", "h_mm"):
            continue
        if isinstance(x, (int, float)):
            v[k] = float(x)
    for k, x in vars_.items():
        if k in ("b_mm", "h_mm") or isinstance(x, (int, float)):
            continue
        if isinstance(x, str):
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


# ── lap splice (11-SPEC F6) ─────────────────────────────────
def hitung_jumlah_potongan(L: int, S: int, Lp: int) -> int:
    """Jumlah potongan batang utk panjang total L.

    n × S − (n−1) × Lp ≥ L  →  n = ceil((L − Lp) / (S − Lp))
    """
    if S <= Lp:
        raise ConfigError(
            f"Panjang lewatan {Lp} mm tidak boleh ≥ panjang stok {S} mm. "
            f"Cek config lap_splice_mm — nilai salah.")
    if L <= S:
        return 1
    from math import ceil
    n = ceil((L - Lp) / (S - Lp))
    return max(1, n)


def potongan_lap_splice(L: int, S: int, Lp: int, metode: str,
                        offset_mm: int = 0, idx_ganjil: bool = True):
    """Pembagian panjang total L menjadi potongan ≤ S dengan lewatan Lp.

    metode: "sisa_di_ujung" | "bagi_rata" | "berselang".
    Return (panjang_potongan_list, sambungan_di_mm_list).
    idx_ganjil: utk berselang — batang ganjil vs genap digeser beda.
    """
    n = hitung_jumlah_potongan(L, S, Lp)
    if n == 1:
        return [L], []
    total_baja = L + (n - 1) * Lp
    if metode == "bagi_rata":
        p = total_baja // n
        sisa = total_baja % n
        pot = [p + 1] * sisa + [p] * (n - sisa)
        pos = []
        acc = 0
        for x in pot[:-1]:
            acc += x
            pos.append(acc - Lp)
        return pot, pos
    if metode == "berselang":
        # struktur disiapkan (11-SPEC §3.3): batang ganjil & genap beda offset
        off = offset_mm if idx_ganjil else -offset_mm
        pot = [S - off] * (n - 1) + [total_baja - (n - 1) * (S - off)]
        pos = []
        acc = 0
        for x in pot[:-1]:
            acc += x
            pos.append(acc - Lp)
        return pot, pos
    # sisa_di_ujung (default): n−1 potongan stok penuh + satu sisa
    pot = [S] * (n - 1) + [total_baja - (n - 1) * S]
    pos = []
    acc = 0
    for x in pot[:-1]:
        acc += x
        pos.append(acc - Lp)
    return pot, pos


# ── tulangan utama ──────────────────────────────────────────
def generate_tulangan_utama(tul: TemplateTulangan, bentang: int, cfg: ProjectConfig,
                            meta) -> list[Cut]:
    """Tulangan dengan shape dari template (default '01' batang lurus).

    Kalau panjang > stok → pecah dgn lap splice (11-SPEC). Return LIST —
    beberapa Cut kalau tersambung, satu Cut kalau tidak.
    """
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
    S = cfg.stok.panjang_batang_mm

    if panjang <= S:
        # tanpa sambungan — perilaku identik dengan sebelumnya (11-SPEC §5)
        return [Cut(
            dia=tul.dia, panjang_mm=panjang, jumlah=tul.jumlah * meta.jumlah_elemen,
            bar_mark=meta.bar_mark, tipe_elemen=meta.tipe_elemen,
            posisi=meta.posisi, shape_code=shape_kode,
            lokasi=meta.lokasi, segmen_mm=segmen)]

    # ── lap splice ──
    Lp = cfg.lap.get(tul.dia)
    if not Lp:
        raise ConfigError(
            f"{meta.bar_mark}: panjang {panjang} mm melebihi stok {S} mm, "
            f"butuh lap splice, tapi lap_splice_mm utk D{tul.dia} tidak ada "
            f"di config. Isi panjang lewatan (dari gambar).")
    n = hitung_jumlah_potongan(panjang, S, Lp)
    if n > 5:
        cfg.warnings.append(
            f"WARNING: {meta.bar_mark} D{tul.dia} butuh {n} potongan "
            f"(L={panjang} mm) — biasanya input panjang keliru.")

    metode = getattr(cfg, 'lap_metode', 'sisa_di_ujung')
    off = getattr(cfg, 'lap_berselang_offset_mm', 0)
    zona = getattr(tul, 'zona_sambung_terlarang', None) or ()

    out: list[Cut] = []
    for i_b in range(tul.jumlah * meta.jumlah_elemen):
        # berselang: batang ganjil/genap dalam kelompok digeser bergantian
        idx_ganjil = (i_b % 2 == 0)
        pot, pos = potongan_lap_splice(panjang, S, Lp, metode, off, idx_ganjil)
        # 11-SPEC §4: zona sambung terlarang → WARNING, bukan error.
        # Posisi sambungan = ujung potongan − Lp, diukur dari ujung kiri elemen.
        if zona:
            for p_samb in pos:
                r = p_samb / panjang if panjang else 0
                for (dari, sampai) in zona:
                    if dari <= r <= sampai:
                        cfg.warnings.append(
                            f"WARNING: {meta.bar_mark} sambungan jatuh di "
                            f"zona terlarang ({r:.2f}×bentang, dalam "
                            f"{dari}-{sampai}). Cek persetujuan perencana.")
        for pi, p in enumerate(pot):
            if p > S:
                raise LengthExceedsStockError(
                    f"BUG INTERNAL: potongan {p} mm > stok {S} mm (lap splice).")
            akhiran = chr(97 + pi)   # a, b, c, ...
            out.append(Cut(
                dia=tul.dia, panjang_mm=p,
                jumlah=1,
                bar_mark=f"{meta.bar_mark}{akhiran}",
                tipe_elemen=meta.tipe_elemen, posisi=meta.posisi,
                shape_code=shape_kode, lokasi=meta.lokasi,
                segmen_mm=(p,),
                bagian=(pi + 1, len(pot)),
                sambungan_di_mm=tuple(pos)))
    return out


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


def _panjang_zona_rapat(bentang: int, cfg: ProjectConfig,
                        elemen: str = "balok", b_mm: int = 0,
                        h_mm: int = 0) -> int:
    """Panjang zona rapat di tiap ujung — 12-SPEC §4.

    rasio  : faktor × dimensi utama (balok — perilaku lama)
    panjang: ekspresi `lo` dievaluasi (kolom — mis. max(h, L/6, 450)).
    """
    sc = cfg.sengkang_cfg
    if sc.zona_metode == "panjang":
        from shapes import evaluasi_ekspresi
        return int(round(evaluasi_ekspresi(
            sc.zona_lo_ekspresi,
            {"L": bentang, "H": bentang, "h": h_mm, "b": b_mm},
            "sengkang_zona.lo")))
    return round(sc.zona_tumpuan_faktor * bentang)


def hitung_jumlah_sengkang(bentang: int, sk: TemplateSengkang,
                           cfg: ProjectConfig, elemen="balok",
                           b_mm: int = 0, h_mm: int = 0) -> int:
    """Jumlah sengkang per elemen — kontinyu (default) / per_zona, zona
    rasio (balok) / panjang (kolom)."""
    Lt = _panjang_zona_rapat(bentang, cfg, elemen, b_mm, h_mm)
    Ll = bentang - 2 * Lt

    if Ll < 0:
        raise ValueError(
            f"Zona tumpuan ({Lt}×2) melebihi dimensi utama ({bentang}). "
            f"Cek zona_tumpuan_faktor / sengkang_zona.lo.")

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
                      meta) -> list[Cut]:
    """Semua kelompok sengkang (12-SPEC §2) — return LIST.

    jumlah_per_set mengalikan jumlah batang; jarak kelompok kedua+ mewarisi
    dari pertama (sudah di-resolve di config_loader).
    """
    out: list[Cut] = []
    c = cfg.cover[tpl.tipe]
    lebar_dalam = tpl.b_mm - 2 * c
    tinggi_dalam = tpl.h_mm - 2 * c
    for si, sk in enumerate(tpl.sengkang):
        shape = _get_shape(cfg, sk.shape,
                           f"template '{tpl.nama}' sengkang[{si}]")
        vars_ = {"b_mm": tpl.b_mm, "h_mm": tpl.h_mm}
        panjang, segmen = panjang_potong(shape, vars_, sk.dia, sk.hook_sudut,
                                         cfg, elemen=tpl.tipe, bentang=bentang)
        n = hitung_jumlah_sengkang(bentang, sk, cfg, elemen=tpl.tipe,
                                   b_mm=tpl.b_mm, h_mm=tpl.h_mm)
        n_batang = n * sk.jumlah_per_set * meta.jumlah_elemen
        akhiran = "" if len(tpl.sengkang) == 1 else chr(97 + si)  # a, b, ...
        out.append(Cut(
            dia=sk.dia, panjang_mm=panjang, jumlah=n_batang,
            bar_mark=f"{meta.bar_mark}{akhiran}",
            tipe_elemen=meta.tipe_elemen,
            posisi="sengkang", shape_code=sk.shape,
            lokasi=meta.lokasi, segmen_mm=tuple(segmen) if segmen else
            (lebar_dalam, tinggi_dalam, lebar_dalam, tinggi_dalam)))
    return out


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
        out.extend(generate_tulangan_utama(tul, bentang, cfg, meta))

    meta_sk = _Meta(tipe_elemen=tpl.nama, jumlah_elemen=elemen.jumlah,
                    lokasi=lokasi, bar_mark=f"{prefix}{tpl.nama}-SK",
                    posisi="sengkang", b_mm=tpl.b_mm, h_mm=tpl.h_mm)
    out.extend(generate_sengkang(tpl, bentang, cfg, meta_sk))
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
                "bagian": c.bagian, "sambungan_di_mm": c.sambungan_di_mm,
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
            segmen_mm=g["segmen"], bagian=g["bagian"],
            sambungan_di_mm=g["sambungan_di_mm"]))
    return sorted(out, key=lambda c: (c.dia, -c.panjang_mm))
