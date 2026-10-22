"""R3b replay data: keep the student's general "reason, then call a tool" behaviour while it learns the R2 tasks.

R3 (v26) showed the LoRA student stopped writing any reasoning before tool calls (135/135 vs 10/157 for the base
model) and lost the transfer families (15/36 -> 1/36). This builds the replay part of the R3b training mix:

- agentnet: desktop GUI steps from xlangai/AgentNet (MIT). Each step becomes one row: the task and a text
  description of the screen (the dataset's `observation`) as the user turn, earlier actions as history, and as
  target the step's `thought` followed by one `computer_action` tool call carrying the natural-language action.
  Only completed, well-aligned trajectories and steps marked correct and not redundant are used. Screenshots and
  pyautogui coordinates are not used (the student acts on accessibility trees, not pixels).
- toucan: first tool-calling turn of Agent-Ark/Toucan-1.5M SFT trajectories (Apache-2.0): reasoning text plus
  real MCP tool calls.

  python replay_data.py --agentnet FILE.jsonl --toucan FILE.parquet --out DIR [--agentnet-n 800] [--toucan-n 600]

Rows are written in the R2 SFT row format (tools, messages, target, source, family) so lora_train.py can mix them
with the R2 rows. Every target has non-empty reasoning text.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import random

SEED = 0
GUI_SYSTEM = ('You are a computer-use assistant operating desktop applications for the user. You see a text '
              'description of the current screen. Think about what the screen shows and what the next step is, '
              'then call computer_action with one concrete action.')
COMPUTER_ACTION = {'type': 'function', 'function': {
    'name': 'computer_action',
    'description': 'Perform one user-interface action, described in words (e.g. click the Save button, type text '
                   'into the search field, press Return).',
    'parameters': {'type': 'object', 'properties': {'action': {'type': 'string'}}, 'required': ['action']}}}


def agentnet_rows(trajectories: list[dict], n: int, max_history: int = 6) -> tuple[list[dict], dict]:
    """One row per accepted step; at most 2 steps per trajectory so no single task dominates."""
    rng = random.Random(SEED)
    stats = {'trajectories': len(trajectories), 'skipped_incomplete': 0, 'steps_rejected': 0}
    candidates = []
    for traj in trajectories:
        if str(traj.get('task_completed')).lower() != 'true' or int(traj.get('alignment_score') or 0) < 7:
            stats['skipped_incomplete'] += 1
            continue
        task = (traj.get('natural_language_task') or traj.get('instruction') or '').strip()
        steps = traj.get('traj') or []
        done, picked = [], []
        for step in steps:
            value = step.get('value') or {}
            ok = (str(value.get('last_step_correct')).lower() == 'true'
                  and str(value.get('last_step_redundant')).lower() != 'true')
            observation, thought, action = (value.get(k, '').strip() for k in ('observation', 'thought', 'action'))
            if ok and task and observation and thought and action:
                history = ''.join(f'\n{i + 1}. {a}' for i, a in enumerate(done[-max_history:]))
                user = (f'Task: {task}\n\nCurrent screen: {observation}'
                        + (f'\n\nActions already taken:{history}' if history else ''))
                picked.append({'family': 'replay_agentnet', 'source': 'agentnet', 'tools': [COMPUTER_ACTION],
                               'messages': [{'role': 'system', 'content': GUI_SYSTEM}, {'role': 'user', 'content': user}],
                               'target': {'role': 'assistant', 'content': thought, 'tool_calls': [
                                   {'type': 'function', 'function': {'name': 'computer_action',
                                                                    'arguments': {'action': action}}}]}})
            else:
                stats['steps_rejected'] += 1
            if action:
                done.append(action)
        rng.shuffle(picked)
        candidates.extend(picked[:2])
    rng.shuffle(candidates)
    stats['candidates'] = len(candidates)
    return candidates[:n], stats


def _tool_call(raw: str) -> dict:
    call = ast.literal_eval(raw) if raw.strip().startswith('{\'') else json.loads(raw)
    args = call.get('arguments') or {}
    if isinstance(args, str):
        args = json.loads(args) if args.strip() else {}
    return {'type': 'function', 'function': {'name': call['name'], 'arguments': args}}


def toucan_rows(records: list[dict], n: int) -> tuple[list[dict], dict]:
    """The first assistant turn that both explains and calls tools (consecutive tool_call messages merged)."""
    rng = random.Random(SEED)
    stats = {'records': len(records), 'no_reasoned_call': 0, 'unparsable': 0}
    out = []
    for rec in records:
        try:
            messages = rec['messages'] if isinstance(rec['messages'], list) else json.loads(rec['messages'])
            tools = rec['tools'] if isinstance(rec['tools'], list) else json.loads(rec['tools'])
            history, target = [], None
            for i, msg in enumerate(messages):
                if msg['role'] == 'assistant':
                    calls = []
                    for nxt in messages[i + 1:]:
                        if nxt['role'] != 'tool_call':
                            break
                        calls.append(_tool_call(nxt['content']))
                    if calls and (msg.get('content') or '').strip():
                        target = {'role': 'assistant', 'content': msg['content'].strip(), 'tool_calls': calls}
                        break
                    history.append({'role': 'assistant', 'content': msg.get('content') or ''})
                elif msg['role'] in ('user', 'system'):
                    history.append({'role': msg['role'], 'content': msg['content']})
                else:
                    break                       # tool traffic before the first reasoned call: keep it simple
        except (ValueError, KeyError, SyntaxError, TypeError):
            stats['unparsable'] += 1
            continue
        if target is None or not history:
            stats['no_reasoned_call'] += 1
            continue
        out.append({'family': 'replay_toucan', 'source': 'toucan', 'tools': tools, 'messages': history,
                    'target': target})
    rng.shuffle(out)
    stats['candidates'] = len(out)
    return out[:n], stats


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--agentnet', type=Path, required=True)
    p.add_argument('--toucan', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--agentnet-n', type=int, default=800)
    p.add_argument('--toucan-n', type=int, default=600)
    args = p.parse_args(argv)
    trajectories = [json.loads(line) for line in args.agentnet.open() if line.strip()]
    if args.toucan.suffix == '.parquet':
        import pandas
        records = pandas.read_parquet(args.toucan).to_dict('records')
    else:
        records = [json.loads(line) for line in args.toucan.open() if line.strip()]
    a_rows, a_stats = agentnet_rows(trajectories, args.agentnet_n)
    t_rows, t_stats = toucan_rows(records, args.toucan_n)
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / 'replay.jsonl'
    with path.open('w') as f:
        for row in a_rows + t_rows:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')
    stats = {'agentnet': {**a_stats, 'kept': len(a_rows)}, 'toucan': {**t_stats, 'kept': len(t_rows)},
             'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
             'sources': {'agentnet': str(args.agentnet.name), 'toucan': str(args.toucan.name)}}
    (args.out / 'replay-stats.json').write_text(json.dumps(stats, indent=1))
    print(json.dumps(stats), flush=True)


if __name__ == '__main__':
    main()
