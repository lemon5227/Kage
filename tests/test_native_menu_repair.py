import asyncio
import json
from scripts.experiments import native_menu_repair as repair


def test_fresh_output_and_fixed_no_model_protocol(tmp_path,monkeypatch):
    monkeypatch.setattr(repair,'freeze',lambda output:None)
    contexts=[]
    async def probe(output,context):contexts.append(context);return {'completion':{'status':'unknown'}}
    monkeypatch.setattr(repair,'probe',probe)
    out=tmp_path/'result';asyncio.run(repair.run(out))
    assert contexts==['main','run_sync']
    import pytest
    with pytest.raises(ValueError,match='fresh'):asyncio.run(repair.run(out))
    assert contexts==['main','run_sync']


def test_unsupported_activation_preserves_evidence_without_edit(tmp_path,monkeypatch):
    class Environment:
        def __init__(self,*args):self.adapter=None;self.events=[]
        async def setup(self):return {'success':True}
    class Scope:
        actions=0;save_applied=False
        def __init__(self,*args,**kwargs):pass
        async def initial(self):return {'success':True,'observation':{'application_active':False,'activation_supported':False}}
        async def act(self,*args):raise AssertionError('unsupported activation must not edit')
    monkeypatch.setattr(repair,'NativeDocumentEnvironment',Environment)
    class NoActionAdapter:
        attempts={'editor':0,'checker_cleanup':0}
    monkeypatch.setattr(repair,'BoundedOwnedTraceAdapter',lambda *args:NoActionAdapter())
    monkeypatch.setattr(repair,'ScopedNativeAdapter',Scope)
    report=asyncio.run(repair.probe(tmp_path/'probe','main'))
    assert report['completion']['status']=='unknown' and report['actions']==0
    assert report['disk']['expected_matches'] is False
    saved=json.loads((tmp_path/'probe'/'report.json').read_text())
    assert 'unsupported' in saved['completion']['error']
    assert [s['phase'] for s in saved['stages']]==['setup','initial','failure','preserve']


def test_native_attempt_caps_apply_before_editor_and_checker_dispatch(tmp_path, monkeypatch):
    dispatched=[]
    async def fake_act(self,*args,**kwargs):
        dispatched.append(args)
        return {'success':True,'action_applied':True}
    monkeypatch.setattr(repair.OwnedTraceAdapter,'act',fake_act)
    adapter=repair.BoundedOwnedTraceAdapter(tmp_path/'own.txt',tmp_path/'trace.jsonl')
    async def scenario():
        for _ in range(4):
            assert (await adapter.act('observation','press','target'))['success']
        denied=await adapter.act('observation','press','target')
        assert denied['error']=='ActionLimit' and denied['action_applied'] is False
        adapter.actor='checker'
        for _ in range(2):assert (await adapter.act('observation','press','target'))['success']
        adapter.actor='cleanup'
        for _ in range(2):assert (await adapter.act('observation','press','target'))['success']
        denied=await adapter.act('observation','press','target')
        assert denied['error']=='ActionLimit' and denied['action_applied'] is False
    asyncio.run(scenario())
    assert len(dispatched)==8
    assert adapter.attempts=={'editor':4,'checker_cleanup':4}
