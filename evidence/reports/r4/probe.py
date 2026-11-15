"""R4-2b probe (Kaggle v52): start point of the R3fg student on the round-2 code families, what the teacher's
demonstrations add in context, and the guided-collection yield.

  python3 evidence/reports/r4/probe.py     # -> probe.json (table printed)

Source: evidence/kaggle/v52-results.tar.gz.
"""
from collections import defaultdict
from pathlib import Path
import json
import tarfile

HERE = Path(__file__).resolve().parent
FAMILIES = ('grid_rotate', 'version_sort', 'spiral_walk', 'duration_parse')
out = {'eval': defaultdict(dict), 'stream': defaultdict(dict), 'collect': defaultdict(dict), 'teacher': {}}
with tarfile.open(HERE.parents[2] / 'evidence/kaggle/v52-results.tar.gz') as tar:
    def lines(name):
        return [json.loads(l) for l in tar.extractfile(name).read().decode().splitlines() if l.strip()]
    for m in tar.getnames():
        parts = m.split('/')
        if m.endswith('/checkpoints.jsonl') and parts[1] == 'r4':
            arm = parts[3].replace('-r1', '') + (' + demos in memory (after the 30-task stream)' if parts[2] == 'stream' else '')
            counts = defaultdict(lambda: [0, 0])
            for r in lines(m):
                counts[r['family']][0] += float(r['score']) >= 1
                counts[r['family']][1] += 1
            out['eval'][arm] = {f: f'{a}/{b}' for f, (a, b) in counts.items()} | {
                'total': f"{sum(a for a, _ in counts.values())}/{sum(b for _, b in counts.values())}"}
        if m.endswith('/stream.jsonl') and parts[2] == 'stream':
            counts = defaultdict(lambda: [0, 0, 0, 0])
            for r in lines(m):
                c = counts[r['family']]
                c[0] += 1
                c[1] += r.get('student_score', 0) >= 1
                c[2] += r.get('teacher_status') == 'passed'
                c[3] += bool(r.get('misuse'))
            out['stream'][parts[3]] = {f: dict(zip(('tasks', 'student_passed', 'teacher_demos', 'misuse'), c))
                                       for f, c in counts.items()}
        if m.endswith('/spend.jsonl') and parts[2] == 'stream':
            rows = lines(m)
            out['teacher'][parts[3]] = [rows[0]['ledger_remaining_usd'], rows[-1]['ledger_remaining_usd']]
        if m.endswith('/stats.json') and parts[2] == 'collect':
            stats = json.load(tar.extractfile(m))
            out['collect'][parts[3]] = {f: {k: v[k] for k in ('attempts', 'successes', 'yield', 'samples_kept')}
                                        for f, v in stats['families'].items()}
ledger = [x for pair in out['teacher'].values() for x in pair]
out['teacher']['spent_usd'] = round(max(ledger) - min(ledger), 4)
(HERE / 'probe.json').write_text(json.dumps(out, indent=1))
print('| arm | ' + ' | '.join(FAMILIES) + ' | total |\n|---|' + '---|' * (len(FAMILIES) + 1))
for arm, row in out['eval'].items():
    print(f'| {arm} | ' + ' | '.join(row[f] for f in FAMILIES) + f" | {row['total']} |")
print('\n| guided collection | ' + ' | '.join(FAMILIES) + ' |\n|---|' + '---|' * len(FAMILIES))
for arm, row in out['collect'].items():
    print(f'| {arm} | ' + ' | '.join(f"{row[f]['successes']}/{row[f]['attempts']} ({row[f]['samples_kept']} rows)" for f in FAMILIES) + ' |')
print('\nstream', json.dumps(out['stream']), '\nteacher spent', out['teacher']['spent_usd'])
