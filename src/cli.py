import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config_loader import load_all
from models import Cut
from optimizer import optimize_all
from bbs import agregasi, generate_bbs
from input_reader import baca_elemen_xlsx


def _baca_csv(path: Path) -> list[Cut]:
    cuts: list[Cut] = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            dia = int(row["dia"])
            panjang = int(row["panjang_mm"])
            jumlah = int(row["jumlah"])
            if panjang <= 0 or jumlah <= 0:
                raise ValueError(
                    f"CSV baris {reader.line_num}: panjang/jumlah harus positif "
                    f"({panjang}, {jumlah})")
            cuts.append(Cut(dia=dia, panjang_mm=panjang, jumlah=jumlah))
    return cuts


def _fmt_metrik(r):
    return (f"  {r.dia:>3} mm | batang {r.total_batang:>4} | "
            f"terpakai {r.total_panjang_terpakai_mm:>9,} mm | "
            f"sisa {r.total_sisa_mm:>9,} mm | "
            f"reusable {r.sisa_reusable_mm:>8,} mm | "
            f"waste {r.waste_pct:.2f}% | "
            f"waste kotor {r.waste_kotor_pct:.2f}% | "
            f"pola {r.pola_sebelum_batasi} -> {r.pola_sesudah_batasi}")


def cmd_optimize(args):
    cfg, _ = load_all(args.config)
    for w in cfg.warnings:
        print(w)
    cuts = _baca_csv(args.csv)

    results = optimize_all(cuts, cfg)
    if not results:
        print("Tidak ada potongan.")
        return 0

    print(f"=== OPTIMIZER — {cfg.nama} ({cfg.kode}) ===")
    print(f"sumber: {cfg.sumber.dokumen} {cfg.sumber.revisi} — {cfg.sumber.tanggal}")
    print(f"stok {cfg.stok.panjang_batang_mm} mm | kerf {cfg.stok.kerf_mm} mm | "
          f"max_pola {cfg.optimizer.max_pola} | batasi {cfg.optimizer.batasi_pola}")
    print()
    for dia, r in sorted(results.items()):
        print(_fmt_metrik(r))
        for p in r.patterns:
            mark = " (reusable)" if p.reusable else ""
            print(f"      pola {p.potongan} ×{p.frekuensi} "
                  f"sisa {p.sisa_mm}{mark}")
        print()
    total_batang = sum(r.total_batang for r in results.values())
    total_waste = sum(r.total_sisa_mm for r in results.values())
    total_stok = sum(r.total_panjang_stok_mm for r in results.values())
    if total_stok:
        print(f"TOTAL: {total_batang} batang | sisa {total_waste:,} mm "
              f"({total_waste / total_stok * 100:.2f}%)")
    return 0


def cmd_bbs(args):
    from config_loader import load_all, load_layered
    if args.proyek and args.gambar:
        cfg, templates, info = load_layered(Path(args.config) / "projects",
                                            args.proyek, args.gambar)
        gambar_kode = info["kode"]
        print(f"gambar: {gambar_kode} {info['revisi']} — {info['nama']}")
    else:
        cfg, templates = load_all(args.config)
        gambar_kode = None
    for w in cfg.warnings:
        print(w)
    elemen = baca_elemen_xlsx(args.input, templates)
    cuts = generate_bbs(templates, elemen, cfg, gambar_kode=gambar_kode)
    agg = agregasi(cuts)
    hasil_opt = optimize_all(agg, cfg)

    print(f"=== BBS — {cfg.nama} ({cfg.kode}) ===")
    print(f"sumber: {cfg.sumber.dokumen} {cfg.sumber.revisi} — {cfg.sumber.tanggal}")
    print(f"elemen: {len(elemen)} grup | cut: {len(cuts)} -> agregat {len(agg)}")
    print()
    print(f"{'dia':>4} {'panjang':>8} {'jumlah':>6}  bar_mark")
    for c in agg:
        print(f"{c.dia:>4} {c.panjang_mm:>8} {c.jumlah:>6}  {c.bar_mark or '-'}")
    print()
    for dia, r in sorted(hasil_opt.items()):
        print(_fmt_metrik(r))

    # ── export Excel ──
    if not args.no_export:
        from datetime import datetime
        from export import generate_excel
        ts = datetime.now().strftime("%Y%m%d-%H%M")
        out_dir = args.output
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"BBS_{cfg.kode}_{ts}.xlsx"
        generate_excel(cfg, elemen, cuts, hasil_opt, args.config, out_path)
        print()
        print(f"Excel: {out_path}")
    return 0


def cmd_fix_gambar_kode(args):
    """Perbaiki kode gambar hasil migrasi lama (PATCH-03 #2).

    Scan projects/*/drawings/*.yaml; kalau _meta.dibuat_via=migrasi dan
    kode == nama proyek (salah), ekstrak kode gambar dari sumber.dokumen
    dan rename. Kalau pola tidak ketemu → kode MIGRASI + catatan.
    """
    import yaml
    from config_loader import _ekstrak_kode_gambar, _ekstrak_nama_gambar
    base = Path(args.config) / "projects"
    fixed = 0
    for proj_dir in sorted(base.glob("*/")):
        proj = proj_dir.name
        if not (proj_dir / "project.yaml").exists():
            continue  # folder non-proyek (mis. _arsip)
        proj_cfg = yaml.safe_load((proj_dir / "project.yaml").read_text())
        dokumen = str((proj_cfg.get("sumber") or {}).get("dokumen", ""))
        for draw in sorted((proj_dir / "drawings").glob("*.yaml")):
            d = yaml.safe_load(draw.read_text()) or {}
            meta = d.get("_meta") or {}
            if meta.get("dibuat_via") != "migrasi":
                continue
            if d.get("kode") != proj:
                continue  # bukan hasil migrasi yang salah
            gkode = _ekstrak_kode_gambar(dokumen)
            gnama = _ekstrak_nama_gambar(dokumen) or proj
            catat = ""
            if gkode is None:
                gkode = "MIGRASI"
                catat = ("Kode gambar tidak terdeteksi dari sumber.dokumen "
                         "— ganti manual dengan kode gambar yang benar.")
            d["kode"] = gkode
            d["nama"] = gnama
            if catat:
                d.setdefault("_meta", {})["catatan_migrasi"] = catat
            new_path = draw.parent / f"{gkode}.yaml"
            if new_path != draw:
                draw.rename(new_path)
            new_path.write_text(yaml.safe_dump(d, allow_unicode=True))
            print(f"{proj}: {draw.name} → {new_path.name} "
                  f"(kode={gkode}, nama={gnama})")
            fixed += 1
    print(f"selesai: {fixed} gambar diperbaiki.")
    return 0


def main():
    parser = argparse.ArgumentParser(prog="rebar-tool")
    sub = parser.add_subparsers(dest="cmd", required=True)

    po = sub.add_parser("optimize", help="optimasi potong dari CSV")
    po.add_argument("csv", type=Path)
    po.add_argument("--config", type=Path, default=Path("config"))
    po.set_defaults(fn=cmd_optimize)

    pb = sub.add_parser("bbs", help="generate BBS + optimizer + export Excel")
    pb.add_argument("input", type=Path, nargs="?", default=Path("input/elemen.xlsx"))
    pb.add_argument("--config", type=Path, default=Path("config"))
    pb.add_argument("--proyek", help="kode proyek (berlapis, 08)")
    pb.add_argument("--gambar", help="kode gambar (berlapis, 08)")
    pb.add_argument("--output", type=Path, default=Path("output"))
    pb.add_argument("--no-export", action="store_true", help="tanpa Excel")
    pb.set_defaults(fn=cmd_bbs)

    pf = sub.add_parser("fix-gambar-kode",
                        help="perbaiki kode gambar hasil migrasi lama (PATCH-03)")
    pf.add_argument("--config", type=Path, default=Path("config"))
    pf.set_defaults(fn=cmd_fix_gambar_kode)

    args = parser.parse_args()
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()
