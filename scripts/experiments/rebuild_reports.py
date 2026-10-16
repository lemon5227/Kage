"""Rebuild every stream report in evidence/reports from the raw Kaggle results.

  python scripts/experiments/rebuild_reports.py [--runs artifacts/kaggle-out] [--out evidence/reports]

--runs holds one directory per Kaggle version with the results unpacked, e.g.
  mkdir -p artifacts/kaggle-out/v9/tar && tar -xzf evidence/kaggle/v9-results.tar.gz -C artifacts/kaggle-out/v9/tar
(missing versions are unpacked from evidence/kaggle/ automatically).
Which arm comes from which version is fixed below; the worklog explains why (e.g. v5 was void except A1).
"""
import argparse
from pathlib import Path
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[2]

E1 = [('A0', 'v6', 'A0'), ('A1', 'v5', 'A1')] + \
     [(arm, v, f'seed{s}/{arm}') for s in (1, 2) for arm, v in (('A3', 'v7'), ('A4', 'v6'))]
E1B = E1 + [('A4r', 'v8', f'seed{s}/A4r') for s in (1, 2)]
E1C = E1B + [(arm, 'v9', f'seed{s}/{arm}') for s in (1, 2) for arm in ('A4g', 'A4m')]
E2_BASE = E1 + [('A4m', 'v9', f'seed{s}/A4m') for s in (1, 2)] + \
          [(arm, 'v10', f'seed{s}/{arm}') for s in (1, 2) for arm in ('A4mG', 'A5', 'A6-fixed')]
REPORTS = {
    'e1-report': E1,
    'e1b-report': E1B,
    'e1c-report': E1C,
    'e2-report': E2_BASE + [('A6', 'v10', f'seed{s}/A6') for s in (1, 2)],
    'e2b-report': E2_BASE + [('A6', 'v11', f'seed{s}/A6') for s in (1, 2)],   # architect fixed in v11
}


def ensure_unpacked(runs: Path, version: str) -> Path:
    base = runs / version / 'tar' / 'e1'
    if not base.exists():
        (runs / version / 'tar').mkdir(parents=True, exist_ok=True)
        with tarfile.open(ROOT / 'evidence' / 'kaggle' / f'{version}-results.tar.gz') as tar:
            tar.extractall(runs / version / 'tar', filter='data')
    return base


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--runs', type=Path, default=ROOT / 'artifacts' / 'kaggle-out')
    p.add_argument('--out', type=Path, default=ROOT / 'evidence' / 'reports')
    args = p.parse_args(argv)
    for name, arms in REPORTS.items():
        cmd = [sys.executable, str(ROOT / 'scripts/experiments/stream_report.py')]
        for arm, version, sub in arms:
            cmd += ['--arm-dir', f'{arm}={ensure_unpacked(args.runs, version) / sub}']
        cmd += ['--constant', 'A0', '--constant', 'A1', '--cp0-from', 'A0', '--out', str(args.out / name)]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
        print('rebuilt', name)


if __name__ == '__main__':
    main()
