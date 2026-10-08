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
    observation={'observation_id':'current','targets':[
        {'role':'AXMenuBarItem','target_ref':'menu'},
        {'role':'AXMenuItem','target_ref':'close','command':'w'}]}
    class Adapter:
        async def act(self,*args):return {'success':True,'action_applied':True,'observation':observation}
        async def windows(self,*args):return {'success':True,'windows':[{'title':'owned.txt','document_url':other.as_uri()}]}
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
