"""C1.1 local model drives real Chromium; actual backend record decides success."""
import argparse
import asyncio
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import subprocess
import time
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from playwright.async_api import async_playwright
from core.agentic_loop import AgenticLoop
from core.computer_use.browser import BrowserAdapter
from core.evolution.agent_provider import ExperimentIdentityStore, HistorySession, MeteredProvider
from core.prompt_builder import PromptBuilder
from core.tool_executor import ToolExecutor
from core.tool_registry import ToolRegistry
from scripts.experiments.browser_fixture import profile_server,HTML_PATH
from scripts.experiments.task_suite import RecordedLocalProvider

SOUL='''You are Kage, completing a browser task through the provided tools.
Use browser_observe to inspect the current page. Use only current observation_id and target_ref returned by tools.
Every action returns a new observation: use its ID for the next action. If stale, use the returned fresh observation.
Fill the exact requested value, then click the observed save button. Use browser_act wait to confirm the saved text.
Only report what you actually observed. Tool success alone does not prove the task is complete. No JavaScript or selectors.
'''
GOAL='On the current Profile editor page, fill Name with "Wenbo Browser Lab", save the profile, then confirm the saved name from the page.'


async def pilot(args):
    args.output_dir.mkdir(parents=True,exist_ok=False)
    rows=[]
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        config={'model':'agents-a1-4b','cloud':False,'temperature':0,'max_calls':6,'max_steps':5,'cooperative_timeout_s':150,'http_timeout_s':120,
                'repeats':3,'goal':GOAL,'browser':browser.version,'html_sha256':hashlib.sha256(HTML_PATH.read_bytes()).hexdigest(),
                'prompt_sha256':hashlib.sha256(SOUL.encode()).hexdigest(),
                'adapter_sha256':hashlib.sha256((ROOT/'core/computer_use/browser.py').read_bytes()).hexdigest(),
                'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'git_revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()}
        (args.output_dir/'config.json').write_text(json.dumps(config,indent=2))
        try:
            for repeat in range(3):
                with profile_server() as (url,state):
                    context=await browser.new_context()
                    page=await context.new_page()
                    try:
                        await page.goto(url,wait_until='domcontentloaded')
                        adapter=BrowserAdapter(page,trace_path=args.output_dir/f'browser-{repeat}.jsonl')
                        registry=ToolRegistry();adapter.register_tools(registry)
                        model=MeteredProvider(RecordedLocalProvider(args.output_dir/f'model-{repeat}.jsonl',api_key='local',model_name='agents-a1-4b',base_url=f'http://127.0.0.1:{args.port}/v1',timeout_sec=120),label='agents-a1-4b',max_calls=6)
                        builder=PromptBuilder(ExperimentIdentityStore(SOUL),None,registry,prune_tools=False,memory_cfg={'recall_enabled':False})
                        loop=AgenticLoop(model,ToolExecutor(registry,str(args.output_dir)),builder,HistorySession())
                        start=time.monotonic();result=None;error=None
                        try:
                            result=await asyncio.wait_for(loop.run(GOAL),timeout=150)
                        except Exception as exc:
                            error=f'{type(exc).__name__}: {exc}'
                        # Independent read-only check; no extra agent action or answer injection.
                        record=await (await page.request.get(url+'/record')).json()
                        fresh=await adapter.observe()
                        passed=record=={'name':'Wenbo Browser Lab'} and 'Saved: Wenbo Browser Lab' in fresh['text']
                        row={'repeat':repeat,'status':'passed' if passed else 'failed','score':int(passed),'seconds':round(time.monotonic()-start,3),
                             'backend_record':record,'backend_posts':state['posts'],'model_calls':len(model.calls),'usage':model.calls,
                             'loop_result':asdict(result) if result else None,'error':error,'final_observation':fresh}
                        rows.append(row)
                        (args.output_dir/'results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
                        await page.screenshot(path=str(args.output_dir/f'final-{repeat}.png'))
                        print(json.dumps({k:row[k] for k in ['repeat','status','score','seconds','model_calls','backend_record','error']},ensure_ascii=False),flush=True)
                    finally: await context.close()
        finally: await browser.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--port',type=int,default=18082)
    asyncio.run(pilot(parser.parse_args()))


if __name__=='__main__': main()
