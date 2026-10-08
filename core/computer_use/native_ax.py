"""Bounded, window-scoped macOS Accessibility tools (no global keyboard input)."""
import asyncio
import json
import hashlib
import sys
import time
import uuid
from pathlib import Path

from core.computer_use.browser import revision
from core.tool_registry import ToolDefinition


class AXPermissionError(RuntimeError):
    pass


class AXUnavailableError(RuntimeError):
    pass


class AXReadUnavailableError(RuntimeError):
    """A pure AX read could not complete during a UI transition."""


class AXStaleError(RuntimeError):
    pass


class AXInvalidElementError(AXStaleError):
    pass


class AXWindowClosedError(AXStaleError):
    pass


class AXActivationUnverified(RuntimeError):
    """The activation write succeeded, but its scoped postcondition did not."""


class MacOSAXDriver:
    """Lazy optional PyObjC bridge. Handles never leave this driver.

    Each AX request has a messaging timeout; traversal has node/depth/time caps.
    Window and element identities use CFEqual, not titles or positional paths.
    """
    def __init__(self, max_nodes=400, max_depth=12, timeout_seconds=5):
        if not 1 <= max_nodes <= 1000 or not 1 <= max_depth <= 20 or not 0 < timeout_seconds <= 10:
            raise ValueError('invalid AX bounds')
        self.max_nodes, self.max_depth, self.timeout_seconds = max_nodes, max_depth, timeout_seconds
        self._identities = []
        self._windows = {}
        self._targets = {}
        self._menu_targets = {}
        self._api = None
        self._snapshots = {}
        self._deadline = None

    def _load(self):
        if sys.platform != 'darwin':
            raise AXUnavailableError('native AX requires macOS')
        if self._api is None:
            try:
                import ApplicationServices as ax
                import AppKit
                import CoreFoundation
            except ImportError as exc:
                raise AXUnavailableError('install pyobjc-framework-ApplicationServices and Cocoa') from exc
            self._api = ax, AppKit, CoreFoundation
        if not self._api[0].AXIsProcessTrusted():
            raise AXPermissionError('Accessibility permission is unavailable for this process')
        return self._api

    def _id(self, element, prefix):
        cf = self._load()[2]
        for known, ref in self._identities:
            if cf.CFEqual(known, element):
                return ref
        if len(self._identities) >= 4096:
            raise AXStaleError('AX identity budget exhausted; create a new driver and reobserve')
        ref = prefix + uuid.uuid4().hex
        self._identities.append((element, ref))
        return ref

    def _get(self, element, name, default=None):
        ax = self._load()[0]
        if self._deadline is not None and time.monotonic() >= self._deadline:
            raise RuntimeError('AX operation exceeded its bounded deadline')
        error = ax.AXUIElementSetMessagingTimeout(element, 0.2)
        if error:
            raise RuntimeError(f'AX messaging timeout setup failed: {error}')
        error, names = ax.AXUIElementCopyAttributeNames(element, None)
        if error == -25202:
            raise AXInvalidElementError('AX element was destroyed')
        if error == -25204:
            raise AXReadUnavailableError('AX attribute discovery temporarily unavailable: -25204')
        if error:
            raise RuntimeError(f'AX attribute discovery failed: {error}')
        if name not in names:
            return default
        error, value = ax.AXUIElementCopyAttributeValue(element, name, None)
        if error == -25202:
            raise AXInvalidElementError(f'AX element was destroyed during {name} read')
        if error in (-25205, -25212) or (error == -25200 and name == 'AXDescription'):
            # TextEdit advertises AXDescription on some menu nodes but returns
            # AXErrorFailure. It is an optional label; state attributes still fail.
            return default
        if error == -25204:
            raise AXReadUnavailableError(f'AX attribute {name} temporarily unavailable: -25204')
        if error:
            raise RuntimeError(f'AX attribute {name} failed: {error}')
        return value

    def windows(self, bundle_id):
        if not isinstance(bundle_id, str) or not bundle_id:
            raise ValueError('bundle_id must be nonempty')
        self._deadline = time.monotonic() + self.timeout_seconds
        ax, appkit, _ = self._load()
        apps = appkit.NSRunningApplication.runningApplicationsWithBundleIdentifier_(bundle_id)
        if len(apps) != 1:
            raise ValueError('expected exactly one running application for bundle_id')
        pid = int(apps[0].processIdentifier())
        app = ax.AXUIElementCreateApplication(pid)
        windows = self._get(app, 'AXWindows', [])
        if len(windows) > 40:
            raise RuntimeError('application window count exceeds bound')
        result = []
        selected = {}
        for window in windows:
            ref = self._id(window, 'w')
            selected[ref] = (pid, bundle_id, app, window)
            result.append({'window_ref': ref, 'title': str(self._get(window, 'AXTitle', '')),
                           'bundle_id': bundle_id, 'pid': pid,
                           'document_url': str(self._get(window, 'AXDocument', ''))})
        # A new identification deliberately invalidates previously selected app scope.
        self._windows = selected
        self._targets = {}
        return result

    def snapshot(self, window_ref):
        try:
            return self._snapshot(window_ref)
        except AXInvalidElementError:
            if window_ref in self._windows:
                _, _, app, window = self._windows[window_ref]
                windows = self._get(app, 'AXWindows', [])
                cf = self._load()[2]
                if not any(cf.CFEqual(window, candidate) for candidate in windows):
                    raise AXWindowClosedError('observed window closed during observation') from None
            raise

    def _snapshot(self, window_ref):
        self._deadline = time.monotonic() + self.timeout_seconds
        ax, _, cf = self._load()
        if window_ref not in self._windows:
            raise AXStaleError('window_ref is outside identified application scope')
        pid, bundle, app, window = self._windows[window_ref]
        current = self._get(app, 'AXWindows', [])
        if not any(cf.CFEqual(window, candidate) for candidate in current):
            raise AXWindowClosedError('observed window is no longer present')
        deadline = time.monotonic() + self.timeout_seconds
        roots = [(window, 0)]
        menu_elements = []
        # Menus are application-scoped; only expose them when this window is main.
        main = self._get(app, 'AXMainWindow')
        active = self._get(app, 'AXFrontmost')
        error, writable = ax.AXUIElementIsAttributeSettable(app, 'AXFrontmost', None) if active is not None else (0, False)
        activation_supported = error == 0 and bool(writable)
        activation_support_error = int(error)
        if active is True and main is not None and cf.CFEqual(main, window):
            menu = self._get(app, 'AXMenuBar')
            if menu is not None:
                # Only document Save/Close commands are exposed from menus.
                # Do not observe Apple/system, recent-file or other-window menus.
                for bar_item in list(self._get(menu, 'AXChildren', []))[2:12]:
                    for submenu in list(self._get(bar_item, 'AXChildren', []))[:1]:
                        for item in list(self._get(submenu, 'AXChildren', []))[:100]:
                            command = self._get(item, 'AXMenuItemCmdChar', '')
                            modifiers = self._get(item, 'AXMenuItemCmdModifiers', 0)
                            if str(command).lower() in ('s', 'w') and int(modifiers or 0) == 0:
                                if not any(self._load()[2].CFEqual(bar_item, root[0]) for root in roots):
                                    roots.append((bar_item, self.max_depth))
                                    menu_elements.append(bar_item)
                                roots.append((item, self.max_depth))
                                menu_elements.append(item)
        queue, seen, targets, handles = roots, [], [], {}
        truncated = False
        while queue:
            if len(seen) >= self.max_nodes or time.monotonic() >= deadline:
                truncated = True
                break
            element, depth = queue.pop(0)
            if any(cf.CFEqual(element, item) for item in seen):
                continue
            seen.append(element)
            role = str(self._get(element, 'AXRole', ''))
            label = str(self._get(element, 'AXTitle', '') or self._get(element, 'AXDescription', ''))
            enabled = bool(self._get(element, 'AXEnabled', True))
            error, names = ax.AXUIElementCopyActionNames(element, None)
            if error not in (0, -25205):
                raise RuntimeError(f'AX action discovery failed: {error}')
            operations = ['press'] if enabled and 'AXPress' in (names or []) else []
            if role == 'AXWindow' and cf.CFEqual(element, window) and active is False and activation_supported and main is not None and cf.CFEqual(main, window):
                operations.append('activate')
            if enabled and role in {'AXTextArea', 'AXTextField'}:
                error, writable = ax.AXUIElementIsAttributeSettable(element, 'AXValue', None)
                if error:
                    raise RuntimeError(f'AX writable discovery failed: {error}')
                if writable:
                    operations.append('fill')
            if operations:
                ref = self._id(element, 'e')
                value = self._get(element, 'AXValue', '') if role in {'AXTextArea', 'AXTextField'} else ''
                position, size = self._get(element, 'AXPosition'), self._get(element, 'AXSize')
                bounds = []
                for geometry, kind in [(position, ax.kAXValueCGPointType), (size, ax.kAXValueCGSizeType)]:
                    if geometry is not None:
                        ok, decoded = ax.AXValueGetValue(geometry, kind, None)
                        if not ok:
                            raise RuntimeError('AX geometry decoding failed')
                        bounds.extend(float(v) for v in decoded)
                targets.append({'target_ref': ref, 'role': role, 'label': label[:200],
                                'value': str(value)[:10000], 'value_digest': hashlib.sha256(str(value).encode()).hexdigest(),
                                'bounds': bounds, 'operations': operations,
                                'command': self._get(element, 'AXMenuItemCmdChar', '') if role == 'AXMenuItem' else ''})
                handles[ref] = element
            children = [] if role in {'AXMenuItem', 'AXMenuBarItem'} else list(self._get(element, 'AXChildren', []) or [])
            close = self._get(element, 'AXCloseButton') if role == 'AXWindow' else None
            if close is not None:
                children.append(close)
            if children and depth >= self.max_depth:
                truncated = True
            elif children:
                queue.extend((child, depth + 1) for child in children[:self.max_nodes])
                if len(children) > self.max_nodes:
                    truncated = True
        self._targets[window_ref] = handles
        self._menu_targets[window_ref] = {ref for ref, handle in handles.items()
            if any(cf.CFEqual(handle, menu_element) for menu_element in menu_elements)}
        snapshot = {'window_ref': window_ref, 'pid': pid, 'bundle_id': bundle,
                'title': str(self._get(window, 'AXTitle', '')),
                'document_url': str(self._get(window, 'AXDocument', '')), 'targets': targets,
                'main_window': main is not None and bool(cf.CFEqual(main, window)),
                'application_active': bool(active) if active is not None else None,
                'activation_supported': activation_supported,
                'activation_support_error': activation_support_error,
                'truncated': truncated}
        self._snapshots[window_ref] = snapshot
        return snapshot

    def act(self, window_ref, target_ref, operation, value):
        previous = self._snapshots.get(window_ref)
        if previous is None or revision(self.snapshot(window_ref)) != revision(previous):
            raise AXStaleError('AX controls changed before dispatch')
        ax = self._load()[0]
        element = self._targets.get(window_ref, {}).get(target_ref)
        if element is None:
            raise AXStaleError('target is outside observed window')
        if target_ref in self._menu_targets.get(window_ref, set()):
            _, _, app, window = self._windows[window_ref]
            main = self._get(app, 'AXMainWindow')
            if main is None or not self._load()[2].CFEqual(main, window) or self._get(app, 'AXFrontmost') is not True:
                raise AXStaleError('selected document is no longer main; menu action not dispatched')
        if operation == 'activate':
            _, _, app, window = self._windows[window_ref]
            cf = self._load()[2]
            main = self._get(app, 'AXMainWindow')
            if not cf.CFEqual(element, window) or main is None or not cf.CFEqual(main, window):
                raise AXStaleError('selected document is no longer main; activation not dispatched')
            error, writable = ax.AXUIElementIsAttributeSettable(app, 'AXFrontmost', None)
            if error or not writable:
                raise AXStaleError('owned application activation is unavailable; not dispatched')
            error = ax.AXUIElementSetAttributeValue(app, 'AXFrontmost', True)
            if error:
                raise RuntimeError(f'AX activate returned {error}; action state uncertain')
            # One mutation only. These bounded IPC reads never redispatch it.
            for check in range(10):
                try:
                    main = self._get(app, 'AXMainWindow')
                    if main is None or not cf.CFEqual(main, window):
                        raise AXActivationUnverified('activation applied but selected document is no longer main')
                    if self._get(app, 'AXFrontmost') is True:
                        return
                except AXActivationUnverified:
                    raise
                except Exception as exc:
                    raise AXActivationUnverified(f'activation applied but verification failed: {exc}') from exc
                if check < 9:
                    time.sleep(.05)
            raise AXActivationUnverified('activation applied but owned application did not become active in 10 checks')
        if operation == 'fill':
            error = ax.AXUIElementSetAttributeValue(element, 'AXValue', value)
        elif operation == 'press':
            error = ax.AXUIElementPerformAction(element, 'AXPress')
        else:
            raise ValueError('unsupported operation')
        if error:
            raise RuntimeError(f'AX {operation} returned {error}; action state uncertain')


class NativeAXAdapter:
    def __init__(self, driver=None, trace_path=None):
        self.driver = driver if driver is not None else MacOSAXDriver()
        self.trace_path = Path(trace_path) if trace_path else None
        self.surface_id = 'native:' + uuid.uuid4().hex
        self.current = None
        self._lock = asyncio.Lock()

    def _record(self, phase, start, **data):
        if self.trace_path:
            self.trace_path.parent.mkdir(parents=True, exist_ok=True)
            with self.trace_path.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps({'phase': phase, 'elapsed_ms': round((time.monotonic()-start)*1000, 3),
                                         **data}, ensure_ascii=False) + '\n')

    def _observe(self, window_ref):
        snapshot = self.driver.snapshot(window_ref)
        self.current = {'observation_id': uuid.uuid4().hex, 'surface_id': self.surface_id,
                        'revision': revision(snapshot), 'source': 'ax',
                        'ocr_fallback': {'available': False, 'source': None,
                                         'reason': 'no OCR provider configured'}, **snapshot}
        return self.current

    def _error(self, exc, action_applied=False):
        code, outcome = ('AXDriverError', 'tool_error')
        if isinstance(exc, AXReadUnavailableError): code = 'AXReadUnavailable'
        elif isinstance(exc, AXActivationUnverified): code = 'AXActivationUnverified'
        elif isinstance(exc, AXPermissionError): code, outcome = 'AXPermissionDenied', 'rejected'
        elif isinstance(exc, AXUnavailableError): code, outcome = 'NotAvailable', 'rejected'
        elif isinstance(exc, AXStaleError): code, outcome = 'StaleObservation', 'rejected'
        elif isinstance(exc, ValueError): code, outcome = 'InvalidArgument', 'rejected'
        result = {'success': False, 'error': code, 'message': str(exc), 'outcome': outcome,
                'action_applied': action_applied,
                'ocr_fallback': {'available': False, 'source': None, 'reason': 'no OCR provider configured'}}
        if isinstance(exc, AXWindowClosedError):
            result['window_closed'] = True
        return result

    async def windows(self, bundle_id):
        async with self._lock:
            start = time.monotonic()
            self.current = None
            try: result = {'success': True, 'windows': self.driver.windows(bundle_id), 'action_applied': False}
            except Exception as exc: result = self._error(exc)
            self._record('identify', start, bundle_id=bundle_id, result=result)
            return result

    async def observe(self, window_ref):
        async with self._lock:
            start = time.monotonic()
            self.current = None
            try: result = {'success': True, 'observation': self._observe(window_ref), 'action_applied': False}
            except Exception as exc: result = self._error(exc)
            self._record('observe', start, window_ref=window_ref, result=result)
            return result

    async def act(self, observation_id, operation, target_ref, value=None):
        async with self._lock:
            start = time.monotonic()
            window_ref = self.current['window_ref'] if self.current else None
            applied = False
            observation_exhausted = False
            try:
                if not self.current or observation_id != self.current['observation_id']:
                    raise AXStaleError('observe again before acting')
                fresh = self.driver.snapshot(window_ref)
                if revision(fresh) != self.current['revision']:
                    raise AXStaleError('window or control changed; no action applied')
                target = next((t for t in fresh['targets'] if t['target_ref'] == target_ref), None)
                if not target or operation not in target['operations']:
                    result = self._error(ValueError('operation is not supported by observed control'))
                    result['error'] = 'UnsupportedAction'
                elif operation == 'fill' and (not isinstance(value, str) or len(value) > 10000):
                    raise ValueError('fill requires a string of at most 10000 characters')
                else:
                    applied = None  # A driver exception after dispatch cannot prove no mutation.
                    self.driver.act(window_ref, target_ref, operation, value)
                    applied = True
                    try:
                        for read_attempt in range(3):
                            try:
                                observed = self._observe(window_ref)
                                break
                            except AXReadUnavailableError as exc:
                                self._record('observation_wait', start, attempt=read_attempt+1,
                                             error=str(exc), action_applied=True)
                                if read_attempt==2:
                                    observation_exhausted = True
                                    self.current = None
                                    raise
                                await asyncio.sleep(.05)
                    except AXWindowClosedError:
                        self.current = None
                        observed = {'source': 'ax', 'surface_id': self.surface_id,
                                    'window_ref': window_ref, 'window_closed': True, 'targets': []}
                    result = {'success': True, 'action_applied': True, 'observation': observed}
            except Exception as exc:
                if isinstance(exc, AXActivationUnverified):
                    applied = True
                if applied is None and isinstance(exc, (AXPermissionError, AXUnavailableError, AXStaleError, AXReadUnavailableError)):
                    applied = False
                result = self._error(exc, applied)
            if not result['success'] and window_ref and not observation_exhausted:
                try: result['observation'] = self._observe(window_ref)
                except Exception as exc:
                    self.current = None
                    result['observation_error'] = f'{type(exc).__name__}: {exc}'
            self._record('execute', start, action={'observation_id': observation_id, 'operation': operation,
                'target_ref': target_ref, 'value': value}, result=result)
            return result

    def register_tools(self, registry):
        async def native_windows(bundle_id): return json.dumps(await self.windows(bundle_id), ensure_ascii=False)
        async def native_observe(window_ref): return json.dumps(await self.observe(window_ref), ensure_ascii=False)
        async def native_act(observation_id, operation, target_ref, value=None):
            return json.dumps(await self.act(observation_id, operation, target_ref, value), ensure_ascii=False)
        for name, handler, properties, required, description in [
            ('native_windows', native_windows, {'bundle_id': {'type': 'string'}}, ['bundle_id'],
             'Identify bounded AX windows of exactly one running macOS application by bundle ID.'),
            ('native_observe', native_observe, {'window_ref': {'type': 'string'}}, ['window_ref'],
             'Observe AX controls in an identified window; OCR fallback is unavailable.'),
            ('native_act', native_act, {'observation_id': {'type': 'string'}, 'target_ref': {'type': 'string'},
              'operation': {'type': 'string', 'enum': ['fill', 'press', 'activate']}, 'value': {'type': 'string'}},
             ['observation_id', 'operation', 'target_ref'], 'Act only on fresh observed AX controls; stale refs require reobservation.')]:
            registry.register(ToolDefinition(name, description, {'type': 'object', 'properties': properties,
                'required': required, 'additionalProperties': False}, handler))
