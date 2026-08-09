"""Shape Library (10-SPEC) — definisi bentuk tulangan dari config.

Rumus universal:
    panjang_potong = Σ segmen + Σ hook − Σ bend deduction

Ekspresi segmen diparse dengan whitelist node (ast) — TANPA eval().
Variabel yang boleh: L, b, h, c, Ld, d, tekuk (10-SPEC §3.1).
Operator: + − * / dan kurung. Angka desimal boleh.
"""

import ast
from pathlib import Path

import yaml

from models import (ConfigError, ShapeBengkokan, ShapeDef, ShapeHook,
                    ShapeSegmen)

# 10-SPEC §3.1 — whitelist tertutup
ALLOWED_VARS = {"L", "b", "h", "c", "Ld", "d", "tekuk"}


# ── parser ekspresi (tanpa eval) ────────────────────────────
def parse_ekspresi(expr: str, path: str) -> ast.Expression:
    """Parse ekspresi & cek whitelist variabel/operator — fail loud.

    Dipanggil saat LOAD (validasi) dan saat HITUNG (evaluasi).
    """
    if not isinstance(expr, str) or not expr.strip():
        raise ConfigError(f"{path}: ekspresi panjang kosong.")
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except SyntaxError as e:
        raise ConfigError(
            f"{path}: ekspresi '{expr}' tidak bisa diparse "
            f"(posisi {e.offset}).")
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if node.id not in ALLOWED_VARS:
                raise ConfigError(
                    f"{path}: ekspresi '{expr}' memakai variabel "
                    f"'{node.id}' yang tidak dikenal. "
                    f"Variabel yang boleh: {', '.join(sorted(ALLOWED_VARS))}.")
        elif isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(
                    node.value, (int, float)):
                raise ConfigError(
                    f"{path}: ekspresi '{expr}' memakai literal "
                    f"{node.value!r} yang tidak didukung.")
        elif isinstance(node, ast.BinOp):
            if not isinstance(node.op, (ast.Add, ast.Sub, ast.Mult,
                                        ast.Div, ast.FloorDiv)):
                raise ConfigError(
                    f"{path}: operator {type(node.op).__name__} di "
                    f"'{expr}' tidak didukung. Yang boleh: + − * /.")
        elif isinstance(node, ast.UnaryOp):
            if not isinstance(node.op, (ast.UAdd, ast.USub)):
                raise ConfigError(
                    f"{path}: operator unary {type(node.op).__name__} "
                    f"di '{expr}' tidak didukung.")
        elif not isinstance(node, (ast.Expression, ast.BinOp, ast.UnaryOp,
                                   ast.operator, ast.Load, ast.Constant,
                                   ast.Name)):
            raise ConfigError(
                f"{path}: ekspresi '{expr}' memakai konstruksi "
                f"{type(node).__name__} yang tidak didukung "
                f"(hanya + − * / dan kurung).")
    return tree


def evaluasi_ekspresi(expr: str, vars_, path: str) -> float:
    """Evaluasi ekspresi aman — variabel dari whitelist, tanpa eval()."""
    tree = parse_ekspresi(expr, path)

    def _eval(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id not in vars_:
                raise ConfigError(
                    f"{path}: variabel '{node.id}' tidak tersedia saat "
                    f"hitung. Isi lewat vars di template elemen.")
            return vars_[node.id]
        if isinstance(node, ast.BinOp):
            l, r = _eval(node.left), _eval(node.right)
            if isinstance(node.op, ast.Add): return l + r
            if isinstance(node.op, ast.Sub): return l - r
            if isinstance(node.op, ast.Mult): return l * r
            if isinstance(node.op, ast.Div):
                if r == 0: raise ConfigError(
                    f"{path}: pembagian dengan nol di '{expr}'.")
                return l / r
            if isinstance(node.op, ast.FloorDiv):
                if r == 0: raise ConfigError(
                    f"{path}: pembagian dengan nol di '{expr}'.")
                return l // r
        if isinstance(node, ast.UnaryOp):
            v = _eval(node.operand)
            return -v if isinstance(node.op, ast.USub) else v
        raise ConfigError(f"{path}: ekspresi '{expr}' tidak valid.")

    return _eval(tree.body)


# ── load shapes.yaml ────────────────────────────────────────
def _norm_sudut(v, path):
    """Sudut bengkokan/hook: angka atau string 'hook'."""
    if isinstance(v, str) and v.strip().lower() == "hook":
        return "hook"
    try:
        return int(v)
    except (TypeError, ValueError):
        raise ConfigError(f"{path}: sudut harus angka atau 'hook', "
                          f"dapat {v!r}")


def load_shapes(path) -> dict[str, ShapeDef]:
    """Load config/shapes.yaml → {kode: ShapeDef}. Kumpulkan SEMUA error."""
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"Config shape tidak ditemukan: {path}")
    with open(path) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: shapes harus berupa mapping kode -> definisi")

    errors: list[str] = []
    shapes: dict[str, ShapeDef] = {}
    for kode, d in data.items():
        if kode == "_meta":
            continue
        try:
            shapes[str(kode)] = _parse_shape(str(kode), d, path)
        except ConfigError as e:
            errors.append(str(e))
    if errors:
        raise ConfigError(
            "Config shapes tidak lengkap.\n\n" + "\n\n".join(errors) +
            "\n\nPerbaiki config/shapes.yaml lalu jalankan ulang.")
    return shapes


def _parse_shape(kode, d, path) -> ShapeDef:
    if not isinstance(d, dict):
        raise ConfigError(f"shape.{kode}: definisi harus mapping")
    nama = str(d.get("nama", kode))
    deskripsi = str(d.get("deskripsi", ""))

    segmen_raw = d.get("segmen") or []
    if not isinstance(segmen_raw, list) or not segmen_raw:
        raise ConfigError(f"shape.{kode}: minimal satu segmen")
    segmen = []
    for i, s in enumerate(segmen_raw):
        sp = f"shape.{kode}.segmen[{i}]"
        if not isinstance(s, dict):
            raise ConfigError(f"{sp}: segmen harus mapping")
        sid = str(s.get("id", chr(65 + i)))
        panjang = s.get("panjang", "")
        parse_ekspresi(panjang, f"{sp}.panjang")   # validasi saat load
        segmen.append(ShapeSegmen(id=sid, panjang=panjang))

    bengkokan = []
    for i, b in enumerate(d.get("bengkokan") or []):
        bp = f"shape.{kode}.bengkokan[{i}]"
        sudut = _norm_sudut(b.get("sudut"), f"{bp}.sudut")
        jumlah = int(b.get("jumlah", 1))
        if jumlah <= 0:
            raise ConfigError(f"{bp}.jumlah: harus > 0")
        bengkokan.append(ShapeBengkokan(sudut=sudut, jumlah=jumlah))

    hook = []
    for i, hk in enumerate(d.get("hook") or []):
        hp = f"shape.{kode}.hook[{i}]"
        sudut = _norm_sudut(hk.get("sudut"), f"{hp}.sudut")
        jumlah = int(hk.get("jumlah", 1))
        if jumlah <= 0:
            raise ConfigError(f"{hp}.jumlah: harus > 0")
        hook.append(ShapeHook(sudut=sudut, jumlah=jumlah))

    # §8: jumlah bengkokan > jumlah segmen → warning (tidak fatal di load;
    # ditambahkan ke cfg.warnings oleh pemanggil)
    n_bengkokan = sum(b.jumlah for b in bengkokan)
    n_segmen = len(segmen)

    return ShapeDef(kode=kode, nama=nama, deskripsi=deskripsi,
                    segmen=tuple(segmen), bengkokan=tuple(bengkokan),
                    hook=tuple(hook))


# ── shapes bawaan (migrasi — reproduksi perilaku lama persis) ──
DEFAULT_SHAPES_YAML = """\
# Bentuk tulangan bawaan — 10-SPEC. Reproduksi perilaku asli:
# "01" batang lurus, "51" sengkang persegi 2 kaki.
_meta:
  dibuat_via: migrasi
  catatan: "Bawaan 10-SPEC — bisa diubah per proyek"
"01":
  nama: "Batang lurus"
  deskripsi: "Tanpa bengkokan"
  segmen:
    - { id: A, panjang: "L" }
  bengkokan: []
  hook: []

"51":
  nama: "Sengkang persegi 2 kaki"
  deskripsi: "Sengkang tertutup dengan hook di satu sudut"
  segmen:
    - { id: A, panjang: "b - 2*c" }
    - { id: B, panjang: "h - 2*c" }
    - { id: C, panjang: "b - 2*c" }
    - { id: D, panjang: "h - 2*c" }
  bengkokan:
    - { sudut: 90, jumlah: 3 }
    - { sudut: hook, jumlah: 2 }
  hook:
    - { sudut: hook, jumlah: 2 }
"""


def tulis_shapes_bawaan(path) -> Path:
    """Migrasi otomatis: proyek tanpa shapes.yaml → tulis bawaan (10-SPEC §6)."""
    path = Path(path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(DEFAULT_SHAPES_YAML)
    return path


def shapes_bawaan() -> dict[str, ShapeDef]:
    """Shape bawaan (01/51) sebagai dict — fallback jalur legacy.

    Test lama & pemanggil yang load config tanpa shapes.yaml (mis.
    load_project_config langsung) tetap mendapat perilaku asli: generate
    memakai bawaan yang mereproduksi hasil lama persis.
    """
    import io
    return load_shapes_from_text(DEFAULT_SHAPES_YAML)


def load_shapes_from_text(text: str) -> dict[str, ShapeDef]:
    """Load shapes dari string YAML (dipakai shapes_bawaan)."""
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ConfigError("shapes bawaan harus mapping kode -> definisi")
    errors: list[str] = []
    shapes: dict[str, ShapeDef] = {}
    for kode, d in data.items():
        if kode == "_meta":
            continue
        try:
            shapes[str(kode)] = _parse_shape(str(kode), d, "shapes")
        except ConfigError as e:
            errors.append(str(e))
    if errors:
        raise ConfigError(
            "Config shapes bawaan tidak lengkap.\n\n" + "\n\n".join(errors))
    return shapes
