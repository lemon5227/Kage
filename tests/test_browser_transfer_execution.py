"""Retries must preserve the live page and the original execution allowances."""
import json
from pathlib import Path
import pytest
pytest.importorskip('playwright.async_api')

from core.model_provider import ModelProvider,ModelResponse
from core.evolution.budget import BudgetConfig,BudgetTracker
from core.evolution.contracts import Candidate,RunSpec
from core.evolution.journal import Journal
from core.evolution.runner import EvolutionRunner
from core.computer_use import transfer

ROOT=Path(__file__).resolve().parents[1]
TASK=next(t for t in json.loads((ROOT/'eval/computer-use/browser-learning-v2.json').read_text())['tasks'] if t['task_id']=='preferences_dev')


class LocalActions(ModelProvider):
    def __init__(self,exhaust=False): self.calls=0;self.exhaust=exhaust;self.surfaces=[]
    def generate(self,messages,**kwargs):
        self.calls+=1
        prompt=json.dumps(messages)
        assert 'browser-outcome.json' not in prompt and 'readback_matches_backend' not in prompt
        obs=None
        for message in messages:
            content=message.get('content','')
            if message['role']=='tool':
                payload=json.loads(content[content.index('{'):]);obs=payload.get('observation',payload)
            elif 'runtime:\n' in content:
                obs=json.loads(content.split('runtime:\n',1)[1])
        self.surfaces.append(obs['surface_id'])
        if self.exhaust:
            # Four calls already consume the entire 16-primitive budget.
            tools=[{'name':'browser_observe','arguments':{}}]*4
        else:
            label=['Email notifications','SMS notifications','Save settings'][self.calls-1]
            if self.calls==3:
                assert 'Retry' in prompt
                assert next(t for t in obs['targets'] if t['label']=='Email notifications')['checked']
                assert not next(t for t in obs['targets'] if t['label']=='SMS notifications').get('checked',False)
            ref=next(t['target_ref'] for t in obs['targets'] if t['label']==label)
            tools=[{'name':'browser_act','arguments':{'observation_id':obs['observation_id'],'operation':'click','target_ref':ref}}]
        return ModelResponse(text='',tool_calls=tools,usage={'input_tokens':2,'output_tokens':1})


@pytest.mark.parametrize('exhaust',[False,True])
def test_retry_keeps_state_and_never_resets_shared_step_or_primitive_budget(tmp_path,exhaust):
    assert hasattr(transfer,'BrowserRetryProvider'), 'same-page bounded retry provider is missing'
    model=LocalActions(exhaust)
    provider=transfer.BrowserRetryProvider(model,TASK,model_label='scripted',max_model_calls=6,external_completion=True)
    budget=BudgetTracker(BudgetConfig(max_api_calls=6,max_input_tokens_total=100000,max_output_tokens_total=10000),tmp_path/'budget.sqlite')
    runner=EvolutionRunner(Journal(tmp_path/'journal.sqlite'),budget,tmp_path/'runs',provider,step_isolation='inline')
    result=runner.run(Candidate('retry',(),'workflow',str(ROOT),'retry-test'),TASK,RunSpec('retry','retry',TASK['task_id'],max_steps=1,timeout_s=30))
    chain=result.metadata['chain'][0]
    assert chain['model_calls']<=6 and chain['chain_steps']<=5
    assert len(set(model.surfaces))==1
    attempts=chain['retries']['attempts']
    assert len(attempts)>=2 and attempts[0]['browser_primitives']==(8 if exhaust else 2)
    if exhaust:
        assert result.status=='failed' and chain['browser_primitives']==16
        assert chain['model_calls']==4  # quota exhaustion must stop before another request.
    else:
        assert result.status=='passed' and result.score==1
        assert chain['browser_primitives']==3 and chain['model_calls']==3
        assert json.loads((Path(result.final_state_path)/'browser-check.json').read_text())['posts']==1


def test_trajectory_projection_uses_visible_labels_and_omits_checker_and_stale_references():
    assert hasattr(transfer,'trajectory_prompt'), 'trajectory projection is missing'
    feedback={'instruction':'Enable the first setting and save.',
        'initial_observation':{'observation_id':'OLD-ID','url':'OLD-URL','targets':[{'target_ref':'e1','label':'Mail','checked':False}]},
        'actions':[{'actor':'student','tool':'browser_act','arguments':{'observation_id':'OLD-ID','target_ref':'e1','operation':'click'},'outcome':'ok','observation':{'targets':[{'target_ref':'e1','label':'Mail','checked':True}]}}],
        'scoring_criteria':'CHECKER-SECRET','source_hashes':{'secret':'HASH'}}
    prompt=transfer.trajectory_prompt(feedback)
    assert 'Mail' in prompt and 'student' in prompt and 'click' in prompt
    assert all(s not in prompt for s in ['OLD-ID','OLD-URL','CHECKER-SECRET','HASH','target_ref'])


def test_partial_transfer_summary_preserves_frozen_denominator_and_actor_costs():
    # The driver is deliberately separate from the generation/promotion pilot.
    import importlib.util
    path=ROOT/'scripts/experiments/browser_transfer.py'
    assert path.exists(), 'five-arm driver is missing'
    spec=importlib.util.spec_from_file_location('transfer_driver',path)
    driver=importlib.util.module_from_spec(spec);spec.loader.exec_module(driver)
    plan=transfer.TransferPlan('test','hash',('one','two','three'),3,transfer.ARMS)
    rows=[{'arm':'cloud_takeover','status':'passed','score':1,'seconds':3,
           'actual_skill_calls':0,'metadata':{'chain':[{'model_calls':5,'browser_primitives':2,
           'takeover':{'triggered':True,'student_check_passed':False,
              'student_usage':{'api_calls':3,'input_tokens':9999,'output_tokens':100},
              'teacher_usage':{'api_calls':2,'input_tokens':100,'output_tokens':10}}}]}}]
    summary=driver.summarize(plan,rows)
    assert summary['expected_runs']==45 and summary['recorded_runs']==1 and not summary['complete']
    assert summary['arms']['cloud_takeover']['expected_runs']==9
    assert summary['arms']['cloud_takeover']['teacher_tokens']=={'input_tokens':100,'output_tokens':10}
    assert summary['arms']['cloud_takeover']['student_tokens']=={'input_tokens':9999,'output_tokens':100}
    assert summary['arms']['raw']['recorded_runs']==0


def test_summary_keeps_reported_tokens_distinct_from_conservative_budget_charge():
    from scripts.experiments.browser_transfer import summarize
    plan=transfer.TransferPlan('test','hash',('one',),1,transfer.ARMS)
    row={'arm':'raw','status':'failed','score':0,'seconds':1,'actual_skill_calls':0,
         'usage':{'api_calls':2,'input_tokens':48000,'output_tokens':2000},
         'metadata':{'chain':[{'model_calls':2,'browser_primitives':1,
             'call_usage':[{'input_tokens':5,'output_tokens':1},{}]}]}}
    arm=summarize(plan,[row])['arms']['raw']
    assert arm['student_tokens']=={'input_tokens':5,'output_tokens':1}
    assert arm['unknown_usage_runs']==1


def test_retry_early_final_responses_do_not_create_more_than_three_attempts(tmp_path):
    class ClaimsDone(ModelProvider):
        def generate(self,**kwargs):
            return ModelResponse(text='Done.',usage={'input_tokens':2,'output_tokens':1})
    provider=transfer.BrowserRetryProvider(ClaimsDone(),TASK,model_label='scripted',max_model_calls=6,external_completion=True)
    runner=EvolutionRunner(Journal(tmp_path/'journal.sqlite'),BudgetTracker(BudgetConfig(max_api_calls=6)),
                           tmp_path/'runs',provider,step_isolation='inline')
    result=runner.run(Candidate('retry',(),'workflow',str(ROOT),'early-final'),TASK,
        RunSpec('early-final','retry',TASK['task_id'],max_steps=1,timeout_s=30))
    assert result.status=='failed'
    assert len(result.metadata['chain'][0]['retries']['attempts'])==3
