"""A sixth real action can save; distinct budgets cannot reuse a cached score."""
import json
from pathlib import Path
import pytest
pytest.importorskip('playwright.async_api')
from core.computer_use.experiment import BrowserChainProvider, BrowserCloudProvider
from core.computer_use.teacher_takeover import BrowserTeacherTakeoverProvider
from core.evolution.budget import BudgetConfig, BudgetTracker
from core.evolution.contracts import Candidate, RunSpec
from core.evolution.journal import Journal
from core.evolution.runner import EvolutionRunner
from core.model_provider import ModelResponse
from test_browser_takeover import Actions, ROOT


def definition():
    return json.loads((ROOT/'eval/computer-use/browser-save-budget-dev.json').read_text())['tasks'][0]


class ObserveThenActions(Actions):
    def __init__(self, task):
        super().__init__([f['label'] for f in task['fixture']['fields']]+[task['fixture']['submit']])
        self.first=True

    def generate(self, messages, **kwargs):
        if self.first:
            self.first=False
            return ModelResponse(text='',tool_calls=[{'name':'browser_observe','arguments':{}}],
                                 usage={'input_tokens':2,'output_tokens':1})
        assert self.labels, 'seventh model call is forbidden'
        return super().generate(messages,**kwargs)


@pytest.mark.parametrize('provider_cls',[BrowserChainProvider,BrowserCloudProvider])
def test_sixth_step_saves_and_cache_budget_cannot_cross(tmp_path,provider_cls):
    task=definition(); journal=Journal(tmp_path/'j.sqlite')
    budget=BudgetTracker(BudgetConfig(max_api_calls=12,max_input_tokens_total=200000,max_output_tokens_total=20000),tmp_path/'b.sqlite')
    candidate=Candidate('browser',(),'workflow',str(ROOT),'budget-save')
    def run(cap,run_id):
        provider=provider_cls(ObserveThenActions(task),task,max_loop_steps=cap,max_model_calls=6,
                             model_label='scripted',external_completion=True,observation_format='compact-v2')
        runner=EvolutionRunner(journal,budget,tmp_path/'runs',provider)
        return runner.run(candidate,task,RunSpec(run_id,'browser',task['task_id'],max_steps=1,timeout_s=20)),provider
    five,p5=run(5,'five');six,p6=run(6,'six')
    for result,cap in [(five,5),(six,6)]:
        check=json.loads((Path(result.final_state_path)/'browser-check.json').read_text())
        assert check['posts']==(cap==6)
        entries=[json.loads(line) for line in (Path(result.final_state_path)/'actor-tools.jsonl').read_text().splitlines()]
        observation=json.loads(entries[-1]['result'])['observation']
        form={f['name']:next(t['checked'] for t in observation['targets'] if t['label']==f['label'])
              for f in task['fixture']['fields']}
        assert form==task['scoring_criteria']['expected']['record']
        assert result.metadata['chain'][0]['model_calls']==cap
        assert result.metadata['max_loop_steps']==cap
        assert result.metadata['agentic_loop_max_steps']==cap
        if cap==6:
            assert check['record']==form and check['readback_matches_backend']
    assert five.status=='failed' and six.status=='passed'
    assert p5.cache_identity()!=p6.cache_identity()
    with pytest.raises(ValueError,match='different or unverifiable inputs'):
        run(6,'five')
    cached,p_cached=run(5,'five')
    assert cached.status=='failed' and p_cached.calls==0
    assert budget.to_dict()['total_api_calls']==11


def test_primary_six_does_not_raise_teacher_five(tmp_path):
    task=definition()
    provider=BrowserTeacherTakeoverProvider(Actions([]),ObserveThenActions(task),task,
        max_loop_steps=6,max_model_calls=6,external_completion=True,observation_format='compact-v2')
    runner=EvolutionRunner(Journal(tmp_path/'j.sqlite'),BudgetTracker(BudgetConfig(max_api_calls=12,
        max_input_tokens_total=200000,max_output_tokens_total=20000),tmp_path/'b.sqlite'),tmp_path/'runs',provider)
    result=runner.run(Candidate('browser',(),'workflow',str(ROOT),'teacher-budget'),task,
                      RunSpec('teacher','browser',task['task_id'],max_steps=1,timeout_s=20))
    takeover=result.metadata['chain'][0]['takeover']
    assert takeover['teacher_usage']['api_calls']==5 and not takeover['teacher_check_passed']
    assert result.status=='failed'
    assert json.loads((Path(result.final_state_path)/'browser-check.json').read_text())['posts']==0


@pytest.mark.parametrize('cap',[0,-1,7,True,5.5,'6'])
def test_explicit_loop_limit_must_fit_request_guard(cap):
    with pytest.raises(ValueError,match='max_loop_steps'):
        BrowserChainProvider(None,definition(),max_loop_steps=cap,max_model_calls=6)


def test_frozen_budget_driver_uses_search_and_two_runs_per_budget():
    from scripts.experiments.browser_skill_diagnosis import load_save_budget, diagnostic_provider, summarize
    tasks=load_save_budget(ROOT/'eval/computer-use/browser-save-budget-dev.json')
    assert len(tasks)==2
    # Both instances require all four changes, rather than an already satisfied goal.
    for task in tasks:
        goal=task['scoring_criteria']['expected']['record']
        assert all(f['initial']!=goal[f['name']] for f in task['fixture']['fields'])
    provider=diagnostic_provider(None,tasks[0],None,'steps-6',local=True,model_label='scripted')
    assert provider.skill_context_mode=='search' and provider.max_loop_steps==6
    rows=[{'arm':arm,'chain':{},'status':'failed','skill_search':0,'skill_call':0,'seconds':0}
          for arm in ('steps-5','steps-6') for _ in tasks]
    report=summarize(rows,('steps-5','steps-6'),expected_per_arm=2)
    assert report['complete'] and report['arms']['steps-6']['expected_runs']==2
