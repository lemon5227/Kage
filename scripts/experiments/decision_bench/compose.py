"""T3/T4 by composition: THX-01 per-checkbox intents (T6 results) + a deterministic state compare."""
import json, re, sys
sys.path.insert(0, sys.argv[1])
from core.evolution.stream_tasks import FAMILIES

pred = {r['id']: r['pred'] for r in json.load(open(sys.argv[3]))}
ok3 = ok4 = n3 = n4 = 0
for b in map(json.loads, open(sys.argv[2])):
    if b['task'] not in ('T3_settings_check', 'T4_next_action'):
        continue
    s = int(b['id'].split('-')[1])
    t = FAMILIES['web_prefs'](s)
    labels = {f['label']: f['name'] for f in t['fixture']['fields']}
    cur = {labels[m.group(1)]: m.group(2) == 'on' for m in re.finditer(r'- (.+): (on|off)', b['state'])}
    init = {f['name']: f['initial'] for f in t['fixture']['fields']}
    goal = {n: {'enable': True, 'disable': False}.get(pred[f'web_prefs-{s}-{n}'], init[n]) for n in init}
    wrong = [n for n in goal if goal[n] != cur[n]]
    if b['task'] == 'T3_settings_check':
        n3 += 1; ok3 += (not wrong) == b['gold']['q']
    else:
        n4 += 1; ok4 += (wrong[0] if wrong else 'save') in b['gold']['q']
print(f'T3 via extract+compare acc={ok3 / n3:.2f}  T4 via extract+compare acc={ok4 / n4:.2f}')
