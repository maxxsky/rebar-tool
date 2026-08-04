"""CLI standalone rebar-tool (F1).

Contoh:
    python src/cli.py optimize input/potongan.csv --config config
    python src/cli.py optimize input/potongan.csv --config config --no-limit

CSV: header `dia,panjang_mm,jumlah`
"""

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config_loader import load_all
from models import Cut
from optimizer import optimize_all


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

    # bypass pembatasan pola kalau --no-limit
    if args.no_limit:
        import dataclasses
        cfg = dataclasses.replace(cfg, optimizer=dataclasses.replace(
            cfg.optimizer, batasi_pola=False))

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
    print(f"TOTAL: {total_batang} batang | sisa {total_waste:,} mm "
          f"({total_waste / total_stok * 100:.2f}%)" if total_stok else "")
    return 0


def main():
    parser = argparse.ArgumentParser(prog="rebar-tool")
    sub = parser.add_subparsers(dest="cmd", required=True)

    po = sub.add_parser("optimize", help="optimasi potong dari CSV")
    po.add_argument("csv", type=Path)
    po.add_argument("--config", type=Path, default=Path("config"))
    po.add_argument("--no-limit", action="store_true",
                    help="lewati pembatasan pola (bandingkan)")
    po.set_defaults(fn=cmd_optimize)

    args = parser.parse_args()
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()
