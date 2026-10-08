import asyncio
import importlib
import pytest


def module():
    try:
        return importlib.import_module('scripts.experiments.native_inactive_acceptance')
    except ModuleNotFoundError:
        pytest.fail('controlled inactive acceptance CLI missing')


def harness(monkeypatch, cli, *, setup=True, helper_ready=True, before=None, after=None):
    calls=[]
    def obs(active):
        return {'success':True,'observation':{'observation_id':'o','window_ref':'w',
            'application_active':active,'activation_supported':True,
            'targets':[{'role':'AXWindow','target_ref':'window','operations':['activate']},
                       {'role':'AXTextArea','target_ref':'area'},
                       {'role':'AXMenuBarItem','target_ref':'menu'},
                       {'role':'AXMenuItem','target_ref':'save','command':'s'}]}}
    class Env:
        def __init__(self,*args):self.events=[]
        async def setup(self):return {'success':setup,'error':'SetupUnavailable'}
    class Adapter:
        attempts={'editor':0,'checker_cleanup':0}
    class Scope:
        actions=0;save_applied=False
        def __init__(self,*args,**kwargs):pass
        async def initial(self):return obs(False)
        async def act(self, oid, operation, target, value=None):
            calls.append(operation);self.actions+=1
            return obs(True) if operation=='activate' else {'success':False,'error':'StopAfterFill'}
    class Helper:
        pid=54321
        def __init__(self,*args):pass
        async def start(self):
            calls.append('helper_start');return {'success':helper_ready,'pid':self.pid}
        def close(self):calls.append('helper_close');return {'owned_pid':self.pid,'stopped':True}
    states=iter([before or {'success':True,'frontmost_pid':54321,'app_pid':100,'main_window_owned':True,'owned_window_ref':'owned'},
                 after or {'success':True,'frontmost_pid':100,'app_pid':100,'main_window_owned':True,'owned_window_ref':'owned'}])
    monkeypatch.setattr(cli,'NativeDocumentEnvironment',Env)
    monkeypatch.setattr(cli,'BoundedOwnedTraceAdapter',lambda *args:Adapter())
    monkeypatch.setattr(cli,'ScopedNativeAdapter',Scope)
    monkeypatch.setattr(cli,'OwnedForegroundHelper',Helper)
    monkeypatch.setattr(cli,'sample_state',lambda *args:next(states))
    return calls


@pytest.mark.parametrize('setup,ready',[(False,True),(True,False)])
def test_setup_or_helper_readiness_failure_prevents_any_native_write(tmp_path,monkeypatch,setup,ready):
    cli=module();calls=harness(monkeypatch,cli,setup=setup,helper_ready=ready)
    report=asyncio.run(cli.probe(tmp_path/'probe','main'))
    assert not any(c in calls for c in ['activate','fill','press'])
    assert report['completion']['status']=='unknown'
    assert calls[-1]=='helper_close'


@pytest.mark.parametrize('after',[
    {'success':True,'frontmost_pid':54321,'app_pid':100,'main_window_owned':True,'owned_window_ref':'owned'},
    {'success':True,'frontmost_pid':100,'app_pid':100,'main_window_owned':False,'owned_window_ref':'owned'},
    {'success':False},
])
def test_actual_activation_postcondition_blocks_fill_on_false_success(tmp_path,monkeypatch,after):
    cli=module();calls=harness(monkeypatch,cli,after=after)
    report=asyncio.run(cli.probe(tmp_path/'probe','main'))
    assert calls==['helper_start','activate','helper_close']
    assert report['activation_verified'] is False
    assert report['completion']['status']=='unknown'


def test_already_active_control_is_not_activation_success(tmp_path,monkeypatch):
    cli=module();calls=harness(monkeypatch,cli,before={
        'success':True,'frontmost_pid':100,'app_pid':100,'main_window_owned':True,'owned_window_ref':'owned'})
    report=asyncio.run(cli.probe(tmp_path/'probe','main'))
    assert calls==['helper_start','helper_close']
    assert report['activation_verified'] is False


def test_verified_activation_allows_one_fill_and_retains_original_failure(tmp_path,monkeypatch):
    cli=module();calls=harness(monkeypatch,cli)
    report=asyncio.run(cli.probe(tmp_path/'probe','main'))
    assert calls==['helper_start','activate','fill','helper_close']
    assert report['activation_verified'] is True
    assert next(s['result'] for s in report['stages'] if s['phase']=='fill')['error']=='StopAfterFill'
    assert report['completion']['status']=='unknown'


def test_helper_cleanup_terminates_only_owned_process(tmp_path):
    cli=module();helper=cli.OwnedForegroundHelper(tmp_path)
    assert helper.close()['owned_pid'] is None
    class Process:
        pid=123;stopped=False
        def poll(self):return 0 if self.stopped else None
        def terminate(self):self.stopped=True
        def wait(self,timeout):return 0
    process=Process();helper.process=process
    assert helper.close()=={'owned_pid':123,'stopped':True,'returncode':0}
    assert process.stopped


def test_fresh_output_runs_exactly_two_contexts_and_refuses_overwrite(tmp_path,monkeypatch):
    cli=module();contexts=[]
    monkeypatch.setattr(cli,'freeze',lambda output:None)
    async def probe(output,context):
        contexts.append(context)
        return {'completion':{'status':'unknown'},'activation_verified':False}
    monkeypatch.setattr(cli,'probe',probe)
    output=tmp_path/'out'
    asyncio.run(cli.run(output))
    assert contexts==['main','run_sync']
    with pytest.raises(ValueError,match='fresh'):
        asyncio.run(cli.run(output))
    assert contexts==['main','run_sync']


def test_changed_owned_window_after_activation_blocks_fill(tmp_path,monkeypatch):
    cli=module();calls=harness(monkeypatch,cli,after={
        'success':True,'frontmost_pid':100,'app_pid':100,
        'main_window_owned':True,'owned_window_ref':'different-window'})
    report=asyncio.run(cli.probe(tmp_path/'probe','main'))
    assert calls==['helper_start','activate','helper_close']
    assert report['activation_verified'] is False


def test_helper_exit_before_ready_preserves_exit_status_and_closes_log(tmp_path,monkeypatch):
    cli=module()
    class Exited:
        pid=123;returncode=7
        def poll(self):return 7
    monkeypatch.setattr(cli.subprocess,'Popen',lambda *args,**kwargs:Exited())
    helper=cli.OwnedForegroundHelper(tmp_path)
    assert asyncio.run(helper.start())=={'success':False,'pid':123,'returncode':7}
    assert helper.close()=={'owned_pid':123,'stopped':True,'returncode':7}
    assert helper.log.closed


def test_helper_waits_for_actual_foreground_without_relaunch(tmp_path,monkeypatch):
    cli=module();launches=[]
    class Running:
        pid=123
        def poll(self):return None
    def launch(*args,**kwargs):
        launches.append(args)
        (tmp_path/'helper-ready.json').write_text('{"pid":123,"window_created":true}')
        return Running()
    monkeypatch.setattr(cli.subprocess,'Popen',launch)
    states=iter([999,123])
    monkeypatch.setattr(cli,'helper_frontmost_pid',lambda:next(states),raising=False)
    helper=cli.OwnedForegroundHelper(tmp_path)
    result=asyncio.run(helper.start())
    assert result['success'] is True
    assert result['foreground_samples']==[999,123]
    assert len(launches)==1
    helper.log.close()


def test_fresh_frontmost_reader_uses_bounded_child_process(monkeypatch):
    cli = module()
    calls = []
    class Result:
        returncode = 0
        stdout = "4242\n"
        stderr = ""
    def run(*args, **kwargs):
        calls.append((args, kwargs))
        return Result()
    monkeypatch.setattr(cli.subprocess, 'run', run)
    assert cli.fresh_frontmost_pid(timeout_s=0.4) == 4242
    assert calls and calls[0][1]['timeout'] == 0.4
    assert calls[0][1]['check'] is False


def test_activation_state_reads_fresh_foreground_instead_of_cached_appkit(monkeypatch):
    cli = module()
    monkeypatch.setattr(cli, 'passive_sample', lambda *args: {
        'success': True, 'app_pid': 100, 'main_window_owned': True,
        'owned_windows': [{'window_ref': 'same-owned-window'}],
    })
    class CachedWorkspace:
        def _load(self):
            raise AssertionError('cached AppKit frontmost reader must not be used')
    monkeypatch.setattr(cli, 'fresh_frontmost_pid', lambda **kwargs: 100)
    state = cli.sample_state(CachedWorkspace(), object())
    assert state['success'] is True
    assert state['frontmost_pid'] == 100
    assert state['owned_window_ref'] == 'same-owned-window'


def test_unavailable_fresh_foreground_cannot_be_successful_state(monkeypatch):
    cli = module()
    monkeypatch.setattr(cli, 'passive_sample', lambda *args: {
        'success': True, 'owned_windows': [{'window_ref': 'owned'}],
    })
    monkeypatch.setattr(cli, 'fresh_frontmost_pid', lambda **kwargs: None)
    state = cli.sample_state(object(), object())
    assert state['success'] is False
    assert state['error'] == 'FreshFrontmostUnavailable'


def test_unknown_completion_never_has_overall_acceptance(tmp_path,monkeypatch):
    cli=module();harness(monkeypatch,cli)
    report=asyncio.run(cli.probe(tmp_path/'probe','main'))
    assert report['acceptance_passed'] is False
    assert report['helper_cleanup']['stopped'] is True


def test_cleanup_failure_keeps_checker_passed_but_blocks_acceptance(tmp_path,monkeypatch):
    cli=module();harness(monkeypatch,cli)
    async def act(self,oid,operation,target,value=None):
        self.actions+=1
        if target=='save':self.save_applied=True
        return {'success':True,'observation':{'observation_id':'o','application_active':True,
            'targets':[{'role':'AXTextArea','target_ref':'area'},
                       {'role':'AXMenuBarItem','target_ref':'menu'},
                       {'role':'AXMenuItem','target_ref':'save','command':'s'}]}}
    monkeypatch.setattr(cli.ScopedNativeAdapter,'act',act)
    async def reread(self):return {'success':True}
    async def cleanup(self):raise RuntimeError('owned cleanup unavailable')
    monkeypatch.setattr(cli.NativeDocumentEnvironment,'reread',reread,raising=False)
    monkeypatch.setattr(cli.NativeDocumentEnvironment,'cleanup',cleanup,raising=False)
    async def completion(*args):return {'status':'passed','disk_matches':True,'reopened_ax_matches':True}
    monkeypatch.setattr(cli,'check_native_completion',completion)
    report=asyncio.run(cli.probe(tmp_path/'probe','main'))
    assert report['completion']['status']=='passed'
    assert report['acceptance_passed'] is False
