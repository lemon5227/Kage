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
