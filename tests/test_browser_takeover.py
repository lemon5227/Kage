"""Actual saved errors can be revised in one live browser; no model claims score."""
import json
from pathlib import Path
import pytest
pytest.importorskip('playwright.async_api')
from core.model_provider import ModelProvider,ModelResponse
ROOT=Path(__file__).resolve().parents[1]

def task():
    return next(t for t in json.loads((ROOT/'eval/computer-use/browser-learning-v2.json').read_text())['tasks'] if t['task_id']=='preferences_dev')

class Actions(ModelProvider):
    def __init__(self,labels): self.labels=list(labels)
    def generate(self,messages,**kwargs):
        prompt=json.dumps(messages)
        assert 'browser-outcome.json' not in prompt and 'readback_matches_backend' not in prompt
        obs=None
        for m in messages:
            content=m.get('content','')
            if not isinstance(content,str): continue
            if m.get('role')=='tool':
                try:
                    value=json.loads(content[content.index('{'):]);obs=value.get('observation',value) if isinstance(value,dict) else obs
                except ValueError: pass
            elif 'runtime:\n' in content:
                obs=json.loads(content.split('runtime:\n',1)[1])
        if not self.labels: return ModelResponse(text='Done',usage={'input_tokens':2,'output_tokens':1})
        label=self.labels.pop(0)
        if label.startswith('WAIT:'):
            return ModelResponse(text='',tool_calls=[{'name':'browser_act','arguments':{'observation_id':obs['observation_id'],'operation':'wait','value':label[5:]}}],usage={'input_tokens':2,'output_tokens':1})
        ref=next(x['target_ref'] for x in obs['targets'] if x['label']==label)
        return ModelResponse(text='',tool_calls=[{'name':'browser_act','arguments':{'observation_id':obs['observation_id'],'operation':'click','target_ref':ref}}],usage={'input_tokens':2,'output_tokens':1})

@pytest.mark.parametrize('student_ok',[False,True,'raised'])
def test_real_same_page_revision_and_teacher_skipped_when_already_correct(tmp_path,student_ok):
    from core.computer_use.teacher_takeover import BrowserTeacherTakeoverProvider
    from core.evolution.budget import BudgetConfig,BudgetTracker
    from core.evolution.contracts import Candidate,RunSpec
    from core.evolution.journal import Journal
    from core.evolution.runner import EvolutionRunner
    raised=student_ok=='raised'
    student_ok=student_ok is True
    class RaisesAfterActions(Actions):
        def generate(self,*args,**kwargs):
            if not self.labels: raise TimeoutError('student request raised after wrong save')
            return super().generate(*args,**kwargs)
    student=['Email notifications','SMS notifications','Save settings','WAIT:"email":true'] if student_ok else ['SMS notifications','Save settings','WAIT:"email":false']
    provider=BrowserTeacherTakeoverProvider((RaisesAfterActions if raised else Actions)(student),Actions(['Email notifications','Save settings','WAIT:"email":true']),task(),model_label='test-student',teacher_label='test-teacher')
    runner=EvolutionRunner(Journal(tmp_path/'j.sqlite'),BudgetTracker(BudgetConfig(max_api_calls=12,max_input_tokens_total=200000,max_output_tokens_total=20000),tmp_path/'b.sqlite'),tmp_path/'runs',provider)
    r=runner.run(Candidate('browser',(),'workflow',str(ROOT),'same-page'),task(),RunSpec('revision','browser','preferences_dev',max_steps=1,timeout_s=20))
    assert r.status=='passed' and r.score==1
    ws=Path(r.final_state_path);check=json.loads((ws/'browser-check.json').read_text())
    assert check['posts']==(1 if student_ok else 2) and check['record']=={'email':True,'sms':False,'weekly':False}
    takeover=r.metadata['chain'][0]['takeover']
    assert takeover['triggered']==(not student_ok)
    assert takeover['continued_same_page'] and takeover['student_surface_id']==takeover['final_surface_id']
    if not student_ok:
        assert takeover['student_state']['posts']==1 and takeover['student_state']['record']['email'] is False
        assert takeover['teacher_usage']['api_calls']==4
    else: assert takeover['teacher_usage']['api_calls']==0
    if raised:
        assert any('TimeoutError' in error for error in takeover['student_chain']['model_errors'])
        assert 'input_tokens' not in takeover['student_usage']
    actors=[json.loads(x)['actor'] for x in (ws/'actor-tools.jsonl').read_text().splitlines()]
    assert ('teacher' in actors)==(not student_ok)


@pytest.mark.parametrize('student_ok',[True,False])
def test_external_completion_waits_for_real_saved_readback_and_skips_extra_calls(tmp_path,student_ok):
    from core.computer_use.teacher_takeover import BrowserTeacherTakeoverProvider
    from core.evolution.budget import BudgetConfig,BudgetTracker
    from core.evolution.contracts import Candidate,RunSpec
    from core.evolution.journal import Journal
    from core.evolution.runner import EvolutionRunner
    definition=task();definition['fixture']['readback_delay_ms']=150
    class NoSummary(Actions):
        def generate(self,*args,**kwargs):
            if not self.labels: raise AssertionError('unnecessary model summary requested')
            return super().generate(*args,**kwargs)
    labels=['Email notifications','SMS notifications','Save settings'] if student_ok else ['SMS notifications','Save settings']
    provider=BrowserTeacherTakeoverProvider(NoSummary(labels),NoSummary(['Email notifications','Save settings']),definition,
        model_label='test-student',teacher_label='test-teacher',external_completion=True)
    runner=EvolutionRunner(Journal(tmp_path/'j.sqlite'),BudgetTracker(BudgetConfig(max_api_calls=12,max_input_tokens_total=200000,max_output_tokens_total=20000),tmp_path/'b.sqlite'),tmp_path/'runs',provider)
    r=runner.run(Candidate('browser',(),'workflow',str(ROOT),'external-completion'),definition,RunSpec('complete','browser',definition['task_id'],max_steps=1,timeout_s=20))
    assert r.status=='passed' and r.score==1
    t=r.metadata['chain'][0]['takeover']
    assert t['student_check_passed']==student_ok and t['triggered']==(not student_ok)
    if student_ok:
        assert t['student_usage']['api_calls']==3 and t['teacher_usage']['api_calls']==0
        assert t['student_chain']['stop_reason']=='external_check' and not t['student_chain']['model_errors']
    else:
        assert t['student_usage']['api_calls']==3 # Wrong saved state must not trigger early completion.
        assert t['teacher_usage']['api_calls']==2 and t['teacher_check_passed']
        assert t['teacher_chain']['stop_reason']=='external_check' and not t['teacher_chain']['model_errors']
    check=json.loads((Path(r.final_state_path)/'browser-check.json').read_text())
    assert check['posts']==(1 if student_ok else 2) and check['readback_matches_backend']
    assert provider.cache_identity()['external_completion'] is True


def test_save_settlement_deadline_keeps_live_page_and_unconfirmed_evidence(tmp_path):
    import asyncio
    from playwright.async_api import async_playwright
    from core.computer_use.experiment import CheckpointExecutor
    from core.computer_use.browser import BrowserAdapter
    from core.computer_use.task_environment import browser_task_server
    from core.tool_registry import ToolRegistry
    async def run():
        loop=asyncio.get_running_loop();errors=[]
        loop.set_exception_handler(lambda loop,context: errors.append(context))
        definition=task();definition['fixture']['readback_delay_ms']=1500
        with browser_task_server(definition['fixture'],tmp_path) as (url,state):
            async with async_playwright() as p:
                browser=await p.chromium.launch(headless=True)
                try:
                    page=await browser.new_page();await page.goto(url)
                    adapter=BrowserAdapter(page);registry=ToolRegistry();adapter.register_tools(registry)
                    executor=CheckpointExecutor(registry,tmp_path,page,url,settle_saves=True)
                    await executor.checkpoint()
                    obs=await adapter.observe();ref=next(t['target_ref'] for t in obs['targets'] if t['label']=='Save settings')
                    await adapter.act(obs['observation_id'],'click',ref)
                    checked=await executor.checkpoint()
                    assert checked['posts']==1 and not checked['readback_matches_backend'] and not page.is_closed()
                    assert (tmp_path/'checkpoint-errors.jsonl').exists()
                    await page.wait_for_function('document.querySelector("[data-result]").textContent.length>0')
                    assert (await executor.checkpoint())['readback_matches_backend']
                finally:
                    await browser.close()
                    await asyncio.sleep(.01)
                    assert not errors, errors
    asyncio.run(run())


@pytest.mark.parametrize('packed',[False,True])
def test_teacher_can_save_under_same_wire_cap_with_archived_dom_history(tmp_path,packed):
    from core.computer_use.teacher_takeover import BrowserTeacherTakeoverProvider
    from core.model_provider import OpenAICompatibleProvider
    from core.evolution.budget import BudgetConfig,BudgetTracker
    from core.evolution.contracts import Candidate,RunSpec
    from core.evolution.journal import Journal
    from core.evolution.runner import EvolutionRunner
    class WireBoundedActions(Actions):
        def generate(self,messages,**kwargs):
            wire=OpenAICompatibleProvider(api_key='test',model_name='deepseek-flash',thinking=False)
            kwargs['max_tokens']=1024;kwargs['temperature']=0
            if len(wire._serialize_request(wire._request_payload(messages,**kwargs)))>12000:
                raise RuntimeError('teacher input byte cap reached')
            if self.labels and self.labels[0]=='OBSERVE':
                self.labels.pop(0)
                return ModelResponse(text='Reobserve',tool_calls=[{'name':'browser_observe','arguments':{}}],usage={'input_tokens':2,'output_tokens':1})
            return super().generate(messages,**kwargs)
    provider=BrowserTeacherTakeoverProvider(Actions([]),WireBoundedActions(['OBSERVE','Email notifications','SMS notifications','Save settings']),task(),
        model_label='test-student',external_completion=True,teacher_context_pack=packed)
    runner=EvolutionRunner(Journal(tmp_path/'j.sqlite'),BudgetTracker(BudgetConfig(max_api_calls=12,max_input_tokens_total=200000,max_output_tokens_total=20000),tmp_path/'b.sqlite'),tmp_path/'runs',provider)
    r=runner.run(Candidate('browser',(),'workflow',str(ROOT),'bounded-history'),task(),RunSpec('bounded','browser','preferences_dev',max_steps=1,timeout_s=20))
    ws=Path(r.final_state_path)
    t=r.metadata['chain'][0]['takeover']
    assert (r.status=='passed' and r.score==1)==packed
    if packed:
        assert t['teacher_chain']['stop_reason']=='external_check' and t['teacher_check_passed']
        assert t['teacher_usage']['api_calls']==4
        assert json.loads((ws/'backend.json').read_text())['record']=={'email':True,'sms':False,'weekly':False}
        records=[json.loads(line) for line in (ws/'teacher-context-pack.jsonl').read_text().splitlines()]
        assert records[-1]['archived_observations']>=3
        assert all((ws/record['source_path']).exists() for record in records)
    else:
        assert 'byte cap' in str(t['teacher_chain']['model_errors'])
