"""Browser suite checks actual server records and independently visible readback."""
import asyncio
import json
from pathlib import Path
import time

import pytest
pytest.importorskip('playwright.async_api', reason='optional computer-use dependency')
from playwright.async_api import async_playwright

ROOT=Path(__file__).resolve().parents[1]


def tasks():
    return json.loads((ROOT/'eval/computer-use/browser-v1.json').read_text())['tasks']


def test_four_task_families_save_real_records_and_reset(tmp_path):
    from core.computer_use.task_environment import browser_task_server, checkpoint
    from core.computer_use.browser import BrowserAdapter
    from core.evolution.runner import Evaluator

    async def run():
        assert len(tasks())==8 and len({t['family'] for t in tasks()})==4
        async with async_playwright() as p:
            browser=await p.chromium.launch(headless=True)
            try:
                for task in tasks():
                    ws=tmp_path/task['task_id'];ws.mkdir()
                    with browser_task_server(task['fixture'],ws) as (url,state):
                        page=await browser.new_page();await page.goto(url)
                        assert state['saved'] is None and state['posts']==0
                        adapter=BrowserAdapter(page,compact_observations=True)
                        expected=task['scoring_criteria']['expected']['record']
                        # Tests supply known correct actions; real-agent evidence is separate.
                        async def act(label,op='click',value=None):
                            obs=await adapter.observe()
                            ref=next(t['target_ref'] for t in obs['targets'] if t['label']==label)
                            result=await adapter.act(obs['observation_id'],op,ref,value)
                            assert result['success']
                        fixture=task['fixture'];kind=fixture['kind']
                        if kind in ('profile','invoice'):
                            for field in fixture['fields']:
                                await act(field['label'],'fill',str(expected[field['name']]))
                            await act(fixture['submit'])
                        elif kind=='preferences':
                            for field in fixture['fields']:
                                if field['initial']!=expected[field['name']]: await act(field['label'])
                            await act(fixture['submit'])
                        else:
                            await act(fixture['query_label'],'fill',expected['city'])
                            await act(fixture['category_label'])
                            await act(fixture['apply_label'])
                            item=next(i for i in fixture['items'] if i['id']==expected['property_id'])
                            await act('Choose '+item['name'])
                        await page.wait_for_function('document.querySelector("[data-result]").textContent.length>0')
                        checked=await checkpoint(page,url,ws)
                        assert checked==task['scoring_criteria']['expected']
                        assert Evaluator.score(task,ws)==1 and state['posts']==1
                        assert json.loads((ws/'backend.json').read_text())['record']==expected
                        # A model declaration or backend-only success cannot satisfy UI readback.
                        await page.locator('[data-result]').evaluate('(el)=>el.textContent="not a saved result"')
                        await checkpoint(page,url,ws)
                        assert Evaluator.score(task,ws)==0
                        await page.locator('[data-result]').evaluate('(el,value)=>el.textContent=JSON.stringify(value)',expected)
                        await checkpoint(page,url,ws)
                        assert Evaluator.score(task,ws)==1
                        # A new real POST must revoke old proof before another
                        # checkpoint, including when the worker is then killed.
                        await page.request.post(url+'/save',data=expected)
                        assert state['posts']==2 and Evaluator.score(task,ws)==0
                        learning_task={**task,'scoring_criteria':{'type':'json_exact_match','file':'browser-outcome.json',
                            'expected':{'record':expected,'readback_matches_backend':True}}}
                        assert Evaluator.score(learning_task,ws)==0
                        # Simulate a GET snapshot captured before that POST.
                        # Its later DOM read must not resurrect the old proof.
                        from types import SimpleNamespace
                        class OldResponse:
                            async def json(self): return {'record':expected,'posts':1}
                        async def old_get(*args,**kwargs): return OldResponse()
                        stale_page=SimpleNamespace(request=SimpleNamespace(get=old_get),locator=page.locator)
                        stale_check=await checkpoint(stale_page,url,ws)
                        assert stale_check['posts']==2 and not stale_check['readback_matches_backend']
                        assert Evaluator.score(task,ws)==0
                        assert Evaluator.score(learning_task,ws)==0
                        await checkpoint(page,url,ws)
                        assert Evaluator.score(learning_task,ws)==1 and Evaluator.score(task,ws)==0
                        await page.close()
            finally: await browser.close()
    asyncio.run(run())


def test_browser_worker_hard_timeout_retains_checkpoint_and_stops_descendants(tmp_path):
    from core.computer_use.experiment import BrowserChainProvider
    from core.evolution.budget import BudgetConfig,BudgetTracker
    from core.evolution.contracts import Candidate,RunSpec
    from core.evolution.journal import Journal
    from core.evolution.runner import EvolutionRunner
    from core.model_provider import ModelProvider

    class BlockingModel(ModelProvider):
        def generate(self,**kwargs):
            # Timeout must interrupt an actual synchronous model call, not asyncio sleep.
            time.sleep(20)
            raise AssertionError('hard deadline did not interrupt')

    task=tasks()[0]
    provider=BrowserChainProvider(BlockingModel(),task,model_label='blocking-timeout-test')
    runner=EvolutionRunner(Journal(tmp_path/'journal.sqlite'),BudgetTracker(
        BudgetConfig(max_api_calls=6,max_input_tokens_total=100000,max_output_tokens_total=10000),tmp_path/'budget.sqlite'),tmp_path/'runs',provider)
    candidate=Candidate('browser',(),'workflow',str(ROOT),'timeout-test')
    start=time.monotonic()
    result=runner.run(candidate,task,RunSpec('hard-timeout','browser',task['task_id'],max_steps=1,timeout_s=4))
    assert result.status=='timeout' and result.score==0 and time.monotonic()-start<8
    ws=Path(result.final_state_path)
    assert (ws/'browser-check.json').exists() and (ws/'worker-processes.json').exists()
    import os
    process_ids=json.loads((ws/'worker-processes.json').read_text())
    for pid in process_ids:
        with pytest.raises(ProcessLookupError): os.kill(pid,0)


def test_model_claim_without_browser_actions_fails_external_check(tmp_path):
    from core.computer_use.experiment import BrowserChainProvider
    from core.evolution.budget import BudgetConfig,BudgetTracker
    from core.evolution.contracts import Candidate,RunSpec
    from core.evolution.journal import Journal
    from core.evolution.runner import EvolutionRunner
    from core.model_provider import ModelProvider,ModelResponse

    class ClaimOnlyModel(ModelProvider):
        def generate(self,messages,**kwargs):
            prompt=json.dumps(messages)
            assert 'readback_matches_backend' not in prompt and 'browser-check.json' not in prompt
            return ModelResponse(text='All requested values were saved successfully.',usage={'input_tokens':1,'output_tokens':1})

    task=tasks()[0]
    provider=BrowserChainProvider(ClaimOnlyModel(),task,model_label='claim-only-test')
    runner=EvolutionRunner(Journal(tmp_path/'journal.sqlite'),BudgetTracker(
        BudgetConfig(max_api_calls=6,max_input_tokens_total=100000,max_output_tokens_total=10000),tmp_path/'budget.sqlite'),tmp_path/'runs',provider)
    result=runner.run(Candidate('browser',(),'workflow',str(ROOT),'claim-test'),task,
                      RunSpec('false-claim','browser',task['task_id'],max_steps=1,timeout_s=15))
    assert result.status=='failed' and result.score==0
    check=json.loads((Path(result.final_state_path)/'browser-check.json').read_text())
    assert check['record'] is None and check['posts']==0
    assert result.metadata['chain_model_calls']==1 and result.metadata['chain_tool_calls']==0
