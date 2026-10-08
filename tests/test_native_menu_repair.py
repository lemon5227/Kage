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
    assert repair.PROTOCOL['max_actions_per_context']==4 and repair.PROTOCOL['model_requests']==0
    import pytest
    with pytest.raises(ValueError,match='fresh'):asyncio.run(repair.run(out))
    assert contexts==['main','run_sync']


def test_unsupported_activation_preserves_evidence_without_edit(tmp_path,monkeypatch):
    class Environment:
        def __init__(self,*args):self.adapter=None
        async def setup(self):return {'success':True}
    class Scope:
        actions=0;save_applied=False
        def __init__(self,*args,**kwargs):pass
        async def initial(self):return {'success':True,'observation':{'application_active':False,'activation_supported':False}}
        async def act(self,*args):raise AssertionError('unsupported activation must not edit')
    monkeypatch.setattr(repair,'NativeDocumentEnvironment',Environment)
    monkeypatch.setattr(repair,'OwnedTraceAdapter',lambda *args:None)
    monkeypatch.setattr(repair,'ScopedNativeAdapter',Scope)
    report=asyncio.run(repair.probe(tmp_path/'probe','main'))
    assert report['completion']['status']=='unknown' and report['actions']==0
    assert report['disk']['expected_matches'] is False
    saved=json.loads((tmp_path/'probe'/'report.json').read_text())
    assert 'unsupported' in saved['completion']['error']
    assert [s['phase'] for s in saved['stages']]==['setup','initial','failure','preserve']
