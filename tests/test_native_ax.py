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
    app = Element(AXWindows=[window, other], AXMenuBar=menu)
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
