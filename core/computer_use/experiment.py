"""Browser chain inside the existing isolated EvolutionRunner worker."""
import asyncio
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from core.agentic_loop import AgenticLoop
from core.computer_use.browser import BrowserAdapter
from core.computer_use.task_environment import browser_task_server,checkpoint,atomic_json
from core.evolution.agent_provider import KageChainProvider,ExperimentIdentityStore,HistorySession,run_sync
from core.prompt_builder import PromptBuilder
from core.tool_executor import ToolExecutor
from core.tool_registry import ToolRegistry

BROWSER_SOUL='''You are Kage, completing a browser task through the provided tools.
The runtime supplies an initial DOM observation. Use only current observation_id and target_ref.
Every browser action returns a fresh observation: reuse it for the next action or to confirm the result.
If stale, use the fresh observation returned with the error. Observe or wait when asynchronous results are not yet visible.
Compact-v1 omits false checked/disabled and null target properties. Keep checkbox state in mind before clicking.
Confirm the saved result from the page. Tool success and final text alone do not prove completion.
Only use the provided browser tools. No selectors, JavaScript, file writes or invented node references.
'''


def descendant_pids(root):
    rows=[list(map(int,line.split())) for line in subprocess.check_output(['ps','-axo','pid=,ppid='],text=True).splitlines()]
    found={root}
    while True:
        added={pid for pid,parent in rows if parent in found}-found
        if not added: return sorted(found)
        found.update(added)


class CheckpointExecutor(ToolExecutor):
    def __init__(self,registry,workspace,page,url):
        super().__init__(registry,str(workspace))
        self.workspace,self.page,self.url=workspace,page,url

    async def execute(self,name,arguments,require_confirmation=None):
        result=await super().execute(name,arguments,require_confirmation)
        try:
            await checkpoint(self.page,self.url,self.workspace)
        except Exception as exc:
            # Do not mask the real action result; preserve evidence-check errors.
            with (self.workspace/'checkpoint-errors.jsonl').open('a') as stream:
                stream.write(json.dumps({'tool':name,'error':f'{type(exc).__name__}: {exc}'})+'\n')
        return result


class BrowserChainProvider(KageChainProvider):
    RESERVATION_INPUT_CAP=48_000
    RESERVATION_OUTPUT_CAP=2_000

    def __init__(self,model_provider,task_def,**kwargs):
        super().__init__(model_provider,**kwargs)
        self.task_def=json.loads(json.dumps(task_def))

    def _experiment_soul(self):
        return BROWSER_SOUL

    def cache_identity(self):
        return {**super().cache_identity(),'browser_task':self.task_def,
                'adapter_sha256':hashlib.sha256(Path(__file__).with_name('browser.py').read_bytes()).hexdigest(),
                'environment_sha256':hashlib.sha256(Path(__file__).with_name('task_environment.py').read_bytes()).hexdigest()}

    def metadata(self):
        return {**super().metadata(),'tool_registry':'ToolRegistry(page-scoped browser tools only)',
                'environment_kind':'resettable-local-http-browser','compact_observations':True,
                'initial_observation':'runtime bootstrap; no simulated model call'}

    def generate_step(self,task_def,step,history,workspace_dir):
        if task_def.get('task_id')!=self.task_def.get('task_id'):
            raise ValueError('browser fixture/checker task does not match execution task')
        self.calls+=1
        output=run_sync(lambda:self._run(task_def,step,history,Path(workspace_dir)))
        self.call_log.append({'task_id':task_def['task_id'],'step':step})
        return output

    async def _run(self,task,step,history,workspace):
        from playwright.async_api import async_playwright
        with browser_task_server(self.task_def['fixture'],workspace) as (url,state):
            async with async_playwright() as p:
                browser=await p.chromium.launch(headless=True)
                try:
                    context=await browser.new_context()
                    page=await context.new_page();await page.goto(url,wait_until='domcontentloaded',timeout=10000)
                    atomic_json(workspace/'worker-processes.json',descendant_pids(os.getpid()))
                    adapter=BrowserAdapter(page,trace_path=workspace/'browser.jsonl',compact_observations=True)
                    registry=ToolRegistry();adapter.register_tools(registry)
                    executor=CheckpointExecutor(registry,workspace,page,url)
                    builder=PromptBuilder(ExperimentIdentityStore(self._experiment_soul()),None,registry,
                                          prune_tools=False,memory_cfg={'recall_enabled':False})
                    loop=self.agentic_loop_cls(self._model,executor,builder,HistorySession())
                    started=time.monotonic()
                    observation=await adapter.observe()
                    atomic_json(workspace/'initial-observation.json',observation)
                    await checkpoint(page,url,workspace)
                    instruction=task['instruction']+'\nInitial browser observation supplied by runtime:\n'+json.dumps(observation,ensure_ascii=False,separators=(',',':'))
                    before=len(self._model.calls)
                    result=await loop.run(instruction)
                    agent_elapsed_ms=(time.monotonic()-started)*1000
                    await checkpoint(page,url,workspace)
                    atomic_json(workspace/'loop-result.json',asdict(result))
                    screenshot_error=None
                    try:
                        await page.screenshot(path=str(workspace/'final.png'),timeout=5000)
                    except Exception as exc:
                        screenshot_error=f'{type(exc).__name__}: {exc}'
                        (workspace/'screenshot-error.txt').write_text(screenshot_error)
                    calls=self._model.calls[before:]
                    usage={'api_calls':len(calls)}
                    if all('input_tokens' in c['usage'] and 'output_tokens' in c['usage'] for c in calls):
                        usage.update({key:sum(c['usage'][key] for c in calls) for key in ['input_tokens','output_tokens']})
                    chain={'task_id':task['task_id'],'runner_step':step,'chain_steps':result.steps,
                           'stop_reason':result.stop_reason,'model_calls':len(calls),
                           'tool_calls':len(result.tool_calls_executed),'call_usage':[c['usage'] for c in calls],
                           'model_errors':[c['error'] for c in calls if c['error']],
                           'model_elapsed_ms':round(sum(c['elapsed_ms'] for c in calls),3),
                           'agent_elapsed_ms':round(agent_elapsed_ms,3),
                           'final_text':result.final_text[:2000],'browser_version':browser.version,
                           'screenshot_error':screenshot_error}
                    self.last_chain=chain
                    return {'action':{'name':'finish','reason':f"browser chain stopped: {result.stop_reason}"},
                            'usage':usage,'chain':chain,
                            'tool_results':[self._normalize_tool_call(tc) for tc in result.tool_calls_executed]}
                finally:
                    await browser.close()
