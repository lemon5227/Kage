"""Offline audit for paper v0.4. Run from any directory; no model/network calls."""
from pathlib import Path
import collections
import gzip
import itertools
import json
import tarfile

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent

def read(path):
    return json.loads((ROOT / path).read_text())

result = {}
rows = [json.loads(line) for line in gzip.open(ROOT / 'evidence/reports/r2/sft-v21.jsonl.gz', 'rt')]
result['r2'] = {'examples': len(rows), 'unique_tasks': len({r['task_id'] for r in rows}),
                'retained_rollout_keys': len({(r['task_id'], str(r.get('source')), str(r.get('attempt'))) for r in rows})}
counts = [read(f'evidence/reports/r2/{n}-stats.json')['totals'] for n in ('file-a','file-b','browser-forms','browser-catalog')]
result['r2']['collection_totals'] = {k:sum(c[k] for c in counts) for k in ('attempts','successes','samples_kept')}
result['training'] = {}
for version in ('r3','r3b','r3c','r3d','r3e'):
    c = read(f'evidence/reports/{version}/train-config.json')
    result['training'][version] = {k:c[k] for k in ('examples','steps','seed','epochs','wall_seconds')}
result['training_wall_hours'] = sum(v['wall_seconds'] for v in result['training'].values()) / 3600
result['g0'] = {}
for arm in ('a0-test-v2','a0-test-v2-lessons','a0-test-v2-planonly','a0-test-v2-plan','a0-final-v4-plan'):
    by_task = collections.defaultdict(list)
    for line in (ROOT / f'evidence/reports/g0/{arm}/results.jsonl').read_text().splitlines():
        r = json.loads(line)
        by_task[r['task_id']].append(int(r['check']['passed']))
    result['g0'][arm] = {'by_task':dict(by_task),'passed':sum(map(sum,by_task.values())), 'runs':sum(map(len,by_task.values()))}
a = result['g0']['a0-test-v2']['by_task']
b = result['g0']['a0-test-v2-plan']['by_task']
diffs = [sum(b[k])/len(b[k]) - sum(a[k])/len(a[k]) for k in a]
observed = abs(sum(diffs))
p = sum(abs(sum(d*s for d,s in zip(diffs,signs))) >= observed-1e-10
        for signs in itertools.product((-1,1),repeat=len(diffs))) / (2**len(diffs))
result['g0_sign_flip'] = {'task_order':list(a),'mean_differences':diffs,'two_sided_p':p,'assumption':'task-level sign symmetry; exploratory sensitivity analysis'}
result['d7'] = {}
for f in ('heldout.json','v2-heldout2.json'):
    rs = read('evidence/reports/d7/'+f)
    result['d7'][f] = {'n':len(rs),**{k:sum(r[k]==r['intent'] for r in rs) for k in ('legacy','clef','combined')}}
# Read actual checkpoint records without extracting or modifying historical archives.
learn = {'subset_selection','interval_merge','log_aggregation','csv_transform'}
held = {'text_normalize','config_migrate'}
result['raw_checkpoints'] = {}
for version in (26,28,29,30,31,32,33):
    totals = {}
    with tarfile.open(ROOT / f'evidence/kaggle/v{version}-results.tar.gz') as archive:
        for member in archive.getmembers():
            if not member.name.endswith('/checkpoints.jsonl'):
                continue
            family = collections.defaultdict(lambda: {'passed':0,'total':0})
            for line in archive.extractfile(member):
                r = json.loads(line)
                if r['checkpoint'] != 'cp0':
                    continue
                group = 'file_learned' if r['family'] in learn else 'file_heldout' if r['family'] in held else r['family']
                family[group]['passed'] += int(r['score']==1)
                family[group]['total'] += 1
            totals[member.name] = dict(family)
    result['raw_checkpoints'][str(version)] = totals
assert result['r2']['examples'] == 1900 and result['r2']['unique_tasks'] == 151
assert result['g0']['a0-final-v4-plan']['passed'] == 41 and p == .25
(OUT / 'audit.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k not in ('raw_checkpoints','g0')},indent=2))
