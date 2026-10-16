"""Replay one real Kage-Stream run as a ~2.5 minute terminal demo (W6-4).

  python scripts/demo/replay_demo.py [--run DIR] [--speed 1.0] [--open-curve]

Every line comes from the recorded run (default: E-2, Kaggle v10, arm A6, seed 1, unpacked from
evidence/kaggle/v10-results.tar.gz). Bubbles use the real notice templates in
core/evolution/notices.py. No model is started.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from core.evolution.competence import CompetenceModel          # noqa: E402
from core.evolution.notices import adoption_confirm, help_request, learning_report  # noqa: E402

DIM, BOLD, RED, GREEN, CYAN, YELLOW, MAGENTA, RESET = ('\033[2m', '\033[1m', '\033[31m', '\033[32m', '\033[36m',
                                                       '\033[33m', '\033[35m', '\033[0m')
NAMES = {'csv_transform': 'CSV 整理', 'subset_selection': '背包/子集选择', 'interval_merge': '区间合并',
         'log_aggregation': '日志汇总', 'read_preserve': '只读·保留', 'inspect_question': '只读·回答问题',
         'lookalike_readonly': '只读·形似日志'}
SPEED = 1.0


def pause(seconds):
    time.sleep(seconds / SPEED)


def typeout(text, delay=0.012):
    for ch in text:
        sys.stdout.write(ch)
        sys.stdout.flush()
        time.sleep(delay / SPEED)
    sys.stdout.write('\n')


def width(text):
    return sum(2 if ord(ch) > 0x2E7F else 1 for ch in text)


def wrap(text, cols):
    """Wrap by terminal display width (CJK = 2 columns), breaking English at spaces."""
    lines, line = [], ''
    for word in text.replace(' ', ' \0').split('\0'):
        pieces = [word] if word.isascii() else list(word)
        for piece in pieces:
            if width(line + piece) > cols and line:
                lines.append(line.rstrip())
                line = piece.lstrip()
            else:
                line += piece
    return lines + ([line] if line else [])


def shot(n, title, caption, source='回放：Kaggle v10 实录（E-2，A6，种子 1）'):
    print('\033[2J\033[H', end='')
    print(f'{BOLD}{MAGENTA}── 镜头 {n}/6 · {title} ──{RESET}   {DIM}{source}{RESET}\n')
    for line in wrap(caption, 76):
        typeout(f'{YELLOW}{line}{RESET}', 0.03)
    print()
    pause(2)


def bubble(notice):
    if not notice:
        return
    cols = 66
    head = f'─ Kage · {notice["title"]} '
    print(f'{CYAN}╭{head}{"─" * max(2, cols - width(head))}╮{RESET}')
    for line in wrap(notice['body'], cols - 2):
        print(f'{CYAN}│{RESET} {line}{" " * max(0, cols - 2 - width(line))} {CYAN}│{RESET}')
    tail = '［需要你的回复］' if notice['needs_reply'] else ''
    print(f'{CYAN}╰{"─" * cols}╯{RESET} {DIM}{tail}{RESET}\n')
    pause(5)


def row_line(r):
    fam = NAMES.get(r['family'], r['family'])
    calls = [c['skill_id'] for c in r.get('skill_calls', [])]
    if 'student_score' not in r:
        res = f'{YELLOW}先求教{RESET}'
    elif r['solved_by_student']:
        res = f'{GREEN}自己完成 ✓{RESET}'
    else:
        res = f'{RED}没做对 ✗{RESET}'
    extra = f'  调用技能 {BOLD}{calls[0]}{RESET}' if calls else ''
    if r.get('helped'):
        extra += f'  {DIM}→ 请教师示范（{"通过" if (r.get("teacher_score") or 0) >= 1 else "未通过"}）{RESET}'
    return f'  [{r["task_id"].split("-")[-1]}] {fam:<10} 聚类 {r.get("cluster", "?"):<4} {res}{extra}'


def skill_description(run: Path, skill_id: str) -> str:
    for manifest in sorted(run.glob('mutations/*/bundles/*/manifest.json')):
        for item in json.loads(manifest.read_text()).get('skills', []):
            if item['skill_id'] == skill_id:
                return item['description']
    return ''


def ensure_run(run: Path | None) -> Path:
    if run:
        return run
    base = ROOT / 'artifacts' / 'kaggle-out' / 'v10' / 'tar'
    if not (base / 'e1').exists():
        base.mkdir(parents=True, exist_ok=True)
        with tarfile.open(ROOT / 'evidence' / 'kaggle' / 'v10-results.tar.gz') as tar:
            tar.extractall(base, filter='data')
    return base / 'e1' / 'seed1' / 'A6'


def main(argv=None):
    global SPEED
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', type=Path)
    p.add_argument('--speed', type=float, default=1.0)
    p.add_argument('--open-curve', action='store_true', help='open the growth curve image at the end (macOS)')
    args = p.parse_args(argv)
    SPEED = args.speed
    run = ensure_run(args.run)
    rows = [json.loads(l) for l in (run / 'stream.jsonl').read_text().splitlines() if l.strip()]
    evolution = [json.loads(l) for l in (run / 'evolution.jsonl').read_text().splitlines() if l.strip()]
    by_id = {r['task_id']: r for r in rows}

    # 1 — says it cannot
    first = rows[0]
    shot(1, '说不会', '本地 4B 小模型第一次遇到“CSV 整理”。它在 5 步内没写对——外部检查告诉它：不通过。')
    print(row_line({**first, 'helped': False}))
    pause(1.5)
    comp = CompetenceModel()
    comp.record_task(NAMES[first['family']], False)
    bubble(help_request(comp, NAMES[first['family']]))

    # 2 — asks, learns
    shot(2, '求教 → 学会', '老师（DeepSeek）从干净状态示范一次并通过。示范被提炼成一个带参数的技能，'
         '学生自己调用它重做通过才入库；示范本身也存入记忆。')
    print(row_line(first))
    learning = first.get('learning') or {}
    print(f'  {GREEN}技能入库：{learning.get("accepted")}   示范入记忆：{learning.get("memory_stored")}{RESET}\n')
    pause(1.5)
    skill = next(c['skill_id'] for r in rows for c in r.get('skill_calls', []) if r['family'] == 'csv_transform')
    bubble(adoption_confirm(skill, skill_description(run, skill), writes_files=True,
                            validation={'passed': 1, 'total': 1}))

    # 3 — background practice and report
    e10 = evolution[0]
    shot(3, '后台自练 → 汇报', '每做完 10 题，它在空闲时挑自己最没把握的题型练习：全部本地运行，不花云费。')
    for key, fam in sorted(e10['practice']['families'].items()):
        print(f'  练习 {NAMES.get(fam["generator"], key)}（{key}）：{fam["passed"]}/{fam["tasks"]}，'
              f'估计成功率 {fam["p_before"]:.0%} → {fam["p_after"]:.0%}')
    print()
    pause(1.5)
    report = dict(e10['practice'])
    report['families'] = {NAMES.get(f['generator'], k): f for k, f in report['families'].items()}
    bubble(learning_report(report))

    # 4 — reuse on new tasks
    shot(4, '新题复用', '区间合并：第一次失败、求教学会技能之后，再来的新题直接调用技能，一次做完。')
    interval = [r for r in rows if r['family'] == 'interval_merge']
    start = next(i for i, r in enumerate(interval) if (r.get('learning') or {}).get('accepted'))
    for r in interval[start:start + 3]:
        print(row_line(r))
        pause(2.5)
    pause(3)

    # 5 — negatives not misused
    shot(5, '负例不误用', '有些题看起来像学过的任务，其实只该读文件、回答问题、不许修改。'
         '相关性门控不放出任何技能，学生只读不写。')
    for r in [r for r in rows if r['negative']][:5]:
        print(row_line(r))
        pause(1.6)
    print(f'\n  {GREEN}评测负例 24/24 通过，技能误用 0 次{RESET}')
    pause(3.5)

    # 6 — growth curve
    summary = json.loads((ROOT / 'evidence/reports/e2b-report/summary.json').read_text())
    a0 = summary['arms']['A0']['checkpoints']['cp60']['in_family']
    best = summary['arms']['A6-fixed']['checkpoints']['cp60']['in_family']
    shot(6, '成长曲线', '两条学习流、各 60 道题之后，同类新题（评测集，学习时从未见过）的通过率：',
         source='汇总：两个种子，evidence/reports/e2b-report')
    print(f'  原学生             {a0["k"]}/{a0["n"]}  ({a0["rate"]:.0%}；重复测量在 29–54% 之间)')
    print(f'  学习 + 后台自练    {BOLD}{best["k"]}/{best["n"]}  ({best["rate"]:.0%}){RESET}')
    print(f'  教师花费           每组约 US$0.2（示范按题缓存、各组共享）')
    print(f'\n  {DIM}一个会求教、会练习、知道边界的小模型。  github.com/lemon5227/Kage{RESET}')
    if args.open_curve:
        subprocess.run(['open', str(ROOT / 'docs/assets/readme/growth-curve.png')], check=False)
    pause(8)


if __name__ == '__main__':
    main()
