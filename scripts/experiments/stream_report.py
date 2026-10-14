"""Kage-Stream report: checkpoints, paired tests, learning stream, help quality.

  python scripts/experiments/stream_report.py --arm-dir A0=artifacts/e1/seed1/A0 \
      --arm-dir A4=artifacts/e1/seed1/A4 --arm-dir A4=artifacts/e1/seed2/A4 ... --out artifacts/e1/report

The same arm may be given several directories (seeds); instances are keyed by
(directory position, task_id), so arm X's i-th directory is paired with arm Y's i-th.
Formulas are fixed by the W1-10 card; this script never reruns or rescores anything.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from math import comb, sqrt
from pathlib import Path

Z = 1.96
PAIRS = [('A4', 'A0'), ('A4', 'A1'), ('A4', 'A3'), ('A5', 'A4'), ('A6', 'A5'), ('A6', 'A6-fixed')]
RETENTION_FAMILY = 'subset_selection'   # F1 carries the old knapsack ability


def wilson(k: int, n: int) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    center = (p + Z * Z / (2 * n)) / (1 + Z * Z / n)
    half = Z * sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / (1 + Z * Z / n)
    return (max(0.0, center - half), min(1.0, center + half))


def mcnemar_exact(b: int, c: int) -> float:
    n = b + c
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(comb(n, i) for i in range(min(b, c) + 1)) * 0.5 ** n)


def _jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def load_arm(dirs: list[Path]) -> dict:
    checkpoints, stream, spend, help_log = [], [], [], []
    for pos, root in enumerate(dirs):
        for row in _jsonl(root / 'checkpoints.jsonl'):
            checkpoints.append({**row, 'key': (pos, row['task_id'])})
        for row in _jsonl(root / 'stream.jsonl'):
            stream.append({**row, 'seed_pos': pos})
        for row in _jsonl(root / 'spend.jsonl'):
            spend.append({**row, 'seed_pos': pos})
        comp = root / 'competence.json'
        if comp.exists():
            help_log += [{**h, 'seed_pos': pos} for h in json.loads(comp.read_text()).get('help_log', [])]
    return {'checkpoints': checkpoints, 'stream': stream, 'spend': spend, 'help_log': help_log}


def _cp_order(label: str) -> int:
    return int(label[2:]) if label.startswith('cp') and label[2:].isdigit() else 10**9


def _rate(rows: list[dict]) -> dict:
    k, n = sum(r['score'] >= 1.0 for r in rows), len(rows)
    lo, hi = wilson(k, n)
    return {'k': k, 'n': n, 'rate': (k / n) if n else None, 'ci95': [round(lo, 4), round(hi, 4)]}


def checkpoint_table(arm: dict) -> dict:
    learned = {r['family'] for r in arm['stream'] if not r.get('negative')}
    by_cp = defaultdict(list)
    for row in arm['checkpoints']:
        by_cp[row['checkpoint']].append(row)
    out = {}
    for cp in sorted(by_cp, key=_cp_order):
        rows = by_cp[cp]
        neg = [r for r in rows if r.get('negative')]
        cap = [r for r in rows if not r.get('negative')]
        out[cp] = {'in_family': _rate([r for r in cap if r['family'] in learned or not learned]),
                   'cross_family': _rate([r for r in cap if learned and r['family'] not in learned]),
                   'negative': _rate(neg),
                   'misuse': {'k': sum(bool(r.get('misuse')) for r in neg), 'n': len(neg)},
                   'retention_f1': _rate([r for r in cap if r['family'] == RETENTION_FAMILY])}
    return out


def paired(a: dict, b: dict) -> dict:
    out = {}
    index_a = {(r['checkpoint'], r['key']): r['score'] >= 1.0 for r in a['checkpoints']}
    index_b = {(r['checkpoint'], r['key']): r['score'] >= 1.0 for r in b['checkpoints']}
    for cp in sorted({k[0] for k in index_a} & {k[0] for k in index_b}, key=_cp_order):
        keys = [k for k in index_a if k[0] == cp and k in index_b]
        bb = sum(index_a[k] and not index_b[k] for k in keys)
        cc = sum(index_b[k] and not index_a[k] for k in keys)
        out[cp] = {'pairs': len(keys), 'a_only': bb, 'b_only': cc, 'p': round(mcnemar_exact(bb, cc), 6)}
    return out


def stream_blocks(arm: dict, block: int = 10) -> list[dict]:
    spend_by_task = defaultdict(dict)
    for row in arm['spend']:
        spend_by_task[(row['seed_pos'], row['task_id'])][row['when']] = row['ledger_remaining_usd']
    rows = sorted(arm['stream'], key=lambda r: (r['seed_pos'], r['index']))
    out, cumulative = [], defaultdict(float)
    by_block = defaultdict(list)
    for row in rows:
        by_block[row['index'] // block].append(row)
    for b in sorted(by_block):
        chunk = by_block[b]
        attempted = [r for r in chunk if r.get('student_score') is not None]
        cost = 0.0
        for r in chunk:
            s = spend_by_task.get((r['seed_pos'], r['task_id']), {})
            if 'before' in s and 'after' in s:
                cost += max(0.0, s['before'] - s['after'])
        cumulative['usd'] += cost
        out.append({'tasks': f'{b * block}-{b * block + block - 1}', 'n': len(chunk),
                    'student_solved': sum(bool(r.get('solved_by_student')) for r in chunk),
                    'student_attempted': len(attempted),
                    'teacher_calls': sum(bool(r.get('helped')) for r in chunk),
                    'skills_accepted': sum(bool((r.get('learning') or {}).get('accepted')) for r in chunk),
                    'cloud_usd': round(cost, 6), 'cumulative_cloud_usd': round(cumulative['usd'], 6)})
    return out


def help_quality(arm: dict) -> dict:
    counts = defaultdict(int)
    for h in arm['help_log']:
        if h.get('asked'):
            counts[h.get('when', 'unknown')] += 1
    rows = sorted(arm['stream'], key=lambda r: (r['seed_pos'], r['index']))
    last_student = {}
    precise = asked_before = missed = 0
    for row in rows:
        fam = (row['seed_pos'], row['family'])
        asked = 'student_score' not in row and bool((row.get('help_decision') or {}).get('ask'))
        if asked:
            asked_before += 1
            precise += last_student.get(fam) is False
        elif row.get('student_score') is not None:
            missed += not row.get('solved_by_student') and not row.get('help_requested')
            last_student[fam] = bool(row.get('solved_by_student'))
    return {'before_attempt': counts['before_attempt'], 'student_requested': counts['student_requested'],
            'after_failure': counts['after_failure'], 'asked_before_tasks': asked_before,
            'precision_before': (precise / asked_before) if asked_before else None,
            'missed_asks': missed}


def _fmt(r: dict) -> str:
    if not r['n']:
        return '无数据'
    return f"{r['k']}/{r['n']} ({r['rate']:.0%}, CI {r['ci95'][0]:.2f}–{r['ci95'][1]:.2f})"


def build(arms: dict[str, list[Path]]) -> dict:
    data = {name: load_arm(dirs) for name, dirs in arms.items()}
    summary = {'arms': {}, 'paired': {}}
    for name, arm in data.items():
        summary['arms'][name] = {'checkpoints': checkpoint_table(arm), 'stream': stream_blocks(arm),
                                 'help': help_quality(arm)}
    for a, b in PAIRS:
        if a in data and b in data:
            summary['paired'][f'{a} vs {b}'] = paired(data[a], data[b])
    return summary


def render(summary: dict, plotted: bool) -> str:
    lines = ['# Kage-Stream report', '', '## 检查点', '',
             '| 臂 | 检查点 | 族内 | 跨族 | 负例通过 | 误用 | F1 保留 |', '|---|---|---|---|---|---|---|']
    for name, arm in summary['arms'].items():
        if not arm['checkpoints']:
            lines.append(f'| {name} | 无数据 | | | | | |')
        for cp, r in arm['checkpoints'].items():
            mis = f"{r['misuse']['k']}/{r['misuse']['n']}" if r['misuse']['n'] else '无数据'
            lines.append(f"| {name} | {cp} | {_fmt(r['in_family'])} | {_fmt(r['cross_family'])} | "
                         f"{_fmt(r['negative'])} | {mis} | {_fmt(r['retention_f1'])} |")
    lines += ['', '## 配对比较（McNemar 精确）', '', '| 比较 | 检查点 | 配对数 | 仅前者过 | 仅后者过 | p |', '|---|---|---|---|---|---|']
    for pair, cps in summary['paired'].items():
        for cp, r in cps.items():
            lines.append(f"| {pair} | {cp} | {r['pairs']} | {r['a_only']} | {r['b_only']} | {r['p']:.4g} |")
    lines += ['', '## 学习流（每 10 个任务）', '',
              '| 臂 | 任务 | 学生独立成功/尝试 | 教师调用 | 接受技能 | 云费 | 累计云费 |', '|---|---|---|---|---|---|---|']
    for name, arm in summary['arms'].items():
        for b in arm['stream']:
            lines.append(f"| {name} | {b['tasks']} | {b['student_solved']}/{b['student_attempted']} | {b['teacher_calls']} | "
                         f"{b['skills_accepted']} | ${b['cloud_usd']:.4f} | ${b['cumulative_cloud_usd']:.4f} |")
    lines += ['', '## 求教质量', '', '| 臂 | 事前求教 | 学生请求 | 失败后求教 | 事前求教精准率 | 漏问 |', '|---|---|---|---|---|---|']
    for name, arm in summary['arms'].items():
        h = arm['help']
        prec = '无数据' if h['precision_before'] is None else f"{h['precision_before']:.0%}"
        lines.append(f"| {name} | {h['before_attempt']} | {h['student_requested']} | {h['after_failure']} | {prec} | {h['missed_asks']} |")
    lines += ['', '精准率（近似）= 事前求教的任务中，同族上一次学生独立尝试失败的比例；漏问 = 未求教、学生自己也没请求帮助、且失败的任务数。']
    if not plotted:
        lines += ['', '（未生成 curves.png：当前环境没有 matplotlib。）']
    return '\n'.join(lines) + '\n'


def plot(summary: dict, path: Path) -> bool:
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    fig, ax = plt.subplots(figsize=(6, 4))
    for name, arm in summary['arms'].items():
        cps = [(cp, r['in_family']) for cp, r in arm['checkpoints'].items() if r['in_family']['n']]
        if not cps:
            continue
        xs = [_cp_order(cp) for cp, _ in cps]
        ys = [r['rate'] for _, r in cps]
        err = [[y - r['ci95'][0] for y, (_, r) in zip(ys, cps)], [r['ci95'][1] - y for y, (_, r) in zip(ys, cps)]]
        ax.errorbar(xs, ys, yerr=err, marker='o', capsize=3, label=name)
    ax.set_xlabel('stream tasks seen (checkpoint)')
    ax.set_ylabel('in-family success rate')
    ax.set_ylim(0, 1)
    if ax.lines:
        ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return True


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--arm-dir', action='append', required=True, help='ARM=DIR; repeat for arms and seeds')
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args(argv)
    arms: dict[str, list[Path]] = defaultdict(list)
    for item in args.arm_dir:
        name, _, path = item.partition('=')
        if not name or not path:
            p.error(f'--arm-dir expects ARM=DIR, got {item!r}')
        arms[name].append(Path(path))
    args.out.mkdir(parents=True, exist_ok=True)
    summary = build(dict(arms))
    plotted = plot(summary, args.out / 'curves.png')
    (args.out / 'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    (args.out / 'report.md').write_text(render(summary, plotted))
    print(args.out / 'report.md')


if __name__ == '__main__':
    main()
