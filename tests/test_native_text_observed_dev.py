import asyncio
import json
import sys
import time

import pytest
from core.computer_use.native_ax import NativeAXAdapter
from core.computer_use.native_model import NativeDocumentEnvironment
from core.model_provider import ModelResponse
from scripts.experiments import native_text_observed_dev as dev


def test_protocol_is_fresh_and_fits_real_reservation():
    assert dev.TASK['document_name'] == 'kage-text-observed-dev4.txt'
    assert dev.TASK['expected'].count('\n') == 3
    assert json.loads(dev.TASK['instruction'].split('Exact JSON text:\n')[1]) == dev.TASK['expected']
    assert dev.PROTOCOL['max_requests'] == 8
    assert dev.budget_config().max_output_tokens_total >= dev.NativeChainProvider.RESERVATION_OUTPUT_CAP


def test_invalid_ready_never_dispatches(tmp_path):
    controller = dev.ObservationController(tmp_path)
    dev.atomic_json(tmp_path/'observer-ready.json', {'baseline': {'success':True,'owned_count':0,'original_present':False}})
    class Model:
        def generate(self, **kwargs): pytest.fail('invalid baseline dispatched')
    with pytest.raises(RuntimeError): dev.DispatchModel(Model(), controller).generate(messages=[])
    assert not (tmp_path/'observer-start.json').exists()


def test_real_short_process_handshake_and_owned_cleanup(tmp_path):
    child = dev.start_owned([sys.executable, '-c',
        "import json,pathlib,time; p=pathlib.Path(__import__('sys').argv[1]); "
        "(p/'observer-ready.json').write_text(json.dumps({'baseline':{'success':True,'owned_count':1,'original_present':True,'original_pid':1,'app_pid':1,'owned_url':'file:///owned'},'fresh':{'success':True,'owned_count':1,'app_pid':1,'owned_url':'file:///owned'}})); "
        "time.sleep(30)", str(tmp_path)], tmp_path/'stdout', tmp_path/'stderr')
    controller=dev.ObservationController(tmp_path); controller.child=child
    class Model:
        def generate(self, **kwargs): return ModelResponse(text='done')
    try:
        response=dev.DispatchModel(Model(),controller).generate(messages=[])
        assert response.text=='done'
        assert json.loads((tmp_path/'observer-start.json').read_text())['first_model_dispatch_monotonic'] > 0
        rows=[json.loads(line) for line in (tmp_path/'events.jsonl').read_text().splitlines()]
        assert [r['stage'] for r in rows]==['model_request','model_response']
    finally: controller.stop()
    assert child.poll() is not None
    assert (tmp_path/'observer-stop.json').exists()


def test_observer_keeps_unknown_and_stage_and_stop(tmp_path):
    dev.atomic_json(tmp_path/'stage.json',{'actor':'checker','stage':'close','monotonic':time.monotonic()})
    class Reader:
        original_pid=1; original_ref='retained'
        def sample(self): return {'success':True,'owned_count':1,'original_present':True,'original_pid':1,'app_pid':1,'owned_url':'file:///owned'}
    dev.atomic_json(tmp_path/'observer-start.json',{'first_model_dispatch_monotonic':time.monotonic()})
    count=[0]
    def fresh():
        count[0]+=1
        if count[0]==1:return {'success':True,'owned_count':1,'app_pid':1,'owned_url':'file:///owned'}
        dev.atomic_json(tmp_path/'observer-stop.json',{})
        return {'success':False,'error':'AXReadUnavailableError','original_present':None}
    report=dev.observe(tmp_path, Reader(), fresh, lambda seconds:None, interval=.01, maximum=2, duration=.1)
    rows=[json.loads(line) for line in (tmp_path/'timeline.jsonl').read_text().splitlines()]
    assert report['sample_count']==1
    assert rows[0]['actor']=='checker' and rows[0]['stage']=='close'
    assert rows[0]['fresh']['original_present'] is None


def test_checker_close_marker_precedes_actual_close(monkeypatch,tmp_path):
    controller=dev.ObservationController(tmp_path)
    environment=dev.ObservedEnvironment(tmp_path/'owned.txt',tmp_path,controller)
    async def close(self,actor):
        marker=json.loads((tmp_path/'stage.json').read_text())
        assert marker['actor']==actor and marker['stage']=='close'
        return {'success':True}
    monkeypatch.setattr(NativeDocumentEnvironment,'close',close)
    assert asyncio.run(environment.close('checker'))['success']
    assert environment.adapter.trace_path is None


def test_real_provider_chain_eight_calls_and_kernel_budget(tmp_path):
    from core.evolution.runner import EvolutionRunner
    from core.evolution.journal import Journal
    from core.evolution.budget import BudgetTracker
    from core.evolution.contracts import Candidate, RunSpec
    class Driver:
        def windows(self,bundle):return [{'window_ref':'owned','title':dev.TASK['document_name'],'document_url':self.document.as_uri(),'bundle_id':bundle}]
        def snapshot(self,ref):return {'window_ref':'owned','title':dev.TASK['document_name'],'document_url':self.document.as_uri(),'targets':[{'role':'AXTextArea','target_ref':'text','value':'initial','operations':['fill']}],'truncated':False}
    class Environment:
        def __init__(self,document,output):
            driver=Driver();driver.document=document;self.adapter=NativeAXAdapter(driver)
        async def setup(self):pass
        async def reread(self):return {'success':False}
    class Model:
        calls=0
        def generate(self,**kwargs):
            self.calls+=1
            return ModelResponse(text='', tool_calls=[{'name':'native_observe','arguments':{'window_ref':'owned'}}],usage={'input_tokens':1,'output_tokens':1})
    model=Model();provider=dev.make_provider(model,Environment)
    budget=BudgetTracker(dev.budget_config(),tmp_path/'budget.sqlite')
    runner=EvolutionRunner(Journal(tmp_path/'journal.sqlite'),budget,tmp_path/'workspaces',provider,step_isolation='inline')
    result=runner.run(Candidate('dev4',(),'workflow',str(tmp_path),'frozen'),dev.TASK,RunSpec('dev4','dev4',dev.TASK['task_id'],max_steps=1,timeout_s=480))
    assert model.calls==8 and provider.max_model_calls==8
    assert budget.total_api_calls==8
    assert json.loads((__import__('pathlib').Path(result.final_state_path)/'chain.json').read_text())['model_requests']==8


def test_fresh_missing_or_changed_scope_rejected_before_dispatch(tmp_path):
    baseline={'success':True,'owned_count':1,'app_pid':1,'original_present':True,'original_pid':1,'owned_url':'file:///owned'}
    assert not dev.valid_ready({'baseline':baseline})
    assert not dev.valid_ready({'baseline':baseline,'fresh':{**baseline,'owned_url':'file:///other'}})


def test_cleanup_error_keeps_partial_evidence(monkeypatch,tmp_path):
    controller=dev.ObservationController(tmp_path);controller.child=object()
    def fail(*args,**kwargs):raise PermissionError('private window title')
    monkeypatch.setattr(dev,'stop_owned',fail)
    controller.child=type('Child',(),{'poll':lambda self:0})()
    report=controller.stop()
    assert report['error']=='PermissionError' and 'private' not in json.dumps(report)
    assert json.loads((tmp_path/'observer-cleanup.json').read_text())==report


def test_actual_close_dispatch_and_result_are_marked(tmp_path):
    controller=dev.ObservationController(tmp_path);controller.event('checker','close')
    class Adapter:
        current={'targets':[{'target_ref':'close','command':'w'}]}
        async def act(self,*args):return {'success':True,'action_applied':True}
    result=asyncio.run(dev.ActionAdapter(Adapter(),controller).act('obs','press','close'))
    assert result['action_applied'] is True
    rows=[json.loads(line) for line in (tmp_path/'events.jsonl').read_text().splitlines()]
    assert [r['stage'] for r in rows]==['close','close_dispatch','close_result']
    assert rows[-1]['actor']=='checker' and rows[-1]['action_applied'] is True


def test_first_request_failure_remains_error_with_timestamp(tmp_path):
    c=dev.ObservationController(tmp_path);c.ready=True
    class FailedModel:
        def generate(self,**kwargs):raise RuntimeError('failed local request')
    with pytest.raises(RuntimeError):dev.DispatchModel(FailedModel(),c).generate(messages=[])
    rows=[json.loads(line) for line in (tmp_path/'events.jsonl').read_text().splitlines()]
    assert [r['stage'] for r in rows]==['model_request','model_error']
    assert c.calls==1


def test_setup_gate_failure_prevents_chain_entry(monkeypatch,tmp_path):
    controller=dev.ObservationController(tmp_path)
    env=dev.ObservedEnvironment(tmp_path/'owned.txt',tmp_path,controller)
    async def setup(self):return {'success':True}
    monkeypatch.setattr(NativeDocumentEnvironment,'setup',setup)
    monkeypatch.setattr(controller,'start',lambda document:None)
    def gate():raise RuntimeError('invalid baseline')
    monkeypatch.setattr(controller,'gate',gate)
    with pytest.raises(RuntimeError):asyncio.run(env.setup())


def test_baseline_pid_change_rejected():
    baseline={'success':True,'owned_count':1,'app_pid':1,'original_present':True,'original_pid':2,'owned_url':'file:///owned'}
    assert not dev.valid_ready({'baseline':baseline,'fresh':{**baseline,'original_pid':1}})


def test_dirty_sources_rejected_before_output(monkeypatch,tmp_path):
    monkeypatch.setattr(sys,'argv',['dev','--output',str(tmp_path/'attempt')])
    monkeypatch.setattr(dev.subprocess,'check_output',lambda *args,**kwargs:' M core/native.py')
    with pytest.raises(SystemExit):dev.main()
    assert not (tmp_path/'attempt').exists()


def test_existing_output_never_overwritten(monkeypatch,tmp_path):
    monkeypatch.setattr(sys,'argv',['dev','--output',str(tmp_path)])
    monkeypatch.setattr(dev.subprocess,'check_output',lambda *args,**kwargs:'')
    with pytest.raises(FileExistsError):dev.main()


def test_observer_disk_metrics_are_hash_only(tmp_path):
    document=tmp_path/'owned.txt';document.write_text('secret owned content')
    metrics=dev.disk_metrics(document)
    assert metrics['bytes']==20 and metrics['success'] is True
    assert set(metrics)=={'success','bytes','sha256'}
    assert 'secret' not in json.dumps(metrics)
    assert dev.disk_metrics(tmp_path/'missing')['success'] is False
