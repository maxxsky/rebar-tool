"""Models — dataclass immutable utk seluruh pipeline rebar-tool.

Semua panjang internal dalam mm integer. Nilai teknis TIDAK pernah
hardcoded — datang dari ProjectConfig yang diisi dari config YAML.
"""

from dataclasses import dataclass, field

TOOL_VERSION = "0.1.0"


class ConfigError(Exception):
    """Error validasi config — fail loud, tidak ada fallback diam-diam."""


@dataclass(frozen=True)
class SourceInfo:
    dokumen: str
    revisi: str
    tanggal: str
    catatan: str = ""


@dataclass(frozen=True)
class StockConfig:
    panjang_batang_mm: int
    kerf_mm: int
    sisa_min_simpan_mm: int


@dataclass(frozen=True)
class SengkangConfig:
    zona_tumpuan_faktor: float
    jarak_sengkang_pertama_mm: int
    metode_hitung: str = "kontinyu"   # "kontinyu" | "per_zona" — lihat spec 02 §4.3


@dataclass(frozen=True)
class OptimizerConfig:
    max_pola: int = 8
    batasi_pola: bool = False   # PATCH-01: pembatasan pola dihapus — true ditolak loader


class InfeasiblePatternError(Exception):
    """BUG INTERNAL: pola tidak layak dieksekusi / batang tidak terwakili.

    Bukan error input — pesan menyebut itu supaya tidak salah diagnosa.
    """


@dataclass(frozen=True)
class ProjectConfig:
    """Config proyek — immutable setelah load. Frozen disengaja.

    Kalau ada kode yang butuh mengubah nilai config saat runtime,
    itu tanda nilai tsb seharusnya parameter fungsi, bukan config.
    """

    nama: str
    kode: str
    sumber: SourceInfo
    stok: StockConfig
    cover: dict                      # 'balok' | 'kolom' | 'plat' -> mm
    ld: dict                         # dia -> mm
    lap: dict                        # dia -> mm
    hook_tail: dict                  # sudut -> dia -> mm
    bend_factor: int
    bend_faktor: dict                # sudut -> kelipatan diameter (PATCH-06 §1.5)
    unit_weight: dict                # dia -> kg/m
    sengkang_cfg: SengkangConfig
    optimizer: OptimizerConfig
    koreksi_bend_aktif: bool = False  # spec 02 §3.1 — default OFF sampai terverifikasi (F4)
    hook_konvensi: str = "tail_terpisah"  # 09-SPEC §8: "tail_terpisah" | "hook_total"
    shapes: dict = field(default_factory=dict)  # 10-SPEC: {kode: ShapeDef}
    warnings: list = field(default_factory=list)


@dataclass(frozen=True)
class ShapeSegmen:
    id: str
    panjang: str          # ekspresi — dievaluasi via parser whitelist (10-SPEC §3)


@dataclass(frozen=True)
class ShapeBengkokan:
    sudut: object         # int | "hook"
    jumlah: int


@dataclass(frozen=True)
class ShapeHook:
    sudut: object         # int | "hook"
    jumlah: int


@dataclass(frozen=True)
class ShapeDef:
    """Definisi bentuk tulangan — config/shapes.yaml (10-SPEC §3).

    Rumus universal: panjang_potong = Σ segmen + Σ hook − Σ bend deduction.
    """
    kode: str
    nama: str
    deskripsi: str
    segmen: tuple[ShapeSegmen, ...]
    bengkokan: tuple[ShapeBengkokan, ...]
    hook: tuple[ShapeHook, ...]


@dataclass(frozen=True)
class TemplateTulangan:
    posisi: str
    dia: int
    jumlah: int
    tumpuan_kedua_ujung: bool = True
    shape: str = "01"     # 10-SPEC §5 — default batang lurus
    vars: dict = field(default_factory=dict)


@dataclass(frozen=True)
class TemplateSengkang:
    dia: int
    jarak_tumpuan_mm: int
    jarak_lapangan_mm: int
    kaki: int
    hook_sudut: int
    # PATCH-06 §1.6: jumlah bengkokan per sudut (mis. {90: 3, 135: 2} utk
    # sengkang persegi 2 kaki). Kosong → turunkan dari bentuk standar
    # (3× sudut 90° + 2× hook_sudut) — asumsi dicatat di output.
    bengkokan: dict = field(default_factory=dict)
    shape: str = "51"     # 10-SPEC §5 — default sengkang persegi 2 kaki


@dataclass(frozen=True)
class ElementTemplate:
    """Satu template tipe elemen (misal balok.B1)."""
    nama: str
    tipe: str
    deskripsi: str
    b_mm: int
    h_mm: int
    tulangan: tuple[TemplateTulangan, ...]
    sengkang: TemplateSengkang


# ── Elemen input (F2+) ──────────────────────────────────────
@dataclass(frozen=True)
class ElemenInput:
    tipe: str
    bentang_bersih_mm: int
    jumlah: int
    lokasi: str = ""


# ── Cutting stock (F1) ──────────────────────────────────────
class LengthExceedsStockError(Exception):
    """Panjang potong > batang stok — fail loud, bukan silent truncate (F6)."""


@dataclass(frozen=True)
class Cut:
    """Satu kebutuhan potongan: diameter + panjang + jumlah.

    Metadata dibawa untuk traceability & output BBS.
    """
    dia: int              # mm
    panjang_mm: int       # panjang potong (sudah termasuk hook & bengkokan)
    jumlah: int
    # metadata untuk traceability & output BBS
    bar_mark: str = ""    # "B1-A" (tipe - posisi)
    tipe_elemen: str = "" # "B1"
    posisi: str = ""      # "atas" | "bawah" | "pinggang" | "sengkang"
    shape_code: str = ""  # "01" lurus, "51" sengkang, dst
    lokasi: str = ""      # dari input, bebas teks
    segmen_mm: tuple[int, ...] = ()   # dimensi per segmen, untuk kolom shape


@dataclass(frozen=True)
class Pattern:
    """Satu pola potong — multiset potongan yang diulang beberapa batang."""
    potongan: tuple[int, ...]      # panjang tiap potongan, urut
    frekuensi: int                 # berapa batang dipotong dengan pola ini
    sisa_mm: int                   # sisa per batang
    reusable: bool                 # sisa >= sisa_min_simpan_mm


@dataclass(frozen=True)
class OptimizeResult:
    dia: int
    patterns: list[Pattern]
    total_batang: int
    total_panjang_stok_mm: int     # total_batang × panjang_batang
    total_panjang_terpakai_mm: int # jumlah semua potongan
    total_kerf_mm: int
    total_sisa_mm: int
    sisa_reusable_mm: int
    waste_pct: float
    waste_kotor_pct: float
    # metrik pembatasan pola
    pola_sebelum_batasi: int
    pola_sesudah_batasi: int
    waste_pct_tanpa_batasi: float
