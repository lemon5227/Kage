"""A browser workflow must act through the owned Page and independent checker."""
import asyncio
import hashlib
import json
from pathlib import Path
import pytest
pytest.importorskip('playwright.async_api')

from core.computer_use.skills import BrowserSkillCatalog
from core.evolution.contracts import Candidate,RunSpec
from core.evolution.journal import Journal
from core.evolution.budget import BudgetConfig,BudgetTracker
from core.evolution.runner import EvolutionRunner
from core.computer_use.experiment import BrowserChainProvider
from core.model_provider import ModelProvider,ModelResponse

ROOT=Path(__file__).resolve().parents[1]
TASK=next(t for t in json.loads((ROOT/'eval/computer-use/browser-learning-v2.json').read_text())['tasks'] if t['task_id']=='preferences_dev')


def bundle(tmp_path):
    from core.computer_use.skills import descriptor_digest
    root=tmp_path/'bundle';root.mkdir()
    descriptor={'skill_id':'set_preferences','description':'Set named checkbox preferences and save the page',
        'parameters':{'type':'object','properties':{
            'settings':{'type':'array','maxItems':8,'items':{'type':'object','properties':{
                'label':{'type':'string'},'checked':{'type':'boolean'}},'required':['label','checked'],'additionalProperties':False}},
            'save_label':{'type':'string'}},'required':['settings','save_label'],'additionalProperties':False},
        'workflow':[{'op':'for_each','items_param':'settings','step':{'op':'ensure_checked','label_item':'label','checked_item':'checked'}},
                    {'op':'click','label_param':'save_label'}]}
    descriptor['digest']=descriptor_digest(descriptor)
    (root/'manifest.json').write_text(json.dumps({'version':2,'kind':'browser_workflow','skills':[descriptor]}))
    return root,descriptor


def test_bundle_digest_and_unknown_skill_do_not_execute(tmp_path):
    path,descriptor=bundle(tmp_path)
    catalog=BrowserSkillCatalog.from_bundle(path)
    assert catalog.search('checkbox')['skills'][0]['digest']==descriptor['digest']
    assert catalog.digests=={'set_preferences':descriptor['digest']}
    (path/'manifest.json').write_text(json.dumps({'version':2,'kind':'browser_workflow','skills':[{**descriptor,'description':'mutated'}]}))
    with pytest.raises(ValueError,match='digest'):
        BrowserSkillCatalog.from_bundle(path)


@pytest.mark.parametrize('query',['checkbox','notification preferences enable email disable sms save settings'])
def test_skill_discovery_call_and_actual_saved_readback(tmp_path,query):
    path,descriptor=bundle(tmp_path)
    args={'settings':[{'label':'Email notifications','checked':True},
                      {'label':'SMS notifications','checked':False},
                      {'label':'Weekly digest','checked':False}], 'save_label':'Save settings'}
    class SkillModel(ModelProvider):
        def __init__(self): self.calls=0
        def generate(self,messages,**kwargs):
            self.calls+=1
            if self.calls==1:
                assert any(t['function']['name']=='skill_search' for t in kwargs['tools'])
                return ModelResponse(text='',tool_calls=[{'name':'skill_search','arguments':{'query':query}}])
            if self.calls==2:
                discovered=next(m for m in messages if m['role']=='tool')
                result=json.loads(discovered['content'].split('] ',1)[1])
                assert result['skills'][0]['digest']==descriptor['digest']
                return ModelResponse(text='',tool_calls=[{'name':'skill_call','arguments':{'skill_id':'set_preferences','digest':descriptor['digest'],'arguments':args}}])
            return ModelResponse(text='Done')
    model=SkillModel()
    provider=BrowserChainProvider(model,TASK,model_label='scripted',max_model_calls=4,
                                  external_completion=True,browser_skill_bundle=path)
    runner=EvolutionRunner(Journal(tmp_path/'journal.sqlite'),BudgetTracker(BudgetConfig(max_api_calls=8),tmp_path/'budget.sqlite'),tmp_path/'runs',provider)
    result=runner.run(Candidate('browser',(),'workflow',str(path),'test'),TASK,RunSpec('skill','browser',TASK['task_id'],max_steps=1,timeout_s=30))
    assert result.status=='passed' and result.score==1
    assert result.metadata['chain'][0]['model_calls']==2  # trusted completion gate avoids summary call.
    workspace=Path(result.final_state_path)
    check=json.loads((workspace/'browser-check.json').read_text())
    assert check['record']=={'email':True,'sms':False,'weekly':False} and check['readback_matches_backend']
    actions=[json.loads(line) for line in (workspace/'actor-tools.jsonl').read_text().splitlines()]
    assert [row['name'] for row in actions].count('browser_act')==3
    assert [row['name'] for row in actions].count('skill_call')==1
    assert result.metadata['chain'][0]['browser_primitives']==4
    assert result.metadata['browser_skill_digests']==catalog_digests(path)


def catalog_digests(path):
    return BrowserSkillCatalog.from_bundle(path).digests


@pytest.mark.parametrize('case',['already_satisfied','reordered','ambiguous','quota','stale_once','unknown_applied','unknown_no_observation'])
def test_live_workflow_resolves_semantics_and_stops_on_uncertainty(tmp_path,case):
    from playwright.async_api import async_playwright
    from core.computer_use.browser import BrowserAdapter
    from core.computer_use.skills import BrowserPrimitiveQuota
    from core.computer_use.experiment import CheckpointExecutor
    from core.computer_use.task_environment import browser_task_server
    from core.tool_registry import ToolRegistry
    path,descriptor=bundle(tmp_path)
    task=json.loads(json.dumps(TASK))
    if case=='already_satisfied':
        task['fixture']['fields'][0]['initial']=True
        task['fixture']['fields'][1]['initial']=False
    if case=='reordered': task['fixture']['fields'].reverse()
    if case=='ambiguous':
        task['fixture']['fields'].append({'name':'other','label':'Email notifications','initial':False})
    args={'settings':[{'label':'Email notifications','checked':True},
                      {'label':'SMS notifications','checked':False},
                      {'label':'Weekly digest','checked':False}], 'save_label':'Save settings'}
    async def run():
        workspace=tmp_path/'workspace';workspace.mkdir()
        with browser_task_server(task['fixture'],workspace) as (url,state):
            async with async_playwright() as p:
                browser=await p.chromium.launch(headless=True)
                try:
                    page=await browser.new_page();await page.goto(url)
                    adapter=BrowserAdapter(page,compact_observations=True)
                    quota=BrowserPrimitiveQuota(2 if case=='quota' else 16)
                    registry=ToolRegistry();adapter.register_tools(registry,quota=quota)
                    executor=CheckpointExecutor(registry,workspace,page,url,settle_saves=True)
                    catalog=BrowserSkillCatalog.from_bundle(path)
                    catalog.register_tools(registry,adapter,executor,workspace,quota)
                    if case=='quota':
                        await executor.execute('browser_observe',{})  # raw and nested tools share the same limit.
                    if case=='stale_once':
                        original=adapter.act;changed=False
                        async def replaced(*a,**kw):
                            nonlocal changed
                            if not changed:
                                changed=True
                                await page.evaluate('''() => {const old=document.querySelector('input[name="email"]');old.replaceWith(old.cloneNode(true));}''')
                            return await original(*a,**kw)
                        adapter.act=replaced
                    if case in {'unknown_applied','unknown_no_observation'}:
                        original=adapter.act;attempts=0
                        async def unknown(*a,**kw):
                            nonlocal attempts
                            attempts+=1
                            answer={'success':False,'error':'BrowserTimeout','message':'click timed out',
                                    'outcome':'tool_error','action_applied':None}
                            if case=='unknown_applied':answer['observation']=await adapter.observe()
                            return answer
                        adapter.act=unknown
                    result=await executor.execute('skill_call',{'skill_id':'set_preferences','digest':descriptor['digest'],'arguments':args})
                    payload=json.loads(result.result)
                    if case in {'already_satisfied','reordered','stale_once'}:
                        assert result.success and payload['success']
                        assert (await executor.checkpoint())['readback_matches_backend']
                        assert state['saved']=={'email':True,'sms':False,'weekly':False}
                        if case=='already_satisfied':
                            assert len([s for s in payload['steps'] if s['outcome']=='unchanged'])==3
                        if case=='stale_once':
                            assert any(s['outcome']=='rejected' for s in payload['steps'])
                    else:
                        assert not result.success and result.outcome=='not_applied'
                        if payload.get('observation'):
                            assert json.loads(result.history_line()[result.history_line().index('{'):])['observation']['observation_id']==payload['observation']['observation_id']
                        assert state['posts']==0
                        if case=='quota': assert quota.used==2 and payload['error']=='PrimitiveQuotaExceeded'
                        if case=='ambiguous': assert payload['error']=='AmbiguousTarget'
                        if case in {'unknown_applied','unknown_no_observation'}:
                            assert payload['action_applied'] is None and attempts==1
                            if case=='unknown_no_observation': assert payload['observation'] is None
                    nested=[json.loads(x) for x in (workspace/'actor-tools.jsonl').read_text().splitlines()]
                    children=[row for row in nested if row['name'].startswith('browser_') and 'parent_call_id' in row]
                    assert children and len({row['parent_call_id'] for row in children})==1
                    assert all(row['skill_id']=='set_preferences' and row['digest']==descriptor['digest'] for row in children)
                    assert nested[-1]['name']=='skill_call' and 'parent_call_id' not in nested[-1]
                finally: await browser.close()
    asyncio.run(run())


def test_profile_fill_workflow_saves_real_values(tmp_path):
    from playwright.async_api import async_playwright
    from core.computer_use.browser import BrowserAdapter
    from core.computer_use.skills import BrowserPrimitiveQuota,descriptor_digest
    from core.computer_use.experiment import CheckpointExecutor
    from core.computer_use.task_environment import browser_task_server
    from core.tool_registry import ToolRegistry
    task=next(t for t in json.loads((ROOT/'eval/computer-use/browser-learning-v2.json').read_text())['tasks'] if t['task_id']=='profile_dev')
    descriptor={'skill_id':'fill_profile','description':'Fill named profile fields and save',
        'parameters':{'type':'object','properties':{
            'name_label':{'type':'string'},'name_value':{'type':'string'},
            'email_label':{'type':'string'},'email_value':{'type':'string'},
            'save_label':{'type':'string'}},
            'required':['name_label','name_value','email_label','email_value','save_label'],'additionalProperties':False},
        'workflow':[{'op':'fill','label_param':'name_label','value_param':'name_value'},
                    {'op':'fill','label_param':'email_label','value_param':'email_value'},
                    {'op':'click','label_param':'save_label'}]}
    descriptor['digest']=descriptor_digest(descriptor)
    path=tmp_path/'bundle';path.mkdir()
    (path/'manifest.json').write_text(json.dumps({'version':2,'kind':'browser_workflow','skills':[descriptor]}))
    workspace=tmp_path/'workspace';workspace.mkdir()
    async def run():
        with browser_task_server(task['fixture'],workspace) as (url,state):
            async with async_playwright() as p:
                browser=await p.chromium.launch(headless=True)
                try:
                    page=await browser.new_page();await page.goto(url)
                    adapter=BrowserAdapter(page,compact_observations=True)
                    quota=BrowserPrimitiveQuota()
                    registry=ToolRegistry();adapter.register_tools(registry,quota=quota)
                    executor=CheckpointExecutor(registry,workspace,page,url,settle_saves=True)
                    BrowserSkillCatalog.from_bundle(path).register_tools(registry,adapter,executor,workspace,quota)
                    args={'name_label':'Name','name_value':'Wenbo Browser Lab','email_label':'Email',
                          'email_value':'wenbo@example.test','save_label':'Save profile'}
                    result=await executor.execute('skill_call',{'skill_id':'fill_profile','digest':descriptor['digest'],'arguments':args})
                    assert result.success and quota.used==4
                    assert (await executor.checkpoint())['readback_matches_backend']
                    assert state['saved']=={'name':'Wenbo Browser Lab','email':'wenbo@example.test'}
                finally: await browser.close()
    asyncio.run(run())
