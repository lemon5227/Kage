import asyncio
import pytest
from core.computer_use import native_model as native
from core.computer_use.native_ax import NativeAXAdapter, MacOSAXDriver


def test_completion_refreshes_disk_after_reopen_finishes_pending_save(tmp_path):
    document=tmp_path/'owned.txt';document.write_text('before save completes')
    async def reopened():
        document.write_text('exact saved text\n')  # External app's delayed save.
        return {'success':True,'observation':{'targets':[{'role':'AXTextArea','value':'exact saved text\n'}]}}
    result=asyncio.run(native.check_native_completion(document,'exact saved text\n',reopened))
    assert result['status']=='passed' and result['disk_matches'] is True
    assert result['disk_matches_before_reopen'] is False


def test_read_timeout_is_typed_and_not_a_mutation_retry():
    class API:
        def AXUIElementSetMessagingTimeout(self,*args):return 0
        def AXUIElementCopyAttributeNames(self,*args):return 0,['AXWindows']
        def AXUIElementCopyAttributeValue(self,*args):return -25204,None
    driver=MacOSAXDriver();driver._load=lambda:(API(),None,None)
    driver.windows=lambda bundle:driver._get(object(),'AXWindows')
    result=asyncio.run(NativeAXAdapter(driver).windows('com.apple.TextEdit'))
    assert result['error']=='AXReadUnavailable' and result['action_applied'] is False


def test_destroyed_element_during_value_read_is_typed_stale():
    class API:
        def AXUIElementSetMessagingTimeout(self,*args):return 0
        def AXUIElementCopyAttributeNames(self,*args):return 0,['AXTitle']
        def AXUIElementCopyAttributeValue(self,*args):return -25202,None
    driver=MacOSAXDriver();driver._load=lambda:(API(),None,None)
    driver.windows=lambda bundle:driver._get(object(),'AXTitle')
    result=asyncio.run(NativeAXAdapter(driver).windows('com.apple.TextEdit'))
    assert result['error']=='StaleObservation' and result['action_applied'] is False


def test_close_rechecks_fresh_windows_after_destroyed_element_without_redispatch(tmp_path):
    observation={'observation_id':'current','window_ref':'owned','targets':[
        {'role':'AXMenuBarItem','target_ref':'menu'},
        {'role':'AXMenuItem','target_ref':'close','command':'w'}]}
    class Adapter:
        reads=0;actions=[]
        async def act(self,oid,operation,target,value=None):
            self.actions.append(target)
            return {'success':True,'action_applied':True,'observation':observation}
        async def windows(self,*args):
            self.reads+=1
            if self.reads==1:return {'success':False,'error':'StaleObservation','action_applied':False}
            return {'success':True,'windows':[]}
    env=native.NativeDocumentEnvironment(tmp_path/'owned.txt',tmp_path);env.adapter=Adapter()
    async def observe(actor):return {'success':True,'observation':observation}
    env.observe=observe
    assert asyncio.run(env.close('checker'))=={'success':True,'window_disappeared':True}
    assert env.adapter.actions==['menu','close'] and env.adapter.reads==2
    assert env.events[-2]['result']['error']=='StaleObservation'


def test_close_cannot_claim_disappearance_when_all_fresh_reads_are_stale(tmp_path,monkeypatch):
    observation={'observation_id':'current','window_ref':'owned','targets':[
        {'role':'AXMenuBarItem','target_ref':'menu'},
        {'role':'AXMenuItem','target_ref':'close','command':'w'}]}
    class Adapter:
        reads=0;actions=0
        async def act(self,*args):
            self.actions+=1
            return {'success':True,'action_applied':True,'observation':observation}
        async def windows(self,*args):
            self.reads+=1
            return {'success':False,'error':'StaleObservation','action_applied':False}
    env=native.NativeDocumentEnvironment(tmp_path/'owned.txt',tmp_path);env.adapter=Adapter()
    async def observe(actor):return {'success':True,'observation':observation}
    async def no_delay(*args):pass
    env.observe=observe
    monkeypatch.setattr(asyncio,'sleep',no_delay)
    with pytest.raises(RuntimeError,match='remained'):
        asyncio.run(env.close('checker'))
    assert env.adapter.actions==2 and env.adapter.reads==30


def test_checker_observation_waits_only_for_retryable_read_state(tmp_path,monkeypatch):
    responses=[{'success':False,'error':'AXReadUnavailable','action_applied':False},
               {'success':True,'observation':{'window_ref':'owned','targets':[]}}]
    class Scope:
        def __init__(self,*args,**kwargs):pass
        async def initial(self):return responses.pop(0)
    monkeypatch.setattr(native,'ScopedNativeAdapter',Scope)
    env=native.NativeDocumentEnvironment(tmp_path/'owned.txt',tmp_path)
    result=asyncio.run(env.observe('checker'))
    assert result['success'] is True
    assert [e['result']['success'] for e in env.events]==[False,True]


def test_close_waits_for_exact_document_url_not_same_basename(tmp_path):
    document=tmp_path/'owned.txt';other=tmp_path/'other'/'owned.txt'
    observation={'observation_id':'current','window_ref':'owned','targets':[
        {'role':'AXMenuBarItem','target_ref':'menu'},
        {'role':'AXMenuItem','target_ref':'close','command':'w'}]}
    class Adapter:
        async def act(self,*args):return {'success':True,'action_applied':True,'observation':observation}
        async def windows(self,*args):return {'success':True,'windows':[{'window_ref':'other','title':'owned.txt','document_url':other.as_uri()}]}
    env=native.NativeDocumentEnvironment(document,tmp_path);env.adapter=Adapter()
    async def observe(actor):return {'success':True,'observation':observation}
    env.observe=observe
    result=asyncio.run(env.close('checker'))
    assert result=={'success':True,'window_disappeared':True}


def test_post_save_observation_settles_without_redispatching_save(tmp_path):
    from core.computer_use.native_ax import AXReadUnavailableError
    class Driver:
        applied=0;pending_reads=0
        def windows(self,bundle):return [{'window_ref':'owned','title':'owned.txt','document_url':(tmp_path/'owned.txt').as_uri()}]
        def snapshot(self,ref):
            if self.pending_reads:
                self.pending_reads-=1
                raise AXReadUnavailableError('menu teardown temporarily unavailable')
            return {'window_ref':'owned','title':'owned.txt','document_url':(tmp_path/'owned.txt').as_uri(),
                    'targets':[{'target_ref':'save','role':'AXMenuItem','command':'s','operations':['press']}]}
        def act(self,*args):self.applied+=1;self.pending_reads=2
    driver=Driver();scope=native.ScopedNativeAdapter(NativeAXAdapter(driver),'com.apple.TextEdit','owned.txt',document_path=tmp_path/'owned.txt')
    async def scenario():
        observed=(await scope.initial())['observation']
        result=await scope.act(observed['observation_id'],'press','save')
        assert result['success'] is True and result['action_applied'] is True
        assert scope.save_applied is True and scope.actions==1
    asyncio.run(scenario())
    assert driver.applied==1


def test_missing_document_url_does_not_prove_original_window_disappeared(tmp_path):
    observation={'observation_id':'current','window_ref':'owned','targets':[
        {'role':'AXMenuBarItem','target_ref':'menu'},
        {'role':'AXMenuItem','target_ref':'close','command':'w'}]}
    class Adapter:
        reads=0
        async def act(self,*args):return {'success':True,'action_applied':True,'observation':observation}
        async def windows(self,*args):
            self.reads+=1
            if self.reads==1:return {'success':True,'windows':[{'window_ref':'owned','title':'changed','document_url':''}]}
            return {'success':False,'error':'AXPermissionDenied'}
    env=native.NativeDocumentEnvironment(tmp_path/'owned.txt',tmp_path);env.adapter=Adapter()
    async def observe(actor):return {'success':True,'observation':observation}
    env.observe=observe
    with pytest.raises(RuntimeError,match='AXPermissionDenied'):
        asyncio.run(env.close('checker'))


def test_exhausted_post_action_read_wait_keeps_three_reads_and_invalidates_refs():
    from core.computer_use.native_ax import AXReadUnavailableError
    class Driver:
        applied=0;reads=0
        def snapshot(self,ref):
            if self.applied:
                self.reads+=1
                raise AXReadUnavailableError('still transitioning')
            return {'window_ref':'owned','targets':[{'target_ref':'save','operations':['press']}]}
        def act(self,*args):self.applied+=1
    driver=Driver();adapter=NativeAXAdapter(driver)
    async def scenario():
        obs=(await adapter.observe('owned'))['observation']
        result=await adapter.act(obs['observation_id'],'press','save')
        assert result['success'] is False and result['action_applied'] is True
        assert driver.reads==3 and driver.applied==1
        assert adapter.current is None
    asyncio.run(scenario())
