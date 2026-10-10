import hashlib
import json
from pathlib import Path

import pytest

from core.evolution.budget import BudgetTracker
from core.evolution.bundle import RecoveryPolicy
from core.evolution.contracts import Candidate
from core.evolution.journal import Journal
from core.evolution.mutator import bundle_digest
from core.evolution.promotion import Promoter
from core.evolution.recovery_mutator import RecoveryMutator
from test_evolution_mutation import _Generator


STOP = 'def recover(error, history, checkpoints):\n    return {"action":"stop"}\n'
FIX = 'def recover(error, history, checkpoints):\n    return {"action":"switch_tool","tool_call":{"name":"skill_call","arguments":{}}}\n'


def setup(tmp_path, code=FIX):
    path = tmp_path / 'base'
    if not path.exists():
        path.mkdir()
        (path / 'recovery.py').write_text(STOP)
        (path / 'manifest.json').write_text(json.dumps({'version':1,'skills':[], 'modules':{'recovery':{'entrypoint':'recovery.py:recover','digest':hashlib.sha256(STOP.encode()).hexdigest()}}}))
    parent = Candidate('base', (), 'recovery', str(path), bundle_digest(path))
    model = _Generator([{'hypothesis':'Test observed recovery change', 'code':code}]*2)
    journal, budget = Journal(tmp_path/'journal.sqlite'), BudgetTracker()
    class Provider:
        def __init__(self, candidate):
            self.policy = RecoveryPolicy.from_bundle(candidate.bundle_path)
        def generate_step(self, task, step, history, workspace):
            decision = self.policy.recover({'reason':'no_tool_calls'}, [], [])
            if decision['action']=='switch_tool':
                (workspace/'output.json').write_text('1')
            return {'action':{'name':'finish'},'usage':{'input_tokens':1,'output_tokens':1},
                    'chain':{'stop_reason':'model_returned','model_errors':[], 'recovery_events':[]}}
    promoter=Promoter(journal,budget,Provider,tmp_path/'loop',kernel_max_steps=1)
    from core.evolution.recovery_loop import RecoveryLoop
    loop=RecoveryLoop(promoter,lambda slot:RecoveryMutator(model,budget,journal,slot), promoter.root,parent,[task('validation','validation')])
    return loop, model, parent


def task(name, split='dev'):
    return {'task_id':name,'split':split,'instruction':'Create output.json',
            'scoring_criteria':{'type':'json_exact_match','file':'output.json','expected':1},
            'secret':'NOT_VISIBLE'}


def test_failure_generates_validation_promotes_restart_consumes(tmp_path):
    loop,model,parent=setup(tmp_path)
    report=loop.run_task(task('source'))
    assert report['comparison']['promoted']
    assert report['result']['status']=='failed'
    assert 'NOT_VISIBLE' not in json.dumps(model.messages)
    assert all(pair['parent']['run_id'].startswith('validation-') for pair in report['comparison']['pairs'])
    restarted,_,_=setup(tmp_path)
    reused=restarted.run_task(task('next','reuse'))
    assert reused['result']['status']=='passed'
    assert reused['candidate']['digest']!=parent.digest


def test_rejection_and_resource_caps_survive_restart(tmp_path):
    loop,_,parent=setup(tmp_path,STOP)
    assert not loop.run_task(task('first'))['comparison']['promoted']
    restarted,_,_=setup(tmp_path,STOP)
    assert not restarted.run_task(task('second'))['comparison']['promoted']
    assert restarted.run_task(task('third'))['stop_reason']=='candidate_limit'
    assert restarted.load_active().digest==parent.digest


def test_bad_digest_falls_back_before_task(tmp_path):
    loop,_,parent=setup(tmp_path)
    loop.run_task(task('first'))
    active=loop.load_active()
    (Path(active.bundle_path)/'recovery.py').write_text('corrupted')
    assert loop.load_active().digest==parent.digest
    state=json.loads(loop.state_path.read_text())
    assert state['disabled']


def test_model_error_after_partial_write_never_mutates(tmp_path):
    loop,model,_=setup(tmp_path)
    original=loop.promoter.provider_factory
    def factory(candidate):
        provider=original(candidate)
        generate=provider.generate_step
        def fail(*args):
            result=generate(*args)
            result['chain']['model_errors']=['Connection reset']
            return result
        provider.generate_step=fail
        return provider
    loop.promoter.provider_factory=factory
    report=loop.run_task(task('transport'))
    assert report['failure_kind']=='infrastructure'
    assert report['comparison'] is None
    assert not model.messages


def test_runtime_fault_disables_for_next_task_without_replay(tmp_path):
    loop,_,parent=setup(tmp_path)
    loop.run_task(task('first'))
    original=loop.promoter.provider_factory
    writes=[]
    def factory(candidate):
        provider=original(candidate)
        generate=provider.generate_step
        def fail(task,step,history,workspace):
            writes.append(candidate.digest)
            output=generate(task,step,history,workspace)
            output['chain']['recovery_events']=[{'decision':{'action':'stop'}, 'error':'RuntimeError: worker'}]
            return output
        provider.generate_step=fail
        return provider
    loop.promoter.provider_factory=factory
    report=loop.run_task(task('fault','reuse'))
    assert report['stop_reason']=='runtime_rollback'
    assert len(writes)==1
    assert loop.load_active().digest==parent.digest
    assert loop.run_task(task('fault','reuse'))==report
    assert len(writes)==1


def test_incompatible_active_and_invalid_parent_fail_closed(tmp_path):
    import pytest
    loop,_,parent=setup(tmp_path)
    loop.run_task(task('first'))
    active=loop.load_active()
    manifest=Path(active.bundle_path)/'manifest.json'
    data=json.loads(manifest.read_text()); data['version']=99
    manifest.write_text(json.dumps(data))
    active_data=json.loads((loop.root/'active.json').read_text())
    active_data['candidate']['digest']=bundle_digest(Path(active.bundle_path))
    (loop.root/'active.json').write_text(json.dumps(active_data))
    assert loop.load_active().digest==parent.digest
    (Path(parent.bundle_path)/'recovery.py').write_text('bad')
    with pytest.raises(ValueError):
        loop.run_task(task('never-runs'))


def test_new_process_consumes_persisted_candidate_without_candidate_path(tmp_path):
    import subprocess
    import sys
    loop,_,parent=setup(tmp_path)
    loop.run_task(task('first'))
    code = '''import json, sys
from pathlib import Path
sys.path.insert(0, 'tests')
from test_recovery_loop import setup,task
loop,_,_=setup(Path(sys.argv[1]))
print(json.dumps(loop.run_task(task('subprocess','reuse'))))
'''
    process=subprocess.run([sys.executable,'-c',code,str(tmp_path)],capture_output=True,text=True,check=True)
    result=json.loads(process.stdout.strip().splitlines()[-1])
    assert result['candidate']['digest']!=parent.digest
    assert result['result']['status']=='passed'


def test_tool_action_cap_blocks_thirteenth_write(tmp_path):
    from core.evolution.agent_provider import KageChainProvider
    from core.model_provider import ModelResponse
    class Model:
        def generate(self, **kwargs):
            return ModelResponse(text='',tool_calls=[{'name':'write_file','arguments':{'path':f'{i}.txt','content':'x'}} for i in range(13)],usage={'input_tokens':1,'output_tokens':1})
    provider=KageChainProvider(Model(),provider_mode='fixture',max_tool_actions=12)
    result=provider.generate_step({'task_id':'cap','instruction':'Write files'},1,[],tmp_path)
    assert not (tmp_path/'12.txt').exists()
    assert len(list(tmp_path.glob('*.txt')))==12
    assert result['chain']['tool_action_limit_reached']
    assert result['chain']['tool_actions_executed']==12


@pytest.mark.parametrize('errors', [
    ['network failure after tool'],
    ['InvalidToolArguments: write_file (finish_reason=length)', 'HTTPError: 503'],
    ['TimeoutError: timed out'],
])
def test_validation_transport_error_after_correct_output_rejects(tmp_path, errors):
    loop,_,_=setup(tmp_path)
    original=loop.promoter.provider_factory
    def factory(candidate):
        provider=original(candidate)
        generate=provider.generate_step
        def fail(task,*args):
            output=generate(task,*args)
            if task['task_id']=='validation' and candidate.parent_ids:
                output['chain']['model_errors']=errors
            return output
        provider.generate_step=fail
        return provider
    loop.promoter.provider_factory=factory
    assert not loop.run_task(task('source'))['comparison']['promoted']


@pytest.mark.parametrize('malformed', [False, True])
def test_real_chain_generated_source_frozen_skill_and_feedback_boundary(tmp_path, monkeypatch, malformed):
    from core.evolution.agent_provider import KageChainProvider
    from core.evolution.skills import SkillCatalog
    from core.model_provider import ModelResponse
    from test_agentic_loop_multistep import SequenceModel, call
    from test_evolution_skills import _bundle
    loop,_,parent=setup(tmp_path)
    source=tmp_path/'skill'; _bundle(source)
    bundle=Path(parent.bundle_path)
    manifest=json.loads((bundle/'manifest.json').read_text())
    manifest['skills']=json.loads((source/'manifest.json').read_text())['skills']
    skill_code = 'def run(arguments, context):\n    import json\n    from pathlib import Path\n    rows=[{"name":r["name"].strip()} for r in arguments["records"]]\n    (Path(context["workspace_dir"])/"normalized.json").write_text(json.dumps(rows))\n    return {"success":True}\n'
    descriptor = manifest['skills'][0]
    canonical = json.dumps({k:v for k,v in descriptor.items() if k!='digest'},sort_keys=True,separators=(',',':'))
    descriptor['digest']=hashlib.sha256(canonical.encode()+b'\n'+skill_code.encode()).hexdigest()
    (bundle/'normalize.py').write_text(skill_code)
    (bundle/'manifest.json').write_text(json.dumps(manifest))
    parent=Candidate('base',(), 'recovery',str(bundle),bundle_digest(bundle))
    loop.state_path.unlink()
    code='''import json
def recover(error, history, checkpoints):
    rows = json.loads(json.loads(history[0]['result'])['content'])
    skill = error['available_skills'][0]
    return {'action':'switch_tool', 'tool_call':{'name':'skill_call', 'arguments':{'skill_id':skill['skill_id'],'digest':skill['digest'],'arguments':{'records':rows}}}}
'''
    model=_Generator([{'hypothesis':'Use the available transform after observed read', 'code':code}])
    parsed_error = None
    if malformed:
        from core.model_provider import OpenAICompatibleProvider
        import io
        import urllib.request
        body = {'choices':[{'finish_reason':'length','message':{'content':'', 'tool_calls':[
            {'function':{'name':'write_file','arguments':'{"path": "truncated'}}]}}],
            'usage':{'prompt_tokens':3,'completion_tokens':2}}
        monkeypatch.setattr(urllib.request, 'urlopen', lambda *a, **kw:io.BytesIO(json.dumps(body).encode()))
        parsed_error = OpenAICompatibleProvider('fixture-key', base_url='https://fixture.invalid').generate([])
        assert parsed_error.error == 'InvalidToolArguments: write_file (finish_reason=length)'
    def factory(candidate):
        catalog=SkillCatalog.from_bundle(candidate.bundle_path)
        policy=RecoveryPolicy.from_bundle(candidate.bundle_path,skill_catalog=catalog)
        responses=[call('read_file',path='input.json'),parsed_error if malformed else ModelResponse(text='thinking'),ModelResponse(text='done')]
        return KageChainProvider(SequenceModel(responses),provider_mode='fixture',skill_catalog=catalog,recovery_policy=policy,max_tool_actions=12)
    promoter=Promoter(loop.promoter.journal,loop.promoter.budget,factory,loop.root,kernel_max_steps=1)
    def case(name,split):
        return {'task_id':name,'split':split,'instruction':'Read input.json and normalize records into normalized.json',
                'initial_files':{'input.json':'[{"name":"  Ada  "}]'},
                'scoring_criteria':{'type':'json_exact_match','file':'normalized.json','expected':[{'name':'Ada'}]},'hidden_note':'NEVER_TEACH'}
    from core.evolution.recovery_loop import RecoveryLoop
    loop=RecoveryLoop(promoter,lambda slot:RecoveryMutator(model,promoter.budget,promoter.journal,slot),loop.root,parent,[case('blind','validation')])
    report=loop.run_task(case('source','dev'))
    assert report['comparison']['promoted']
    if malformed:
        child_run = report['comparison']['pairs'][0]['child']
        assert child_run['status']=='passed'
        assert child_run['metadata']['chain'][0]['model_errors']==[parsed_error.error]
        assert child_run['metadata']['chain'][0]['recovery_events'][0]['decision']['action']=='switch_tool'
    reused=loop.run_task(case('reuse','reuse'))
    assert reused['result']['status']=='passed'
    chain=reused['result']['metadata']['chain'][0]
    assert chain['recovery_trace'][0]['module_sha256']
    assert any(row['observation']['actor']=='recovery_policy' for row in map(json.loads,Path(reused['result']['trace_path']).read_text().splitlines()) if 'observation' in row)
    assert 'NEVER_TEACH' not in json.dumps(model.messages)
    assert json.loads((Path(loop.load_active().bundle_path)/'manifest.json').read_text())['skills']==manifest['skills']
    import subprocess, sys
    subprocess_code = """import json, sys
from pathlib import Path
sys.path.insert(0, 'tests')
from core.evolution.agent_provider import KageChainProvider
from core.evolution.bundle import RecoveryPolicy
from core.evolution.skills import SkillCatalog
from core.evolution.budget import BudgetTracker
from core.evolution.journal import Journal
from core.evolution.promotion import Promoter
from core.evolution.recovery_loop import RecoveryLoop, _candidate
from core.model_provider import ModelResponse
from test_agentic_loop_multistep import SequenceModel, call
root=Path(sys.argv[1]); state=json.loads((root/'recovery_state.json').read_text())
protocol=state['protocol']; bootstrap=_candidate(protocol['bootstrap'])
def factory(candidate):
    catalog=SkillCatalog.from_bundle(candidate.bundle_path)
    policy=RecoveryPolicy.from_bundle(candidate.bundle_path,skill_catalog=catalog)
    return KageChainProvider(SequenceModel([call('read_file',path='input.json'),ModelResponse(text='thinking'),ModelResponse(text='done')]),provider_mode='fixture',skill_catalog=catalog,recovery_policy=policy,max_tool_actions=12)
promoter=Promoter(Journal(root.parent/'journal.sqlite'),BudgetTracker(),factory,root,kernel_max_steps=1)
def forbidden(slot):
    raise AssertionError('reuse must not generate')
loop=RecoveryLoop(promoter,forbidden,root,bootstrap,protocol['validation_tasks'])
task={**protocol['validation_tasks'][0], 'task_id':'new-process', 'split':'reuse'}
print(json.dumps(loop.run_task(task)))
"""
    process=subprocess.run([sys.executable,'-c',subprocess_code,str(loop.root)],capture_output=True,text=True,check=True)
    restarted=json.loads(process.stdout.strip().splitlines()[-1])
    assert restarted['result']['status']=='passed'
    assert restarted['candidate']['digest']==reused['candidate']['digest']
    assert restarted['result']['metadata']['chain'][0]['recovery_trace'][0]['module_sha256']==chain['recovery_trace'][0]['module_sha256']



def test_evaluation_limit_and_interrupted_task_stay_spent(tmp_path):
    from core.evolution.recovery_loop import RecoveryLoop
    loop,model,parent=setup(tmp_path)
    loop.state_path.unlink()
    loop=RecoveryLoop(loop.promoter,loop.mutator_factory,loop.root,parent,loop.validation_tasks,max_evaluations=1)
    report=loop.run_task(task('one'))
    assert report['stop_reason']=='evaluation_limit' and not model.messages
    restarted=RecoveryLoop(loop.promoter,loop.mutator_factory,loop.root,parent,loop.validation_tasks,max_evaluations=1)
    assert restarted.run_task(task('two'))['result'] is None
    assert restarted.state['evaluations']==1


def test_interrupted_and_network_generation_slots_never_regenerate(tmp_path):
    import pytest
    loop,model,_=setup(tmp_path)
    def interrupted(**kwargs):
        raise KeyboardInterrupt('interrupted provider')
    model.generate=interrupted
    with pytest.raises(KeyboardInterrupt):
        loop.run_task(task('interrupted'))
    restarted,newmodel,_=setup(tmp_path)
    assert restarted.run_task(task('interrupted'))['stop_reason']=='interrupted'
    assert not newmodel.messages
    assert restarted.state['candidates']==1 and restarted.state['evaluations']==3


def test_step_limit_is_not_capability_failure(tmp_path):
    loop,model,_=setup(tmp_path)
    original=loop.promoter.provider_factory
    def factory(candidate):
        provider=original(candidate)
        generate=provider.generate_step
        def limited(*args):
            output=generate(*args); output['chain']['stop_reason']='step_limit'
            return output
        provider.generate_step=limited
        return provider
    loop.promoter.provider_factory=factory
    assert loop.run_task(task('limited'))['failure_kind']=='resource_or_infrastructure'
    assert not model.messages


def test_recovery_teacher_request_bytes_are_bounded_before_model_call(tmp_path):
    import pytest
    loop,model,parent=setup(tmp_path)
    mutator=loop.mutator_factory(loop.root/'oversize')
    with pytest.raises(ValueError,match='bytes'):
        mutator.propose(parent,{'task_id':'large','instruction':'x'*12000})
    assert not model.messages
    assert loop.promoter.budget.total_api_calls==0


def test_provider_error_stops_slot_and_same_task_does_not_regenerate(tmp_path):
    from core.model_provider import ModelResponse
    loop,model,_=setup(tmp_path)
    requests=[]
    def unavailable(**kwargs):
        requests.append(kwargs)
        return ModelResponse(text='',error='network disconnected')
    model.generate=unavailable
    report=loop.run_task(task('network'))
    assert report['stop_reason']=='learning_stopped'
    assert len(requests)==1
    restarted,model2,_=setup(tmp_path)
    assert restarted.run_task(task('network'))==report
    assert not model2.messages


def test_permission_failure_is_not_a_mutation_signal(tmp_path):
    from core.evolution.contracts import RunResult
    from core.evolution.recovery_loop import classify_failure
    trace=tmp_path/'trace.jsonl'
    trace.write_text(json.dumps({'action':{'name':'write_file'},'observation':{'success':False,'outcome':'error','content':json.dumps({'success':False,'error':'PermissionError: denied'})}})+'\n')
    result=RunResult('permission','failed',0,str(trace))
    assert classify_failure(result)=='infrastructure'


def test_disabled_digest_authoritative_after_interrupted_pointer_write(tmp_path):
    loop,_,parent=setup(tmp_path)
    loop.run_task(task('first'))
    active=loop.load_active()
    loop.state['disabled'].append({'candidate':json.loads(json.dumps(active.__dict__)),'reason':'runtime fault before pointer publication'})
    loop._save()
    restarted,_,_=setup(tmp_path)
    assert restarted.load_active().digest==parent.digest


def test_failed_verified_parent_uses_grandparent_then_exhausts(tmp_path):
    import pytest
    from core.evolution.recovery_loop import RecoveryLoop
    loop,_,parent=setup(tmp_path)
    loop.state_path.unlink()
    validation={**task('validation','validation'), 'scoring_criteria':{'type':'json_exact_match','file':'output.json','expected':[1,2]}}
    first_factory=loop.promoter.provider_factory
    def partial_factory(candidate):
        provider=first_factory(candidate)
        generate=provider.generate_step
        def run(task,*args):
            result=generate(task,*args)
            workspace=args[-1]
            if candidate.parent_ids:
                (workspace/'output.json').write_text('[1]' if len(candidate.parent_ids)==1 and candidate.parent_ids[0]=='base' else '[1,2]')
            return result
        provider.generate_step=run
        return provider
    loop.promoter.provider_factory=partial_factory
    loop=RecoveryLoop(loop.promoter,loop.mutator_factory,loop.root,parent,[validation])
    loop.run_task(task('first'))
    first=loop.load_active()
    generator=_Generator([{'hypothesis':'second fixture', 'code':FIX+'\n# second\n'}])
    second=RecoveryMutator(generator,loop.promoter.budget,loop.promoter.journal,loop.root/'second').propose(first,{})
    comparison=loop.promoter.compare(first,second,[validation],promotion_split='validation')
    assert comparison['promoted']
    assert loop.load_active().digest==second.digest
    assert loop._disable(second,'runtime second').digest==first.digest
    assert loop._disable(first,'runtime first').digest==parent.digest
    with pytest.raises(ValueError,match='verified'):
        loop._disable(parent,'runtime base')


def test_valid_but_unverified_active_pointer_never_loads(tmp_path):
    loop,_,parent=setup(tmp_path)
    child=loop.mutator_factory(loop.root/'unverified').propose(parent,{})
    (loop.root/'active.json').write_text(json.dumps({'candidate':child.__dict__,'last_verified_parent':parent.__dict__}))
    assert loop.load_active().digest==parent.digest


def test_changed_task_id_payload_rejected_before_dispatch(tmp_path):
    import pytest
    loop,_,_=setup(tmp_path)
    loop.run_task(task('same'))
    restarted,_,_=setup(tmp_path)
    with pytest.raises(ValueError,match='task_id'):
        restarted.run_task({**task('same'),'instruction':'changed instruction'})
    assert restarted.state['evaluations']==3


def test_real_chain_permission_error_does_not_call_teacher(tmp_path,monkeypatch):
    from core.evolution.agent_provider import KageChainProvider
    from core.model_provider import ModelResponse
    from test_agentic_loop_multistep import SequenceModel,call
    loop,teacher,_=setup(tmp_path)
    read_text=Path.read_text
    def denied(path,*args,**kwargs):
        if path.name=='input.json':
            raise PermissionError('fixture denied read')
        return read_text(path,*args,**kwargs)
    monkeypatch.setattr(Path,'read_text',denied)
    loop.promoter.provider_factory=lambda candidate:KageChainProvider(SequenceModel([call('read_file',path='input.json'),ModelResponse(text='done')]),provider_mode='fixture')
    report=loop.run_task({**task('permission'),'initial_files':{'input.json':'1'}})
    assert report['failure_kind']=='infrastructure'
    assert not teacher.messages


def test_baseline_runtime_fault_stops_without_proposal(tmp_path):
    loop,teacher,_=setup(tmp_path)
    original=loop.promoter.provider_factory
    def factory(candidate):
        provider=original(candidate); generate=provider.generate_step
        def fault(*args):
            output=generate(*args); output['chain']['recovery_events']=[{'error':'baseline worker fault'}]
            return output
        provider.generate_step=fault
        return provider
    loop.promoter.provider_factory=factory
    report=loop.run_task(task('base-fault'))
    assert report['stop_reason']=='no_verified_parent'
    assert not teacher.messages


def test_validation_machine_tool_permission_error_rejects(tmp_path):
    loop,_,_=setup(tmp_path)
    original=loop.promoter.provider_factory
    def factory(candidate):
        provider=original(candidate); generate=provider.generate_step
        def denied(task,*args):
            output=generate(task,*args)
            if task['task_id']=='validation' and candidate.parent_ids:
                output['chain']['tool_errors']=[{'error_type':'PermissionError','error_message':'denied read','outcome':'error'}]
            return output
        provider.generate_step=denied
        return provider
    loop.promoter.provider_factory=factory
    assert not loop.run_task(task('validation-permission'))['comparison']['promoted']


@pytest.mark.parametrize('errors,expected', [
    (['InvalidToolArguments: write_file (finish_reason=length)'],'capability'),
    (['InvalidToolArguments: skill_call (arguments must be an object)'],'capability'),
    (['InvalidToolArguments: write_file (finish_reason=length)', 'HTTPError: 503'],'infrastructure'),
    (['HTTPError: 503'],'infrastructure'),
    (['TimeoutError: timed out'],'infrastructure'),
    (['unrecognized provider failure'],'infrastructure'),
])
def test_model_error_classification_is_narrow(tmp_path, errors, expected):
    from core.evolution.contracts import RunResult
    from core.evolution.recovery_loop import classify_failure
    trace=tmp_path/'empty.jsonl'; trace.write_text('')
    result=RunResult('classified','failed',0,str(trace),metadata={'chain':[{'model_errors':errors}]})
    assert classify_failure(result)==expected


def test_parse_failure_without_usable_tool_can_trigger_generation(tmp_path):
    from core.evolution.agent_provider import KageChainProvider
    from core.model_provider import ModelResponse
    from test_agentic_loop_multistep import SequenceModel
    loop,teacher,_=setup(tmp_path)
    original=loop.promoter.provider_factory
    def factory(candidate):
        if not candidate.parent_ids:
            return KageChainProvider(SequenceModel([ModelResponse(text='',error='InvalidToolArguments: write_file (finish_reason=length)')]),provider_mode='fixture')
        return original(candidate)
    loop.promoter.provider_factory=factory
    report=loop.run_task(task('parse-source'))
    assert report['result']['status']=='failed'
    assert report['failure_kind']=='capability'
    assert len(teacher.messages)==1
    assert report['comparison']['promoted']
