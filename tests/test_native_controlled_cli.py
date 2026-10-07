import json

def test_frozen_protocol_two_distinct_tasks_and_no_cloud():
    from scripts.experiments.native_model_pilot import TASKS,PROTOCOL,local_broker
    assert len(TASKS)==2 and len({t['document_name'] for t in TASKS})==2
    assert PROTOCOL=={'version':'native-controlled-v1','attempts_per_task':1,'max_loop_steps':8,'max_requests_per_task':10,'max_actions_per_task':16,'timeout_s_per_task':480,'max_requests_total':20,'cloud_calls':0,'temperature':0}
    for task in TASKS:
        assert task['expected'] != task['initial_files'][task['document_name']]
    broker=local_broker(18082)
    assert broker.profile('background').mode=='local'
    assert broker.background_provider.base_url=='http://127.0.0.1:18082/v1'

def test_freeze_contains_source_prompt_protocol_and_runtime_provenance(tmp_path):
    from scripts.experiments.native_model_pilot import freeze_manifest
    from core.computer_use.native_model import NATIVE_SOUL
    manifest=freeze_manifest(tmp_path,{'model_sha256':'abc','server_version':'verified','server_argv':['llama-server']})
    saved=json.loads((tmp_path/'freeze.json').read_text())
    assert manifest==saved
    assert saved['prompt']==NATIVE_SOUL and saved['source_hashes']['core/computer_use/native_model.py']
    assert saved['runtime']['server_version']=='verified' and saved['git_revision']


def test_version_probe_timeout_retains_status_and_log_build_info(tmp_path,monkeypatch):
    import subprocess
    from scripts.experiments import native_model_pilot as pilot
    (tmp_path/'server.log').write_text('build: 9999 (abc123) with Apple clang\nserver listening\n')
    def timeout(*args,**kwargs):
        assert kwargs['timeout']==3
        raise subprocess.TimeoutExpired(args[0],3,output=b'partial version')
    monkeypatch.setattr(pilot.subprocess,'run',timeout)
    result=pilot.server_version(tmp_path)
    assert result['status']=='timeout'
    assert result['output']=='partial version'
    assert result['log_build_info']==['build: 9999 (abc123) with Apple clang']


def test_version_probe_preserves_nonzero_exit_status(tmp_path,monkeypatch):
    import subprocess
    from scripts.experiments import native_model_pilot as pilot
    monkeypatch.setattr(pilot.subprocess,'run',lambda *args,**kwargs:subprocess.CompletedProcess(args[0],7,'unsupported flag'))
    result=pilot.server_version(tmp_path)
    assert result=={'status':'exited','returncode':7,'output':'unsupported flag','log_build_info':[]}


def test_service_cleanup_stops_only_owned_process(tmp_path):
    from scripts.experiments.native_model_pilot import LocalService
    service=LocalService(18082,tmp_path)
    service.__exit__()
    assert json.loads((tmp_path/'service-cleanup.json').read_text())=={'owned_service':False,'owned_service_stopped':False}
    class Owned:
        stopped=False
        def poll(self):return 0 if self.stopped else None
        def terminate(self):self.stopped=True
        def wait(self,timeout):return 0
    owned=Owned();service.process=owned
    service.__exit__()
    assert owned.stopped
    assert json.loads((tmp_path/'service-cleanup.json').read_text())=={'owned_service':True,'owned_service_stopped':True}
