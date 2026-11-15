#!/usr/bin/env python3
"""v0.9 support: the forgetting-fix chain R3 -> R3g -> R3f -> R3fg in one table and one figure.

  python3 docs/paper/v0.9-support/make_support.py     # -> forgetting-fix.md, forgetting-fix.json, fig5_forgetting_fix.pdf/.png

Reads only the committed analysis.json files (each is rebuilt from raw archives by the analyze.py next to it):
evidence/reports/{r3t-seeds,r3g,r3f,r3fg}/analysis.json. Nothing is typed in by hand.
"""
from pathlib import Path
import json

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
REP = HERE.parents[2] / 'evidence/reports'
A = {d: json.loads((REP / d / 'analysis.json').read_text()) for d in ('r3t-seeds', 'r3g', 'r3f', 'r3fg')}


def frac(text):
    a, b = text.split('/')
    return int(a), int(b)


def readback(runs, seed):
    done = total = 0
    for run, groups in runs.items():
        if run.rsplit('-r', 1)[0] == seed:
            a, b = frac(groups['all'])
            done, total = done + a, total + b
    return f'{done}/{total}'


def misuse(analysis, version, seed):
    """Negative-task executions for one seed: analysis.json only pools them, so recount is left to analyze.py; report pooled."""
    return analysis['negative_misuse']['executions']


# (label, what changed in the data, analysis dir, [(seed key in counts, seed name)], read-back source)
VARIANTS = [
    ('Base student', '—', 'r3t-seeds', [('A0@26', None)], None),
    ('R3', 'guided re-execution, guidance removed', 'r3t-seeds', [('R3@26', None), ('r3t1@41', 'r3t1'), ('r3t2@41', 'r3t2')], ('r3g', 'v41')),
    ('R3g', 'R3 + read-back step after each write', 'r3g', [('r3g0@44', 'r3g0'), ('r3g1@44', 'r3g1')], ('r3g', 'v44')),
    ('R3f', "R3 + 363 rows of the student's own passing code on other programming families", 'r3f', [('r3f0@F', 'r3f0'), ('r3f1@F', 'r3f1')], ('r3f', 'r3f')),
    ('R3fg', 'R3f + read-back step', 'r3fg', [('r3fg0@F', 'r3fg0'), ('r3fg1@F', 'r3fg1')], ('r3fg', 'r3fg')),
]
rows = []
for label, change, source, seeds, rb in VARIANTS:
    for key, seed in seeds:
        c = A[source]['counts'][key]
        row = {'variant': label, 'seed': key, 'change': change, 'learned_file': c['in_family'], 'held_out_file': c['held_out'],
               'learned_web': c.get('learned_web', '—'), 'source': f'evidence/reports/{source}/analysis.json'}
        row['read_back'] = readback(A[rb[0]]['readback'][rb[1]], seed) if rb and seed else '—'
        row['general'] = A[source].get('general', {}).get(seed, '—') if seed else '—'
        rows.append(row)
pooled = {'R3 seeds 1-2': A['r3t-seeds']['negative_misuse'], 'R3g': A['r3g']['negative_misuse'],
          'R3f': A['r3f']['negative_misuse'], 'R3fg': A['r3fg']['negative_misuse']}
repair = {'R3g': A['r3g']['held_out_repair']['v44'], 'R3f': A['r3f']['held_out_repair']['r3f'],
          'R3fg': A['r3fg']['held_out_repair']['r3fg']}
contrasts = {k: {f: A['r3fg']['contrasts'][k][f] for f in ('mean_diff', 'improved', 'worse', 'tied', 'p_fraction', 'boot95')}
             for k in ('r3fg_vs_r3f_in', 'r3fg_vs_r3f_held', 'r3fg_vs_r3t_held', 'r3fg_vs_r3g_held', 'r3fg0_vs_base26_held',
                       'r3fg1_vs_base26_held', 'r3fg0_vs_base26_in', 'r3fg1_vs_base26_in')}
contrasts |= {k: {f: A['r3f']['contrasts'][k][f] for f in ('mean_diff', 'improved', 'worse', 'tied', 'p_fraction', 'boot95')}
              for k in ('r3f_vs_r3t_held', 'r3f_vs_r3g_held')}
(HERE / 'forgetting-fix.json').write_text(json.dumps({'rows': rows, 'negative_misuse_pooled': pooled,
                                                      'held_out_repair': repair, 'contrasts': contrasts}, indent=1))

md = ['| Variant | Seed (run) | Data change | Learned file | Held-out file | Learned web | Read-back (wrote a file, cp0) | General |',
      '|---|---|---|---|---|---|---|---|']
for r in rows:
    md.append(f"| {r['variant']} | `{r['seed']}` | {r['change']} | {r['learned_file']} | {r['held_out_file']} | {r['learned_web']} "
              f"| {r['read_back']} | {r['general']} |")
md += ['', 'Negative-task executions (pooled over the seeds listed, 3 runs each): '
       + '; '.join(f"{k} {v['executions']} ({', '.join(v['tasks']) or 'none'})" for k, v in pooled.items()) + '.', '',
       'Held-out tasks, rewrite after a read-back: '
       + '; '.join(f"{k} {sum(a['rewrite_after_read_back'] for n, a in v.items() if n != 'A0')} rewrites in "
                   f"{sum(a['read_back'] for n, a in v.items() if n != 'A0')} read-backs" for k, v in repair.items()) + '.', '',
       'Task-level exact sign-flip contrasts (mean difference, improved/worse/tied, nominal p):']
md += [f"- `{k}`: {c['mean_diff']:+.2f}, {c['improved']}/{c['worse']}/{c['tied']}, p = {c['p_fraction']}" for k, c in contrasts.items()]
(HERE / 'forgetting-fix.md').write_text('\n'.join(md) + '\n')

plt.rcParams.update({'font.family': 'serif', 'font.serif': ['DejaVu Serif'], 'font.size': 8.5, 'axes.spines.top': False,
                     'axes.spines.right': False, 'pdf.fonttype': 42})
fig, axes = plt.subplots(1, 3, figsize=(7.2, 2.5))
order = ['Base student', 'R3', 'R3g', 'R3f', 'R3fg']
panels = [('learned_file', 'Learned file tasks', 55 / 72), ('held_out_file', 'Held-out file tasks', 12 / 36), ('read_back', 'Read-back after write', None)]
for ax, (field, title, gate) in zip(axes, panels):
    for x, name in enumerate(order):
        ys = [frac(r[field]) for r in rows if r['variant'] == name and r[field] != '—']
        ys = [a / b for a, b in ys if b]
        ax.scatter([x] * len(ys), ys, s=22, color='#1d4ed8' if name in ('R3f', 'R3fg') else '#6b7280', zorder=3)
    if gate:
        ax.axhline(gate, color='#b45309', lw=0.8, ls='--')
    ax.set_xticks(range(len(order)), ['Base', 'R3', 'R3g', 'R3f', 'R3fg'])
    ax.set_ylim(-0.04, 1.04)
    ax.set_title(title)
axes[0].set_ylabel('share (dot = one training seed)')
fig.tight_layout()
for ext in ('pdf', 'png'):
    fig.savefig(HERE / f'fig5_forgetting_fix.{ext}', dpi=200)
print('\n'.join(md))
