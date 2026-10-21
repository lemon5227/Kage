"""T6: per-checkbox intent extraction (enable / disable / leave unchanged) from the settings instruction."""
import json, sys
sys.path.insert(0, sys.argv[1])
from core.evolution.stream_tasks import FAMILIES
out = []
for s in range(9000, 9080):
    t = FAMILIES['web_prefs'](s)
    instr = t['instruction']
    for f in t['fixture']['fields']:
        lab = f['label']
        gold = ('enable' if f'enable' in instr and lab in instr.split('disable')[0] else
                'disable' if 'disable' in instr and lab in instr.split('disable', 1)[-1] else 'unchanged')
        if lab not in instr: gold = 'unchanged'
        out.append({'task': 'T6_item_intent', 'id': f'web_prefs-{s}-{f["name"]}', 'state': instr,
                    'questions': {'q': {'type': 'choice', 'question': f'What does the task ask for the "{lab}" checkbox?',
                        'criteria': {'enable': f'turn "{lab}" on', 'disable': f'turn "{lab}" off',
                                     'unchanged': f'"{lab}" is not mentioned; leave it as it is'}}},
                    'gold': {'q': gold}})
open(sys.argv[2], 'w').write(''.join(json.dumps(x) + '\n' for x in out)); print(len(out))
