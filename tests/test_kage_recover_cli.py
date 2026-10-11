import json
from dataclasses import asdict
import pytest
from test_recovery_loop import setup, task


def config(tmp_path):
    _, _, parent = setup(tmp_path)
    validation = tmp_path/'validation.json'
    validation.write_text(json.dumps({'tasks':[task('validation','validation')]}))
    path = tmp_path/'config.json'
    path.write_text(json.dumps({'root':str(tmp_path/'cli'), 'bootstrap_candidate':asdict(parent),
        'validation_suite':str(validation), 'student_settings':{'model':{'local_runtime':{'port':18082},'hybrid':{'enabled':False}}},
        'teacher_settings':str(tmp_path/'PRIVATE-MISSING.json'),
        'teacher_budget':{'max_api_calls':6,'max_cost_usd':.03,'input_cost_per_million':.3,'output_cost_per_million':1.2}}))
    return path


def test_unauthorized_teacher_not_read_and_protocol_persists(tmp_path, monkeypatch):
    from scripts import kage_recover as cli
    path = config(tmp_path)
    monkeypatch.setattr(cli,'DockerSkillRunner',lambda **kw: object())
    loop = cli.build_loop(path)
    with pytest.raises(RuntimeError,match='paid_teacher_not_authorized'):
        loop.mutator_factory(tmp_path/'mutation')
    restarted = cli.build_loop(path)
    assert restarted.root == loop.root
    frozen=(loop.root/'protocol.json').read_text()
    assert 'PRIVATE-MISSING' not in frozen and 'api_key' not in frozen
    data=json.loads(path.read_text()); data['teacher_budget']['max_api_calls']=5
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='protocol changed'):
        cli.build_loop(path)


def test_student_cloud_settings_rejected(tmp_path):
    from scripts import kage_recover as cli
    path=config(tmp_path); data=json.loads(path.read_text())
    data['student_settings']['model']['hybrid']['enabled']=True
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='local-only'):
        cli.build_loop(path)


def test_teacher_byte_bound_before_reservation(tmp_path):
    from scripts.kage_recover import BoundedRecoveryMutator
    from core.evolution.budget import BudgetTracker
    model=type('Model',(),{'_request_payload':lambda self,messages,**kw:{'messages':messages,**kw},
        '_serialize_request':lambda self,payload:json.dumps(payload).encode()})()
    budget=BudgetTracker()
    mutator=BoundedRecoveryMutator(model,budget,None,tmp_path)
    with pytest.raises(ValueError,match='12000'):
        mutator._validate_request([{'content':'中'*12000}])
    assert budget.total_api_calls==0 and not budget._active_reservations


def test_cli_runs_and_writes_report_without_private_config(tmp_path,monkeypatch,capsys):
    from scripts import kage_recover as cli
    path=config(tmp_path)
    monkeypatch.setattr(cli,'DockerSkillRunner',lambda **kw:object())
    class Provider:
        def __init__(self,*args,**kwargs): pass
        def generate_step(self,task,step,history,workspace):
            return {'action':{'name':'finish'},'usage':{'input_tokens':1,'output_tokens':1},
                'chain':{'model_errors':[],'stop_reason':'model_returned'}}
    monkeypatch.setattr(cli,'KageChainProvider',Provider)
    source=tmp_path/'source.json'; source.write_text(json.dumps(task('source')))
    report=cli.main(['--config',str(path),'--task',str(source),'--allow-paid-teacher'])
    assert report['result']['status']=='failed'
    assert 'invalid_private_teacher_settings' in report['learning_error']
    assert list((tmp_path/'cli'/'task-reports').glob('*.json'))
    assert 'PRIVATE-MISSING' not in capsys.readouterr().out


def test_missing_authorization_preflight_preserves_state_without_dispatch(tmp_path,monkeypatch):
    from scripts import kage_recover as cli
    path=config(tmp_path)
    root=tmp_path/'cli'; root.mkdir()
    state=root/'recovery_state.json'
    state.write_text(json.dumps({'candidates':1,'evaluations':3}))
    before=state.read_bytes()
    def forbidden(*args,**kwargs):
        pytest.fail('preflight must not construct or dispatch execution')
    monkeypatch.setattr(cli,'build_loop',forbidden)
    monkeypatch.setattr(cli,'DockerSkillRunner',forbidden)
    monkeypatch.setattr(cli,'RecordedLocalProvider',forbidden)
    source=tmp_path/'source.json'; source.write_text(json.dumps(task('source')))
    with pytest.raises(RuntimeError,match='paid_teacher_not_authorized'):
        cli.main(['--config',str(path),'--task',str(source)])
    assert state.read_bytes()==before


def test_paths_expand_home_and_teacher_defaults_to_canonical(tmp_path,monkeypatch):
    from scripts import kage_recover as cli
    path=config(tmp_path); cfg=json.loads(path.read_text())
    cfg.pop('teacher_settings')
    cfg['root']='~/persistent-root'
    path.write_text(json.dumps(cfg))
    monkeypatch.setenv('HOME',str(tmp_path))
    private=tmp_path/'.config/kage/teachers/deepseek.json'; private.parent.mkdir(parents=True)
    private.write_text(json.dumps({'model':{'cloud_api':{'api_key':'PRIVATE-KEY','model_name':'deepseek-flash','base_url':'https://api.deepseek.com'}}}))
    monkeypatch.setattr(cli,'DockerSkillRunner',lambda **kw:object())
    loop=cli.build_loop(path,True)
    assert loop.root==tmp_path/'persistent-root'
    mutator=loop.mutator_factory(tmp_path/'slot')
    assert mutator.model.model_name=='deepseek-flash'
    assert 'PRIVATE-KEY' not in (loop.root/'teacher-protocol.json').read_text()


def continuation(tmp_path,monkeypatch):
    from scripts import kage_recover as cli
    path=config(tmp_path)
    monkeypatch.setattr(cli,'DockerSkillRunner',lambda **kw:object())
    prior=cli.build_loop(path)
    state=json.loads(prior.state_path.read_text()); state.update(candidates=1,evaluations=3)
    prior.state_path.write_text(json.dumps(state))
    reservation=prior.promoter.budget.reserve(10,10,api_call_cap=8)
    prior.promoter.budget.settle(reservation,{'input_tokens':8,'output_tokens':8,'api_calls':8})
    from core.evolution.budget import BudgetTracker, BudgetConfig
    teacher=BudgetTracker(BudgetConfig(max_api_calls=6,max_cost_usd=.03,input_cost_per_million=.3,output_cost_per_million=1.2),prior.root/'teacher-budget.sqlite')
    reservation=teacher.reserve(100,100,'optimizer'); teacher.settle(reservation,{'input_tokens':100,'output_tokens':100})
    cfg=json.loads(path.read_text()); cfg['continuation_root']=str(prior.root); cfg['root']=str(tmp_path/'continued')
    path.write_text(json.dumps(cfg))
    return cli,path,prior


def test_continuation_deducts_limits_and_reuses_spent_budgets(tmp_path,monkeypatch):
    cli,path,prior=continuation(tmp_path,monkeypatch)
    before=prior.state_path.read_bytes()
    resumed=cli.build_loop(path)
    assert (resumed.max_candidates,resumed.max_evaluations)==(1,9)
    assert resumed.promoter.budget.db_path==prior.root/'local-budget.sqlite'
    assert resumed.promoter.budget.total_api_calls==8
    cfg=json.loads(path.read_text()); cfg['teacher_settings']=None; path.write_text(json.dumps(cfg))
    private=tmp_path/'.config/kage/teachers/deepseek.json'; private.parent.mkdir(parents=True)
    private.write_text(json.dumps({'model':{'cloud_api':{'api_key':'secret','model_name':'deepseek-flash','base_url':'https://api.deepseek.com'}}}))
    monkeypatch.setenv('HOME',str(tmp_path))
    mutator=cli.build_loop(path,True).mutator_factory(tmp_path/'slot')
    assert mutator.budget.db_path==prior.root/'teacher-budget.sqlite'
    assert mutator.budget.total_api_calls==1
    assert prior.state_path.read_bytes()==before
    state=json.loads(before); state['evaluations']=4; prior.state_path.write_text(json.dumps(state))
    with pytest.raises(ValueError,match='protocol changed'):
        cli.build_loop(path)


@pytest.mark.parametrize('bad',['bootstrap','caps','active_child','exhausted','corrupt','missing_budget'])
def test_continuation_rejects_invalid_prior(tmp_path,monkeypatch,bad):
    cli,path,prior=continuation(tmp_path,monkeypatch)
    state=json.loads(prior.state_path.read_text())
    if bad=='bootstrap': state['protocol']['bootstrap']['digest']='other'
    elif bad=='caps': state['protocol']['max_candidates']=3
    elif bad=='active_child':
        candidate=dict(state['protocol']['bootstrap']); candidate['digest']='child'
        (prior.root/'active.json').write_text(json.dumps({'candidate':candidate}))
    elif bad=='exhausted': state['candidates']=2
    elif bad=='missing_budget': (prior.root/'teacher-budget.sqlite').unlink()
    if bad=='corrupt': prior.state_path.write_text('invalid')
    else: prior.state_path.write_text(json.dumps(state))
    with pytest.raises(ValueError,match='continuation'):
        cli.build_loop(path)


def test_continuation_exclusively_claims_one_root_and_retires_prior(tmp_path,monkeypatch):
    cli,path,prior=continuation(tmp_path,monkeypatch)
    first=cli.build_loop(path)
    assert cli.build_loop(path).root==first.root
    claim=prior.root/'continuation.json'
    assert json.loads(claim.read_text())['root']==str(first.root)
    cfg=json.loads(path.read_text()); cfg['root']=str(tmp_path/'second-root')
    second=tmp_path/'second-config.json'; second.write_text(json.dumps(cfg))
    with pytest.raises(ValueError,match='claimed'):
        cli.build_loop(second)
    assert not (tmp_path/'second-root'/'local-budget.sqlite').exists()
    assert not (tmp_path/'second-root'/'teacher-budget.sqlite').exists()
    cfg.pop('continuation_root'); cfg['root']=str(prior.root)
    old=tmp_path/'old-config.json'; old.write_text(json.dumps(cfg))
    with pytest.raises(ValueError,match='delegated'):
        cli.build_loop(old)


def test_cli_supplies_stable_disjoint_root_run_namespaces(tmp_path,monkeypatch):
    from scripts import kage_recover as cli
    path=config(tmp_path)
    monkeypatch.setattr(cli,'DockerSkillRunner',lambda **kw:object())
    received=[]
    original=cli.Promoter
    def capture(*args,**kwargs):
        received.append(kwargs.pop('run_namespace',None))
        return original(*args,**kwargs)
    monkeypatch.setattr(cli,'Promoter',capture)
    first=cli.build_loop(path); cli.build_loop(path)
    cfg=json.loads(path.read_text()); cfg['root']=str(tmp_path/'another-root')
    path.write_text(json.dumps(cfg)); another=cli.build_loop(path)
    assert received[0] and received[0]==received[1] and received[0]!=received[2]
    assert len(received[0])==12
    assert json.loads((first.root/'protocol.json').read_text())['run_namespace']==received[0]
    assert json.loads((another.root/'protocol.json').read_text())['run_namespace']==received[2]
