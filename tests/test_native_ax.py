"""The fake driver exercises safety contracts without macOS dependencies."""
import asyncio
import copy
import json


def run(coro):
    return asyncio.run(coro)


class FakeDriver:
    def __init__(self):
        self.state = {'window_ref': 'w1', 'title': 'pilot.txt', 'targets': [
            {'target_ref': 'e1', 'role': 'AXTextArea', 'label': 'Text', 'value': 'old', 'operations': ['fill']}],
            'truncated': False}
        self.actions = []
        self.failure = None
    def windows(self, bundle_id):
        return [{'window_ref': 'w1', 'title': 'pilot.txt', 'bundle_id': bundle_id}]
    def snapshot(self, ref):
        if self.failure:
            raise self.failure
        if ref != 'w1':
            raise ValueError('unknown window')
        return copy.deepcopy(self.state)
    def act(self, ref, target, operation, value):
        self.actions.append((ref, target, operation, value))
        self.state['targets'][0]['value'] = value


def test_observed_fill_and_isolated_registry(tmp_path):
    from core.computer_use.native_ax import NativeAXAdapter
    from core.tool_registry import ToolRegistry
    from core.tool_executor import ToolExecutor
    async def scenario():
        driver = FakeDriver()
        adapter = NativeAXAdapter(driver, tmp_path/'trace.jsonl')
        registry = ToolRegistry(); adapter.register_tools(registry)
        executor = ToolExecutor(registry, str(tmp_path))
        observed = await executor.execute('native_observe', {'window_ref': 'w1'})
        obs = json.loads(observed.result)['observation']
        result = await executor.execute('native_act', {'observation_id': obs['observation_id'],
            'operation': 'fill', 'target_ref': 'e1', 'value': 'new'})
        payload = json.loads(result.result)
        assert result.success and payload['action_applied'] is True
        assert payload['observation']['targets'][0]['value'] == 'new'
        assert payload['observation']['source'] == 'ax'
        assert payload['observation']['ocr_fallback']['available'] is False
        assert len(driver.actions) == 1
    run(scenario())


def test_changes_and_cross_surface_refs_reject_without_mutation():
    from core.computer_use.native_ax import NativeAXAdapter
    async def scenario():
        driver = FakeDriver(); adapter = NativeAXAdapter(driver)
        obs = (await adapter.observe('w1'))['observation']
        driver.state['targets'][0]['target_ref'] = 'replacement'
        result = await adapter.act(obs['observation_id'], 'fill', 'e1', 'unsafe')
        assert result['error'] == 'StaleObservation' and result['action_applied'] is False
        assert result['observation']['targets'][0]['target_ref'] == 'replacement'
        other = NativeAXAdapter(FakeDriver())
        result = await other.act(result['observation']['observation_id'], 'fill', 'replacement', 'unsafe')
        assert result['error'] == 'StaleObservation' and not driver.actions
    run(scenario())


def test_permission_and_unsupported_are_explicit_and_preserved(tmp_path):
    from core.computer_use.native_ax import NativeAXAdapter, AXPermissionError
    from core.tool_executor import render_history_line
    async def scenario():
        driver = FakeDriver(); adapter = NativeAXAdapter(driver)
        obs = (await adapter.observe('w1'))['observation']
        bad = await adapter.act(obs['observation_id'], 'press', 'e1')
        assert bad['error'] == 'UnsupportedAction' and bad['action_applied'] is False
        driver.failure = AXPermissionError('Accessibility denied')
        bad = await adapter.act(bad['observation']['observation_id'], 'fill', 'e1', 'unsafe')
        assert bad['error'] == 'AXPermissionDenied' and bad['action_applied'] is False
        line = render_history_line('native_act', False, json.dumps(bad), outcome='rejected')
        assert 'action_applied' in line and 'AXPermissionDenied' in line
    run(scenario())


def test_driver_failure_after_write_keeps_applied_state():
    from core.computer_use.native_ax import NativeAXAdapter
    class Failing(FakeDriver):
        def act(self, *args):
            super().act(*args)
            self.failure = RuntimeError('read failed')
    async def scenario():
        driver = Failing(); adapter = NativeAXAdapter(driver)
        obs = (await adapter.observe('w1'))['observation']
        result = await adapter.act(obs['observation_id'], 'fill', 'e1', 'new')
        assert result['error'] == 'AXDriverError' and result['action_applied'] is True
        assert driver.state['targets'][0]['value'] == 'new'
    run(scenario())


def test_native_driver_does_not_read_unsupported_optional_attribute():
    from core.computer_use.native_ax import MacOSAXDriver
    class API:
        def AXUIElementSetMessagingTimeout(self, element, timeout): return 0
        def AXUIElementCopyAttributeNames(self, element, out): return 0, ['AXRole']
        def AXUIElementCopyAttributeValue(self, *args):
            raise AssertionError('unsupported attribute queried')
    driver = MacOSAXDriver()
    driver._load = lambda: (API(), None, None)
    assert driver._get(object(), 'AXDescription', '') == ''


def test_permission_at_dispatch_is_known_not_applied():
    from core.computer_use.native_ax import NativeAXAdapter, AXPermissionError
    class Denied(FakeDriver):
        def act(self, *args): raise AXPermissionError('permission revoked before dispatch')
    async def scenario():
        adapter = NativeAXAdapter(Denied())
        obs = (await adapter.observe('w1'))['observation']
        result = await adapter.act(obs['observation_id'], 'fill', 'e1', 'new')
        assert result['error'] == 'AXPermissionDenied' and result['action_applied'] is False
    run(scenario())


def test_unknown_driver_dispatch_failure_is_uncertain():
    from core.computer_use.native_ax import NativeAXAdapter
    class Broken(FakeDriver):
        def act(self, *args): raise RuntimeError('transport failed during dispatch')
    async def scenario():
        adapter = NativeAXAdapter(Broken())
        obs = (await adapter.observe('w1'))['observation']
        result = await adapter.act(obs['observation_id'], 'fill', 'e1', 'new')
        assert result['error'] == 'AXDriverError' and result['action_applied'] is None
    run(scenario())


def test_successful_close_is_observed_as_closed_not_driver_failure():
    from core.computer_use.native_ax import NativeAXAdapter, AXWindowClosedError
    class Closing(FakeDriver):
        def __init__(self):
            super().__init__(); self.state['targets'][0]['operations'] = ['press']
        def act(self, *args): self.failure = AXWindowClosedError('window closed')
    async def scenario():
        adapter = NativeAXAdapter(Closing())
        obs = (await adapter.observe('w1'))['observation']
        result = await adapter.act(obs['observation_id'], 'press', 'e1')
        assert result['success'] and result['action_applied'] is True
        assert result['observation']['window_closed'] is True
        stale = await adapter.act(obs['observation_id'], 'press', 'e1')
        assert stale['error'] == 'StaleObservation' and stale['action_applied'] is False
    run(scenario())


def test_native_menu_never_dispatches_when_main_window_switches_during_final_snapshot():
    import pytest
    from core.computer_use.native_ax import MacOSAXDriver, AXStaleError
    class Element:
        def __init__(self, **attrs): self.attrs = attrs
    other = Element(AXRole='AXWindow')
    text = Element(AXRole='AXTextArea', AXValue='old', AXEnabled=True, AXChildren=[])
    save = Element(AXRole='AXMenuItem', AXTitle='Save', AXMenuItemCmdChar='S',
                   AXMenuItemCmdModifiers=0, AXEnabled=True, AXChildren=[])
    submenu = Element(AXChildren=[save])
    file_menu = Element(AXRole='AXMenuBarItem', AXTitle='File', AXEnabled=True, AXChildren=[submenu])
    menu = Element(AXChildren=[Element(), Element(), file_menu])
    window = Element(AXRole='AXWindow', AXTitle='pilot.txt', AXChildren=[text])
    app = Element(AXWindows=[window, other], AXMenuBar=menu, AXFrontmost=True)
    class API:
        kAXValueCGPointType, kAXValueCGSizeType = 1, 2
        def __init__(self): self.main = window; self.switch = False; self.presses = []
        def AXUIElementSetMessagingTimeout(self, element, seconds): return 0
        def AXUIElementCopyAttributeNames(self, element, out):
            return 0, list(element.attrs) + (['AXMainWindow'] if element is app else [])
        def AXUIElementCopyAttributeValue(self, element, name, out):
            if name == 'AXMainWindow': return 0, self.main
            if self.switch and element is text and name == 'AXRole':
                self.main = other; self.switch = False
            return 0, element.attrs[name]
        def AXUIElementCopyActionNames(self, element, out):
            return 0, ['AXPress'] if element in (save, file_menu) else []
        def AXUIElementIsAttributeSettable(self, element, attribute, out): return 0, True
        def AXUIElementPerformAction(self, element, action): self.presses.append(element); return 0
    class CF:
        @staticmethod
        def CFEqual(left, right): return left is right
    api = API(); driver = MacOSAXDriver()
    driver._load = lambda: (api, None, CF)
    driver._windows['w1'] = (1, 'com.example.fixture', app, window)
    snapshot = driver.snapshot('w1')
    ref = next(t['target_ref'] for t in snapshot['targets'] if t.get('command') == 'S')
    api.switch = True  # Final snapshot captures old main, then main changes during traversal.
    with pytest.raises(AXStaleError):
        driver.act('w1', ref, 'press', None)
    assert api.presses == []


def test_pilot_cleanup_requires_observed_window_disappearance():
    from scripts.experiments.native_ax_pilot import wait_window_disappeared
    class Windows:
        def __init__(self, present): self.present = present
        async def windows(self, bundle):
            return {'success': True, 'windows': [{'title': 'pilot.txt'}] if self.present else []}
    async def scenario():
        assert await wait_window_disappeared(Windows(True), 'pilot.txt', attempts=2, interval=0) is False
        assert await wait_window_disappeared(Windows(False), 'pilot.txt', attempts=2, interval=0) is True
    run(scenario())


def focus_driver(*, active=False, writable=True, activation_error=0, change_main=False, settle=True):
    from core.computer_use.native_ax import MacOSAXDriver
    class Element:
        def __init__(self, **attrs): self.attrs=attrs
    save=Element(AXRole='AXMenuItem',AXTitle='Save',AXMenuItemCmdChar='S',AXMenuItemCmdModifiers=0,AXEnabled=True)
    menuitem=Element(AXRole='AXMenuBarItem',AXTitle='File',AXEnabled=True,AXChildren=[Element(AXChildren=[save])])
    bar=Element(AXChildren=[Element(),Element(),menuitem])
    window=Element(AXRole='AXWindow',AXTitle='owned.txt',AXDocument='file:///owned.txt',AXChildren=[])
    other=Element(AXRole='AXWindow')
    app=Element(AXWindows=[window,other],AXMainWindow=window,AXFrontmost=active,AXMenuBar=bar)
    class API:
        kAXValueCGPointType,kAXValueCGSizeType=1,2
        def __init__(self):self.mutations=[]
        def AXUIElementSetMessagingTimeout(self,*args):return 0
        def AXUIElementCopyAttributeNames(self,e,out):return 0,list(e.attrs)
        def AXUIElementCopyAttributeValue(self,e,name,out):return 0,e.attrs[name]
        def AXUIElementCopyActionNames(self,e,out):return 0,['AXPress'] if e in (save,menuitem) else []
        def AXUIElementIsAttributeSettable(self,e,name,out):return 0,writable if e is app and name=='AXFrontmost' else False
        def AXUIElementSetAttributeValue(self,e,name,value):
            self.mutations.append((e,name,value))
            if activation_error:return activation_error
            if settle:e.attrs[name]=value
            if change_main:app.attrs['AXMainWindow']=other
            return 0
        def AXUIElementPerformAction(self,e,action):self.mutations.append((e,action));return 0
    class CF:
        @staticmethod
        def CFEqual(a,b):return a is b
    api=API();driver=MacOSAXDriver(timeout_seconds=.1);driver._load=lambda:(api,None,CF)
    driver._windows['owned']=(1,'com.example.fixture',app,window)
    return driver,api,app,window


def test_inactive_app_hides_menu_press_and_exposes_explicit_owned_activation():
    driver,api,app,window=focus_driver()
    obs=driver.snapshot('owned')
    assert obs['application_active'] is False
    assert obs['activation_supported'] is True
    assert not any(t['role']=='AXMenuBarItem' or t.get('command') for t in obs['targets'])
    target=next(t for t in obs['targets'] if t['role']=='AXWindow')
    assert target['operations']==['activate']
    driver.act('owned',target['target_ref'],'activate',None)
    assert api.mutations==[(app,'AXFrontmost',True)]
    assert driver.snapshot('owned')['application_active'] is True


def test_activation_rejects_changed_main_before_dispatch_and_after_dispatch():
    import pytest
    from core.computer_use.native_ax import AXStaleError
    driver,api,app,window=focus_driver(change_main=True)
    obs=driver.snapshot('owned');target=next(t for t in obs['targets'] if t['role']=='AXWindow')
    with pytest.raises(Exception,match='main'):
        driver.act('owned',target['target_ref'],'activate',None)
    assert len(api.mutations)==1
    assert not any(t.get('command') for t in driver.snapshot('owned')['targets'])


def test_unsupported_activation_is_read_only_and_has_no_menu_target():
    driver,api,app,window=focus_driver(writable=False)
    obs=driver.snapshot('owned')
    assert obs['activation_supported'] is False
    assert obs['targets']==[] and api.mutations==[]


def test_activation_timeout_preserves_known_applied_request_and_single_dispatch():
    from core.computer_use.native_ax import NativeAXAdapter
    async def scenario():
        driver,api,app,window=focus_driver(settle=False)
        adapter=NativeAXAdapter(driver)
        obs=(await adapter.observe('owned'))['observation']
        target=next(t for t in obs['targets'] if t['role']=='AXWindow')
        result=await adapter.act(obs['observation_id'],'activate',target['target_ref'])
        assert result['success'] is False and result['action_applied'] is True
        assert result['error']=='AXActivationUnverified'
        assert result['observation']['application_active'] is False
        assert len(api.mutations)==1
    run(scenario())


def test_activation_transport_error_preserves_unknown_and_never_retries():
    from core.computer_use.native_ax import NativeAXAdapter
    async def scenario():
        driver,api,app,window=focus_driver(activation_error=-25204)
        adapter=NativeAXAdapter(driver)
        obs=(await adapter.observe('owned'))['observation']
        targets=[t for t in obs['targets'] if t['role']=='AXWindow'];assert len(targets)==1
        result=await adapter.act(obs['observation_id'],'activate',targets[0]['target_ref'])
        assert result['success'] is False and result['action_applied'] is None
        assert len(api.mutations)==1
    run(scenario())


def test_menu_dispatch_rechecks_foreground_after_final_snapshot():
    import pytest
    from core.computer_use.native_ax import AXStaleError
    driver,api,app,window=focus_driver(active=True)
    obs=driver.snapshot('owned');target=next(t for t in obs['targets'] if t.get('command')=='S')
    original=driver.snapshot
    def switch(ref):
        result=original(ref)
        app.attrs['AXFrontmost']=False
        return result
    driver.snapshot=switch
    with pytest.raises(AXStaleError):driver.act('owned',target['target_ref'],'press',None)
    assert api.mutations==[]


def test_activation_counts_same_scoped_action_quota_and_traces_explicit_dispatch(tmp_path):
    from core.computer_use.native_ax import NativeAXAdapter
    from core.computer_use.native_model import ScopedNativeAdapter
    async def scenario():
        driver,api,app,window=focus_driver()
        driver.windows=lambda bundle:[{'window_ref':'owned','title':'owned.txt','document_url':'file:///owned.txt'}]
        adapter=NativeAXAdapter(driver,tmp_path/'trace.jsonl')
        scope=ScopedNativeAdapter(adapter,'com.example.fixture','owned.txt',document_path='/owned.txt',max_actions=1)
        obs=(await scope.initial())['observation'];target=next(t for t in obs['targets'] if t['role']=='AXWindow')
        result=await scope.act(obs['observation_id'],'activate',target['target_ref'])
        assert result['success'] and scope.actions==1
        menu=next(t for t in result['observation']['targets'] if t['role']=='AXMenuBarItem')
        refused=await scope.act(result['observation']['observation_id'],'press',menu['target_ref'])
        assert refused['error']=='ActionLimit' and len(api.mutations)==1
        entries=[json.loads(line) for line in (tmp_path/'trace.jsonl').read_text().splitlines()]
        assert [e['action']['operation'] for e in entries if e['phase']=='execute']==['activate']
    run(scenario())
