import asyncio
import json
import pytest
from scripts.experiments import native_ax_pilot as pilot


@pytest.mark.parametrize('code',['AXPermissionDenied','NotAvailable'])
def test_close_completion_failure_retains_structured_blocked_report(tmp_path,monkeypatch,code):
    class Adapter:
        def __init__(self,**kwargs):self.closed=False;self.value='before semantic edit'
        async def windows(self,bundle):
            if self.closed:return {'success':False,'error':code,'message':'completion unavailable','action_applied':False}
            return {'success':True,'windows':[{'title':'kage-native-ax-case.txt','window_ref':'owned'}]}
        def observation(self):
            return {'observation_id':'fresh','targets':[
                {'target_ref':'text','role':'AXTextArea','value':self.value},
                {'target_ref':'menu','role':'AXMenuBarItem'},
                {'target_ref':'save','role':'AXMenuItem','command':'s'},
                {'target_ref':'close','role':'AXMenuItem','command':'w'}]}
        async def observe(self,ref):return {'success':True,'observation':self.observation()}
        async def act(self,obs,operation,target,value=None):
            if operation=='fill':self.value=value
            if target=='close':self.closed=True
            return {'success':True,'action_applied':True,'observation':self.observation()}
    monkeypatch.setattr(pilot,'NativeAXAdapter',Adapter)
    monkeypatch.setattr(pilot.subprocess,'run',lambda *args,**kwargs:None)
    async def no_wait(*args):pass
    monkeypatch.setattr(pilot.asyncio,'sleep',no_wait)
    report=asyncio.run(pilot.pilot(tmp_path/'case'))
    assert report['status']=='blocked'
    stage=next(s for s in report['stages'] if s['stage']=='close_completion_probe')
    assert stage['result']=={'success':False,'error':code,'message':'completion unavailable','action_applied':False}
    assert json.loads((tmp_path/'case'/'report.json').read_text())['stages']==report['stages']
