"""Build a labeled decision benchmark from Kage's seeded generators (eval seeds 9000+).
Each item: {task, id, state, questions, gold} where gold maps question id -> correct answer
(choice key, or bool for noul). Written as JSON lines for any decision model."""
import json, random, sys
sys.path.insert(0, sys.argv[1])
from core.evolution.stream_tasks import FAMILIES, NEGATIVE_FAMILIES
from core.evolution.browser_tasks import BROWSER_NEGATIVE

NEG = NEGATIVE_FAMILIES | BROWSER_NEGATIVE
SEEDS = range(9000, 9030)
DESCR = {
    'log_aggregation': 'count log lines by level or service',
    'subset_selection': 'pick items under a capacity to maximise value (knapsack)',
    'interval_merge': 'merge overlapping intervals',
    'csv_transform': 'clean, filter and sort CSV rows',
    'text_normalize': 'turn text into a normalised slug',
    'config_migrate': 'rename and regroup configuration keys',
    'read_preserve': 'read a file and summarise it without editing',
    'inspect_question': 'answer a question about code without editing',
    'lookalike_readonly': 'explain an existing correct implementation without editing',
    'web_form': 'fill in and submit a web form',
    'web_invoice': 'compute an invoice total on a web page and save it',
    'web_prefs': 'change notification checkboxes on a settings page and save',
    'web_catalog': 'choose a hotel from a web catalog by rules',
    'web_lookup': 'read a value from a web page without changing anything',
}
out = []

# T1: does the request ask for a change (write) or only reading?
for fam, fn in FAMILIES.items():
    for s in list(SEEDS)[:12]:
        t = fn(s)
        out.append({'task': 'T1_write_or_read', 'id': f'{fam}-{s}', 'state': t['instruction'],
                    'questions': {'q': {'type': 'noul', 'question':
                        'Does this request ask to create, modify or save something (rather than only read or answer)?'}},
                    'gold': {'q': fam not in NEG}})

# T2: route the request to its task type (14 options)
for fam, fn in FAMILIES.items():
    for s in list(SEEDS)[12:20]:
        t = fn(s)
        out.append({'task': 'T2_route', 'id': f'{fam}-{s}', 'state': t['instruction'],
                    'questions': {'q': {'type': 'choice', 'question': 'Which kind of task is this request?',
                                        'criteria': DESCR}}, 'gold': {'q': fam}})

def prefs_state(t, current):
    labels = {f['name']: f['label'] for f in t['fixture']['fields']}
    rows = '\n'.join(f'- {labels[n]}: {"on" if v else "off"}' for n, v in current.items())
    return f'Task: {t["instruction"]}\nCurrent checkbox states on the page:\n{rows}'

# T3: checker - is the settings page now in the requested state? (half correct, half one item wrong)
rng = random.Random(7)
for s in range(9000, 9080):
    t = FAMILIES['web_prefs'](s)
    want = dict(t['expected']['record'])
    ok = s % 2 == 0
    cur = dict(want)
    if not ok:
        n = rng.choice(list(cur)); cur[n] = not cur[n]
    out.append({'task': 'T3_settings_check', 'id': f'web_prefs-{s}', 'state': prefs_state(t, cur),
                'questions': {'q': {'type': 'noul', 'question':
                    'Do the current checkbox states fully satisfy the task (every requested change done, nothing else changed)?'}},
                'gold': {'q': ok}})

# T4: next action on the settings page (mid-task): toggle one specific checkbox, or Save when done
for s in range(9000, 9080):
    t = FAMILIES['web_prefs'](s)
    init = {f['name']: f['initial'] for f in t['fixture']['fields']}
    want = t['expected']['record']
    todo = [n for n in want if want[n] != init[n]]
    cur = dict(init)
    k = random.Random(s).randint(0, len(todo))   # done k of the needed changes
    for n in todo[:k]:
        cur[n] = want[n]
    remaining = [n for n in todo[k:]]
    labels = {f['name']: f['label'] for f in t['fixture']['fields']}
    crit = {n: f'click the "{labels[n]}" checkbox' for n in labels}
    crit['save'] = f'click "{t["fixture"]["submit"]}" because every requested change is already done'
    out.append({'task': 'T4_next_action', 'id': f'web_prefs-{s}', 'state': prefs_state(t, cur),
                'questions': {'q': {'type': 'choice', 'question': 'What is the correct next action?', 'criteria': crit}},
                'gold': {'q': remaining or ['save']}})   # any remaining needed toggle is correct

# T5: invoice rule application - is this row included in the total?
for s in range(9000, 9060):
    t = FAMILIES['web_invoice'](s)
    rows = t['fixture']['rows']
    instr = t['instruction']
    r = random.Random(s).choice(rows)
    import re
    m = re.search(r'except (\w+) and (\w+)', instr)
    m2 = re.search(r'at least (\d+)', instr)
    inc = (r['item'] not in m.groups()) if m else (r['price'] >= int(m2.group(1)) if m2 else True)
    table = '\n'.join(f'{x["item"]}: qty {x["qty"]}, unit price {x["price"]}' for x in rows)
    out.append({'task': 'T5_invoice_row_rule', 'id': f'web_invoice-{s}-{r["item"]}',
                'state': f'Task: {instr}\nRows:\n{table}',
                'questions': {'q': {'type': 'noul', 'question': f'Should the row "{r["item"]}" be counted in the invoice total?'}},
                'gold': {'q': inc}})

with open(sys.argv[2], 'w') as f:
    for x in out:
        f.write(json.dumps(x) + '\n')
from collections import Counter
print(Counter(x['task'] for x in out))
