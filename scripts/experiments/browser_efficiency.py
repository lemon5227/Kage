"""Frozen alternating real-agent comparison; backend and DOM decide success."""
import argparse
import asyncio
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from playwright.async_api import async_playwright
from core.agentic_loop import AgenticLoop
from core.computer_use.browser import BrowserAdapter
from core.evolution.agent_provider import ExperimentIdentityStore, HistorySession, MeteredProvider
from core.prompt_builder import PromptBuilder
from core.tool_executor import ToolExecutor
from core.tool_registry import ToolRegistry
from scripts.experiments.browser_dom_pilot import SOUL as BASELINE_SOUL, GOAL
from scripts.experiments.browser_fixture import profile_server, HTML_PATH
from scripts.experiments.task_suite import RecordedLocalProvider

OPTIMIZED_SOUL = '''You are Kage, completing a browser task through the provided tools.
The runtime supplies an initial DOM observation. Use only current observation_id and target_ref.
Every browser action returns a fresh observation: reuse it for the next action or to confirm the result.
Do not request browser_observe again when the current observation already contains what you need.
If stale, use the fresh observation returned with the error. Wait for visible text if the page is still loading.
Compact-v1 omits false checked/disabled and null target properties; other values and geometry are unchanged.
Only report what you actually observed. Tool success alone does not prove completion. No JavaScript or selectors.
'''
ORDER = [('baseline', 'optimized'), ('optimized', 'baseline'), ('baseline', 'optimized')]


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


async def trial(browser, args, arm, pair):
    run_id = f'{pair}-{arm}'
    directory = args.output_dir / run_id
    directory.mkdir()
    setup_start = time.monotonic()
    with profile_server() as (url, state):
        context = await browser.new_context()
        try:
            page = await context.new_page()
            await page.goto(url, wait_until='domcontentloaded')
            adapter = BrowserAdapter(page, trace_path=directory/'browser.jsonl', compact_observations=arm=='optimized')
            registry = ToolRegistry(); adapter.register_tools(registry)
            model = MeteredProvider(RecordedLocalProvider(directory/'model.jsonl', api_key='local', model_name='agents-a1-4b',
                        base_url=f'http://127.0.0.1:{args.port}/v1', timeout_sec=120), label='agents-a1-4b', max_calls=6)
            soul = OPTIMIZED_SOUL if arm=='optimized' else BASELINE_SOUL
            builder = PromptBuilder(ExperimentIdentityStore(soul), None, registry, prune_tools=False, memory_cfg={'recall_enabled':False})
            loop = AgenticLoop(model, ToolExecutor(registry, str(directory)), builder, HistorySession())
            setup_ms = (time.monotonic()-setup_start)*1000
            start = time.monotonic(); bootstrap_ms = 0; result = None; error = None
            try:
                instruction = GOAL
                if arm=='optimized':
                    bootstrap_start = time.monotonic()
                    observation = await adapter.observe()
                    bootstrap_ms = (time.monotonic()-bootstrap_start)*1000
                    (directory/'initial-observation.json').write_text(json.dumps(observation, ensure_ascii=False, indent=2))
                    instruction += '\nInitial browser observation supplied by runtime:\n' + json.dumps(observation, ensure_ascii=False, separators=(',', ':'))
                result = await asyncio.wait_for(loop.run(instruction), timeout=150)
            except Exception as exc:
                error = f'{type(exc).__name__}: {exc}'
            agent_ms = (time.monotonic()-start)*1000
            check_start = time.monotonic()
            record = None; fresh = None; check_error = None
            try:
                record = await (await page.request.get(url+'/record', timeout=10000)).json()
                fresh = await adapter.observe()
            except Exception as exc:
                check_error = f'{type(exc).__name__}: {exc}'
            passed = record=={'name':'Wenbo Browser Lab'} and fresh is not None and 'Saved: Wenbo Browser Lab' in fresh['text'] and state['posts']==1
            check_ms = (time.monotonic()-check_start)*1000
            log = directory/'tool_log.jsonl'
            tool_rows = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
            model_ms = sum(call['elapsed_ms'] for call in model.calls)
            tool_ms = sum(row['elapsed_ms'] for row in tool_rows)
            row = {'pair':pair, 'arm':arm, 'status':'passed' if passed else 'failed', 'score':int(passed),
                   'timing_ms':{'setup':round(setup_ms,3), 'agent':round(agent_ms,3), 'bootstrap':round(bootstrap_ms,3),
                                'model':round(model_ms,3), 'tool_handlers':round(tool_ms,3), 'check':round(check_ms,3),
                                'remaining_agent':round(agent_ms-bootstrap_ms-model_ms-tool_ms,3)},
                   'seconds':round((agent_ms+check_ms)/1000,3), 'backend_record':record, 'backend_posts':state['posts'],
                   'model_calls':len(model.calls), 'totals':model.totals, 'usage':model.calls, 'tool_calls':len(tool_rows),
                   'loop_result':asdict(result) if result else None, 'error':error, 'check_error':check_error, 'final_observation':fresh}
            (directory/'result.json').write_text(json.dumps(row, ensure_ascii=False, indent=2))
            try:
                await page.screenshot(path=str(directory/'final.png'), timeout=10000)
            except Exception as exc:
                (directory/'screenshot-error.txt').write_text(f'{type(exc).__name__}: {exc}')
            return row
        finally:
            await context.close()


async def recorded_trial(browser, args, arm, pair):
    """Keep setup/cleanup failures in the denominator and retain checked results."""
    started = time.monotonic()
    path = args.output_dir / f'{pair}-{arm}' / 'result.json'
    try:
        row = await trial(browser, args, arm, pair)
    except Exception as exc:
        # trial checkpoints its independently checked outcome before cleanup.
        # A failed close must not erase that outcome or invent a new score.
        row = json.loads(path.read_text()) if path.exists() else {
            'pair': pair, 'arm': arm, 'status': 'failed', 'score': 0,
            'seconds': None, 'model_calls': None, 'totals': {}, 'timing_ms': {},
            'error': None, 'check_error': None,
        }
        row['lifecycle_error'] = f'{type(exc).__name__}: {exc}'
    row['lifecycle_elapsed_ms'] = round((time.monotonic() - started) * 1000, 3)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(row, ensure_ascii=False, indent=2))
    return row


async def main_async(args):
    args.output_dir.mkdir(parents=True, exist_ok=False)
    config = {'model':'agents-a1-4b', 'cloud':False, 'temperature':0, 'max_calls':6, 'max_steps':5,
              'http_timeout_s':120, 'cooperative_timeout_s':150, 'order':ORDER, 'goal':GOAL,
              'source_hashes':{str(path.relative_to(ROOT)):file_hash(path) for path in [Path(__file__).resolve(), ROOT/'core/computer_use/browser.py',
                      ROOT/'scripts/experiments/browser_dom_pilot.py', ROOT/'scripts/experiments/browser_fixture.py', ROOT/'scripts/experiments/task_suite.py', HTML_PATH]},
              'prompt_hashes':{arm:hashlib.sha256(soul.encode()).hexdigest() for arm,soul in [('baseline',BASELINE_SOUL),('optimized',OPTIMIZED_SOUL)]},
              'model_sha256':file_hash(args.model_path), 'git_revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
              'timing_definition':'agent includes bootstrap and full loop; seconds includes external check; setup and screenshot excluded; tool_handlers excludes logging tail; remaining includes orchestration/unmetered exceptions',
              'server_settings':{'context':8192, 'parallel':1, 'flash_attention':'auto', 'gpu_layers':99, 'reasoning':'off', 'kv_cache':'q8_0'}}
    # Protocol persisted before any model request; source hashes include uncommitted script.
    (args.output_dir/'config.json').write_text(json.dumps(config, ensure_ascii=False, indent=2))
    rows=[]
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        config['browser']=browser.version
        (args.output_dir/'config.json').write_text(json.dumps(config, ensure_ascii=False, indent=2))
        try:
            for pair,arms in enumerate(ORDER):
                for arm in arms:
                    row=await recorded_trial(browser,args,arm,pair)
                    rows.append(row)
                    (args.output_dir/'results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
                    print(json.dumps({k:row.get(k) for k in ['pair','arm','status','seconds','model_calls','totals','timing_ms','error','check_error','lifecycle_error']},ensure_ascii=False),flush=True)
        finally:
            await browser.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--port',type=int,default=18082)
    parser.add_argument('--model-path',type=Path,default=Path.home()/'.kage/models/agents-a1-4b/Agents-A1-4B-Q4_K_M.gguf')
    asyncio.run(main_async(parser.parse_args()))


if __name__=='__main__': main()
