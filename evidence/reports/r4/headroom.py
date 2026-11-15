"""R4-0 headroom audit: per-family pass counts of the R3fg student (two seeds x 3 runs) and its same-session base anchor.

  python3 evidence/reports/r4/headroom.py     # -> headroom.json (table printed)

Source: evidence/colab/r3fg-eval-results.tar.gz (cp0 rows of every checkpoints.jsonl). No model calls.
"""
from collections import defaultdict
from pathlib import Path
import json
import tarfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
out = defaultdict(lambda: defaultdict(lambda: [0, 0]))
with tarfile.open(ROOT / 'evidence/colab/r3fg-eval-results.tar.gz') as tar:
    for m in tar.getmembers():
        if not (m.name.startswith('e1/ae/') and m.name.endswith('/checkpoints.jsonl')):
            continue
        suite, run = m.name.split('/')[2:4]
        arm = run.rsplit('-r', 1)[0]
        for line in tar.extractfile(m).read().decode().splitlines():
            r = json.loads(line)
            if r['checkpoint'] == 'cp0':
                cell = out[f"{suite}:{r['family']}"][arm]
                cell[0] += float(r['score']) >= 1
                cell[1] += 1
table = {}
for family, arms in sorted(out.items()):
    a, b = (arms['r3fg0'][0] + arms['r3fg1'][0]), (arms['r3fg0'][1] + arms['r3fg1'][1])
    table[family] = {arm: f'{x}/{n}' for arm, (x, n) in sorted(arms.items())} | {'r3fg_pooled': f'{a}/{b}',
                                                                                'headroom': round(1 - a / b, 2)}
(HERE / 'headroom.json').write_text(json.dumps(table, indent=1))
print('| family | A0 (1 run) | r3fg0 | r3fg1 | pooled | headroom |\n|---|---|---|---|---|---|')
for family, row in table.items():
    print(f"| {family} | {row.get('A0', '—')} | {row['r3fg0']} | {row['r3fg1']} | {row['r3fg_pooled']} | {row['headroom']} |")
