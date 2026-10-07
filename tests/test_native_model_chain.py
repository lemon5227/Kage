import asyncio
import copy
import json
from pathlib import Path
from core.computer_use.native_ax import NativeAXAdapter
from core.model_provider import ModelResponse

class Driver:
    def __init__(self):
        self.value='initial'; self.actions=[]; self.revision=0;self.document_url='' 
    def windows(self,bundle):
        return [{'window_ref':'owned','title':'owned.txt','bundle_id':bundle,'document_url':self.document_url},
                {'window_ref':'private','title':'private.txt','bundle_id':bundle}]
    def snapshot(self,ref):
        assert ref=='owned'
        return {'window_ref':ref,'title':'owned.txt','document_url':self.document_url,'targets':[{'target_ref':'text','role':'AXTextArea',
                'value':self.value,'operations':['fill']}],'truncated':False}
    def act(self,ref,target,operation,value):
        self.actions.append((ref,target,operation,value)); self.value=value

class Provider:
    def __init__(self,callback):self.callback=callback;self.messages=[]
    def generate(self,messages,**kwargs):
        self.messages.append(copy.deepcopy(messages));return self.callback(messages,kwargs)

def test_scope_filters_private_windows_and_rejects_foreign_refs():
    from core.computer_use.native_model import ScopedNativeAdapter
    async def scenario():
        driver=Driver(); scoped=ScopedNativeAdapter(NativeAXAdapter(driver),'com.apple.TextEdit','owned.txt')
        result=await scoped.windows('com.apple.TextEdit')
        assert [w['window_ref'] for w in result['windows']]==['owned']
        assert not (await scoped.observe('private'))['success']
        assert not (await scoped.windows('other.app'))['success']
        obs=(await scoped.observe('owned'))['observation']
        driver.value='externally changed'
        stale=await scoped.act(obs['observation_id'],'fill','text','new')
        assert stale['error']=='StaleObservation' and stale['observation']['targets'][0]['value']=='externally changed'
        assert driver.actions==[]
    asyncio.run(scenario())

def test_chain_uses_real_observation_and_tool_exchange_without_checker_secrets(tmp_path):
    from core.computer_use.native_model import NativeModelChain
    driver=Driver()
    def callback(messages,kwargs):
        assert {s['function']['name'] for s in kwargs['tools']}=={'native_windows','native_observe','native_act'}
        if len(provider.messages)==1:
            assert 'initial' in messages[-1]['content'] and 'private.txt' not in str(messages)
            observation=json.loads(messages[-1]['content'].split('Initial native observation:\n')[1])['observation']
            return ModelResponse(text='',tool_calls=[{'name':'native_act','arguments':{'observation_id':observation['observation_id'], 'target_ref':'text','operation':'fill','value':'changed'}}])
        assert any(m['role']=='tool' and 'changed' in m['content'] for m in messages)
        return ModelResponse(text='done')
    provider=Provider(callback)
    chain=NativeModelChain(provider,NativeAXAdapter(driver),'com.apple.TextEdit','owned.txt',tmp_path)
    report=asyncio.run(chain.run('Edit the dedicated document.'))
    assert driver.value=='changed' and report['agent_actions']==1 and report['model_requests']==2
    assert report['loop']['stop_reason']=='model_returned'
    assert (tmp_path/'agent-tools.jsonl').exists() and (tmp_path/'model.jsonl').exists()

def test_request_budget_persists_and_stops_before_extra_dispatch(tmp_path):
    from core.computer_use.native_model import NativeModelChain
    from core.evolution.budget import BudgetConfig,BudgetTracker
    budget=BudgetTracker(BudgetConfig(max_api_calls=1,input_cost_per_million=0,output_cost_per_million=0),tmp_path/'budget.sqlite')
    provider=Provider(lambda messages,kwargs:ModelResponse(text='',tool_calls=[{'name':'native_observe','arguments':{'window_ref':'owned'}}],usage={'input_tokens':5,'output_tokens':2}))
    chain=NativeModelChain(provider,NativeAXAdapter(Driver()),'com.apple.TextEdit','owned.txt',tmp_path/'task',budget=budget)
    report=asyncio.run(chain.run('Continue observing.'))
    assert len(provider.messages)==1 and report['model_requests']==1
    assert report['loop']['stop_reason']=='call_limit'
    assert BudgetTracker(budget.config,tmp_path/'budget.sqlite').total_api_calls==1

def test_action_budget_rejects_without_driver_mutation(tmp_path):
    from core.computer_use.native_model import ScopedNativeAdapter
    async def scenario():
        driver=Driver(); scoped=ScopedNativeAdapter(NativeAXAdapter(driver),'com.apple.TextEdit','owned.txt',max_actions=1)
        obs=(await scoped.observe('owned'))['observation']
        first=await scoped.act(obs['observation_id'],'fill','text','one')
        second=await scoped.act(first['observation']['observation_id'],'fill','text','two')
        assert second['error']=='ActionLimit' and second['action_applied'] is False
        assert len(driver.actions)==1 and driver.value=='one'
    asyncio.run(scenario())

def test_checker_distinguishes_failed_and_unknown_without_writing(tmp_path):
    from core.computer_use.native_model import check_native_completion
    document=tmp_path/'owned.txt';document.write_text('wrong')
    async def reread():return {'success':True,'observation':{'targets':[{'role':'AXTextArea','value':'wrong'}]}}
    assert asyncio.run(check_native_completion(document,'secret expected',reread))['status']=='failed'
    async def unavailable():raise RuntimeError('permission denied')
    document.write_text('secret expected')
    result=asyncio.run(check_native_completion(document,'secret expected',unavailable))
    assert result['status']=='unknown' and result['disk_matches'] is True
    assert document.read_text()=='secret expected'

def test_native_provider_runs_through_existing_runner_and_keeps_checker_out_of_messages(tmp_path):
    from core.computer_use.native_model import NativeChainProvider,NativeEvaluator
    from core.evolution.runner import EvolutionRunner
    from core.evolution.budget import BudgetConfig,BudgetTracker
    from core.evolution.journal import Journal
    from core.evolution.contracts import Candidate,RunSpec
    driver=Driver()
    class Environment:
        def __init__(self,document,output):self.document=document;self.adapter=NativeAXAdapter(driver)
        async def setup(self):driver.document_url=self.document.resolve().as_uri()
        async def reread(self):
            return await self.adapter.observe('owned')
        async def cleanup(self):return {'success':True}
    provider=Provider(lambda messages,kwargs:ModelResponse(text='done',usage={'input_tokens':5,'output_tokens':2}))
    task={'task_id':'native-test','instruction':'Inspect the dedicated document.','document_name':'owned.txt',
          'initial_files':{'owned.txt':'initial'},'expected':'checker-secret','output_file':'owned.txt'}
    chain=NativeChainProvider(provider,task,environment_factory=Environment)
    budget=BudgetTracker(BudgetConfig(max_api_calls=10,input_cost_per_million=0,output_cost_per_million=0),tmp_path/'budget.sqlite')
    runner=EvolutionRunner(Journal(tmp_path/'journal.sqlite'),budget,tmp_path/'workspaces',chain,step_isolation='inline')
    runner.evaluator=NativeEvaluator()
    result=runner.run(Candidate('native',(),'workflow',str(tmp_path),'frozen'),task,RunSpec('native-test','native','native-test',max_steps=1,timeout_s=480))
    assert result.score==0 and result.status=='failed'
    assert 'checker-secret' not in str(provider.messages)
    assert budget.total_api_calls==1
    checked=json.loads((Path(result.final_state_path)/'completion.json').read_text())
    assert checked['status']=='failed'

def test_scope_rejects_same_title_at_other_document_url(tmp_path):
    from core.computer_use.native_model import ScopedNativeAdapter
    class AliasDriver(Driver):
        def windows(self,bundle):
            return [{'window_ref':'owned','title':'owned.txt','bundle_id':bundle,'document_url':(tmp_path/'other'/'owned.txt').as_uri()}]
    async def scenario():
        scoped=ScopedNativeAdapter(NativeAXAdapter(AliasDriver()),'com.apple.TextEdit','owned.txt',document_path=tmp_path/'owned.txt')
        result=await scoped.initial()
        assert result['error']=='ScopeUnavailable' and scoped.allowed_ref is None
    asyncio.run(scenario())

def test_checker_passes_only_when_both_disk_and_reopened_ax_match(tmp_path):
    from core.computer_use.native_model import check_native_completion
    document=tmp_path/'owned.txt';document.write_text('expected')
    async def readback():return {'success':True,'observation':{'targets':[{'role':'AXTextArea','value':'expected'}]}}
    assert asyncio.run(check_native_completion(document,'expected',readback))['status']=='passed'
    async def wrong_ax():return {'success':True,'observation':{'targets':[{'role':'AXTextArea','value':'wrong'}]}}
    assert asyncio.run(check_native_completion(document,'expected',wrong_ax))['status']=='failed'

def test_deadline_and_model_request_cap_prevent_further_calls(tmp_path):
    from core.computer_use.native_model import NativeModelChain
    provider=Provider(lambda messages,kwargs:ModelResponse(text='',tool_calls=[{'name':'native_observe','arguments':{'window_ref':'owned'}}]))
    first=NativeModelChain(provider,NativeAXAdapter(Driver()),'com.apple.TextEdit','owned.txt',tmp_path/'expired',timeout_s=0)
    assert asyncio.run(first.run('Observe'))['model_requests']==0
    second=NativeModelChain(provider,NativeAXAdapter(Driver()),'com.apple.TextEdit','owned.txt',tmp_path/'bounded',max_requests=2)
    result=asyncio.run(second.run('Keep observing'))
    assert len(provider.messages)==2 and result['model_requests']==2 and result['loop']['stop_reason']=='call_limit'
    assert result['usage']=={'api_calls':2}  # Missing usage is unknown, not falsely zero tokens.

def test_save_evidence_requires_successful_observed_save_command():
    from core.computer_use.native_model import ScopedNativeAdapter
    class SaveDriver(Driver):
        def snapshot(self,ref):
            result=super().snapshot(ref)
            result['targets'].append({'target_ref':'save','role':'AXMenuItem','command':'s','operations':['press']})
            return result
    async def scenario():
        driver=SaveDriver();scope=ScopedNativeAdapter(NativeAXAdapter(driver),'com.apple.TextEdit','owned.txt')
        observation=(await scope.initial())['observation']
        assert scope.save_applied is False
        rejected=await scope.act('wrong','press','save')
        assert rejected['success'] is False and scope.save_applied is False
        await scope.act(rejected['observation']['observation_id'],'press','save')
        assert scope.save_applied is True
    asyncio.run(scenario())

import pytest

@pytest.mark.parametrize('phase', ['stale', 'success', 'uncertain'])
@pytest.mark.parametrize('identity', ['url', 'title', 'window'])
def test_action_reobservations_cannot_leak_changed_document(tmp_path, phase, identity):
    from core.computer_use.native_model import ScopedNativeAdapter
    class ChangedDriver(Driver):
        changed=False
        def snapshot(self, ref):
            result=super().snapshot(ref)
            if self.changed:
                result['targets'][0]['value']='PRIVATE CONTENT'
                result[{'url':'document_url','title':'title','window':'window_ref'}[identity]]={'url':(tmp_path/'private.txt').as_uri(),'title':'private.txt','window':'private'}[identity]
            return result
        def act(self,*args):
            self.changed=True
            if phase=='uncertain':raise RuntimeError('dispatch uncertain')
    async def scenario():
        driver=ChangedDriver();driver.document_url=(tmp_path/'owned.txt').as_uri()
        adapter=NativeAXAdapter(driver);scope=ScopedNativeAdapter(adapter,'com.apple.TextEdit','owned.txt',document_path=tmp_path/'owned.txt')
        obs=(await scope.initial())['observation']
        if phase=='stale':driver.changed=True
        result=await scope.act(obs['observation_id'],'fill','text','new')
        assert result['error']=='ScopeViolation'
        assert 'PRIVATE CONTENT' not in json.dumps(result)
        assert result['action_applied']=={'stale':False,'success':True,'uncertain':None}[phase]
        assert adapter.current is None
    asyncio.run(scenario())

@pytest.mark.parametrize('uncertain', [False, True])
def test_fill_invalidates_previous_save_evidence(uncertain):
    from core.computer_use.native_model import ScopedNativeAdapter
    class SaveDriver(Driver):
        def snapshot(self,ref):
            result=super().snapshot(ref);result['targets'].append({'target_ref':'save','role':'AXMenuItem','command':'s','operations':['press']});return result
        def act(self,ref,target,operation,value):
            if operation=='fill' and uncertain:raise RuntimeError('dispatch uncertain')
    async def scenario():
        scope=ScopedNativeAdapter(NativeAXAdapter(SaveDriver()),'com.apple.TextEdit','owned.txt')
        obs=(await scope.initial())['observation']
        saved=await scope.act(obs['observation_id'],'press','save')
        assert scope.save_applied
        await scope.act(saved['observation']['observation_id'],'fill','text','new')
        assert not scope.save_applied
    asyncio.run(scenario())

@pytest.mark.parametrize('kind', ['absolute', 'escape', 'symlink', 'missing_fixture', 'wrong_fixture'])
def test_provider_rejects_unsafe_or_unprepared_document_before_environment(tmp_path,kind):
    from core.computer_use.native_model import NativeChainProvider
    outside=tmp_path.parent/'outside-native.txt';outside.write_text('private')
    name={'absolute':str(outside),'escape':'../outside-native.txt'}.get(kind,'owned.txt')
    if kind=='symlink':(tmp_path/name).symlink_to(outside)
    else:(tmp_path/'owned.txt').write_text('wrong' if kind=='wrong_fixture' else 'initial')
    task={'task_id':'native','document_name':name,'initial_files':{} if kind=='missing_fixture' else {name:'initial'},'instruction':'inspect','expected':'new'}
    def forbidden(*args):raise AssertionError('environment must not be created')
    chain=NativeChainProvider(Provider(lambda *args:None),task,environment_factory=forbidden)
    with pytest.raises(ValueError):asyncio.run(chain._run(tmp_path))
    assert outside.read_text()=='private'


def test_runner_records_native_call_limit_and_real_chain_counts(tmp_path):
    from core.computer_use.native_model import NativeChainProvider,NativeEvaluator
    from core.evolution.runner import EvolutionRunner
    from core.evolution.budget import BudgetConfig,BudgetTracker
    from core.evolution.journal import Journal
    from core.evolution.contracts import Candidate,RunSpec
    driver=Driver()
    class Environment:
        def __init__(self,document,output):self.document=document;self.adapter=NativeAXAdapter(driver)
        async def setup(self):driver.document_url=self.document.resolve().as_uri()
        async def reread(self):return await self.adapter.observe('owned')
        async def cleanup(self):return {'success':True}
    provider=Provider(lambda messages,kwargs:ModelResponse(text='',tool_calls=[{'name':'native_observe','arguments':{'window_ref':'owned'}}]))
    task={'task_id':'native-limit','instruction':'Keep observing','document_name':'owned.txt','initial_files':{'owned.txt':'initial'},'expected':'new'}
    chain=NativeChainProvider(provider,task,environment_factory=Environment,max_model_calls=1)
    runner=EvolutionRunner(Journal(tmp_path/'journal.sqlite'),BudgetTracker(BudgetConfig(max_api_calls=10,input_cost_per_million=0,output_cost_per_million=0),tmp_path/'budget.sqlite'),tmp_path/'workspaces',chain,step_isolation='inline')
    runner.evaluator=NativeEvaluator()
    result=runner.run(Candidate('native',(),'workflow',str(tmp_path),'frozen'),task,RunSpec('native-limit','native','native-limit',max_steps=1,timeout_s=480))
    assert result.metadata['chain_model_calls']==1
    assert result.metadata['chain_tool_calls']==1
    assert result.metadata['chain_steps']>0
    assert result.metadata['chain'][-1]['stop_reason']=='call_limit'

@pytest.mark.parametrize('success',[False,True])
def test_observe_sanitizes_all_returned_observations(tmp_path,success):
    from core.computer_use.native_model import ScopedNativeAdapter
    class Adapter:
        current=None
        async def observe(self,ref):
            self.current={'window_ref':'owned','title':'owned.txt','document_url':(tmp_path/'private.txt').as_uri(),'targets':[{'value':'PRIVATE CONTENT'}]}
            return {'success':success,'observation':self.current,'action_applied':False}
    async def scenario():
        adapter=Adapter();scope=ScopedNativeAdapter(adapter,'com.apple.TextEdit','owned.txt',document_path=tmp_path/'owned.txt');scope.allowed_ref='owned'
        result=await scope.observe('owned')
        assert result['error']=='ScopeViolation' and 'PRIVATE CONTENT' not in json.dumps(result)
        assert adapter.current is None
    asyncio.run(scenario())
