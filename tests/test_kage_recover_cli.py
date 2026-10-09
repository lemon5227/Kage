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
