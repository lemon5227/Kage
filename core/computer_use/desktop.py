"""G0: app-scoped macOS desktop control through the Accessibility API, for the student model.

`native_ax` is the strict TextEdit-document driver from 10-07..09 (one document, Save/Close menus only,
whole-window revision checks). It stops on apps built with SwiftUI: Calculator and System Settings
return -25200 for action discovery on some nodes, and a display that changes after every press makes a
whole-window revision check reject every second action. This driver keeps the same safety rules where
they matter and relaxes the rest:

- scope is one application (bundle id) and its front window, plus an allow-list of menu commands;
- no keyboard events and no coordinates: only AXPress on observed controls, AXValue writes on observed
  text fields, and allow-listed menu items;
- an action is checked against the element itself (still alive, same role, still offers the operation),
  not against the whole window, and every action returns a fresh observation (the 10-09 stall was the
  model acting on refs that went stale after the app lost focus);
- the observation is a C4-style state table: controls in document order with their current state
  (switch on/off, selected radio, popup value, text field contents), and unlabeled controls take the
  nearest preceding static text as their label (System Settings puts the label in a sibling text).
"""
from __future__ import annotations

import re
import time

STATE_ROLES = {'AXCheckBox', 'AXRadioButton', 'AXPopUpButton', 'AXMenuButton', 'AXSlider', 'AXComboBox'}
TEXT_ROLES = {'AXTextField', 'AXTextArea'}
CONTROL_ROLES = {'AXButton', 'AXLink', 'AXTab'} | STATE_ROLES | TEXT_ROLES
CONTEXT_ROLES = {'AXStaticText', 'AXHeading'}
SKIP_ROLES = {'AXScrollBar', 'AXValueIndicator', 'AXSplitter', 'AXImage', 'AXGrowArea'}
SKIP_SUBROLES = {'AXCloseButton', 'AXMinimizeButton', 'AXZoomButton', 'AXFullScreenButton',
                 'AXIncrementArrow', 'AXDecrementArrow', 'AXIncrementPage', 'AXDecrementPage'}
KIND = {'AXButton': 'button', 'AXLink': 'link', 'AXTab': 'tab', 'AXCheckBox': 'checkbox',
        'AXRadioButton': 'radio', 'AXPopUpButton': 'popup', 'AXMenuButton': 'menu-button', 'AXSlider': 'slider',
        'AXComboBox': 'combobox', 'AXTextField': 'textfield', 'AXTextArea': 'textarea'}


class DesktopError(RuntimeError):
    """A rejected request; nothing was dispatched."""


class StaleRef(DesktopError):
    pass


class DesktopAX:
    """One application's front window as numbered controls; handles never leave this object."""

    def __init__(self, bundle_id, *, window_title=None, menus=(), max_visit=3000, max_items=160, max_seconds=8.0,
                 settle_s=0.3):
        self.bundle_id = bundle_id
        self.window_title = window_title                 # TextEdit: only the dedicated document's window
        self.menus = [tuple(m) for m in menus]           # allowed (menu title, item title) pairs
        self.max_visit, self.max_items, self.max_seconds, self.settle_s = max_visit, max_items, max_seconds, settle_s
        self._api = None
        self._handles = {}
        self._items = []
        self.observations = 0

    # --- AX plumbing -------------------------------------------------------------------------------
    def _load(self):
        if self._api is None:
            import ApplicationServices as ax
            import AppKit
            import CoreFoundation
            self._api = ax, AppKit, CoreFoundation
        if not self._api[0].AXIsProcessTrusted():
            raise DesktopError('Accessibility permission is not granted to this process')
        return self._api

    def _get(self, element, name, default=None):
        ax = self._load()[0]
        error, value = ax.AXUIElementCopyAttributeValue(element, name, None)
        return default if error else value

    def _actions(self, element):
        ax = self._load()[0]
        error, names = ax.AXUIElementCopyActionNames(element, None)
        return list(names or []) if error == 0 else []

    def _settable(self, element, name):
        ax = self._load()[0]
        error, settable = ax.AXUIElementIsAttributeSettable(element, name, None)
        return error == 0 and bool(settable)

    def app(self):
        ax, appkit, _ = self._load()
        apps = appkit.NSRunningApplication.runningApplicationsWithBundleIdentifier_(self.bundle_id)
        if len(apps) != 1:
            raise DesktopError(f'{self.bundle_id} is not running exactly once')
        element = ax.AXUIElementCreateApplication(apps[0].processIdentifier())
        ax.AXUIElementSetMessagingTimeout(element, 1.0)
        return element

    def window(self):
        app = self.app()
        if self.window_title is not None:
            matches = [w for w in self._get(app, 'AXWindows', []) or []
                       if self._text(self._get(w, 'AXTitle')) == self.window_title]
            if len(matches) != 1:
                raise DesktopError(f'expected one "{self.window_title}" window, found {len(matches)}')
            return app, matches[0]
        window = self._get(app, 'AXFocusedWindow') or self._get(app, 'AXMainWindow')
        if window is None:
            windows = self._get(app, 'AXWindows', []) or []
            window = windows[0] if windows else None
        if window is None:
            raise DesktopError(f'{self.bundle_id} has no window')
        return app, window

    # --- observation -------------------------------------------------------------------------------
    @staticmethod
    def _text(value, limit=200):
        text = '' if value is None else str(value)
        return ' '.join(text.replace(' ', ' ').replace('\xa0', ' ').split())[:limit]

    def _state(self, role, subrole, value):
        if value is None:
            return None
        if role in ('AXCheckBox', 'AXRadioButton'):
            return {1: 'on', 0: 'off', 2: 'mixed'}.get(int(value), str(value)) if str(value).lstrip('-').isdigit() else str(value)
        if role in TEXT_ROLES:
            return str(value)                                   # exact, newlines kept: fills are checked literally
        return self._text(value)

    def snapshot(self):
        """Walk the front window in document order; return the items and remember their handles."""
        app, window = self.window()
        start, visited = time.monotonic(), 0
        items, handles, last_text, truncated = [], {}, None, False
        stack = [window]
        while stack:
            if visited >= self.max_visit or time.monotonic() - start > self.max_seconds:
                truncated = True
                break
            element = stack.pop()
            visited += 1
            role = self._get(element, 'AXRole')
            if role is None:
                continue                                            # destroyed during the walk
            subrole = self._get(element, 'AXSubrole')
            if role in SKIP_ROLES or subrole in SKIP_SUBROLES:
                continue
            label = self._text(self._get(element, 'AXTitle') or self._get(element, 'AXDescription'))
            ident = self._text(self._get(element, 'AXIdentifier'), 80)
            if role in CONTEXT_ROLES:
                value = self._text(self._get(element, 'AXValue'))
                # Calculator's display is a static text labelled "输入" whose value is the number.
                text = f'{label}: {value}' if label and value and label != value else (value or label)
                if text:
                    items.append({'kind': 'heading' if role == 'AXHeading' else 'text', 'text': text})
                    last_text = text
            elif role in CONTROL_ROLES:
                enabled = self._get(element, 'AXEnabled', True) is not False
                ops = []
                if enabled and 'AXPress' in self._actions(element):
                    ops.append('press')
                if enabled and role in TEXT_ROLES and self._settable(element, 'AXValue'):
                    ops.append('fill')
                state = self._state(role, subrole, self._get(element, 'AXValue'))
                if role == 'AXButton' and state is not None and not label:
                    label, state = state, None                      # e.g. Calculator's unit buttons
                item = {'kind': 'switch' if subrole == 'AXSwitch' else KIND[role], 'label': label,
                        'state': state, 'id': ident, 'ops': ops, 'enabled': enabled}
                if not label and last_text and role != 'AXButton':
                    item['label'] = last_text                       # System Settings: label is a sibling text
                    item['label_from'] = 'preceding text'
                if ops or state is not None:
                    item['ref'] = f'e{len(handles) + 1}'
                    handles[item['ref']] = (element, role)
                    items.append(item)
            children = self._get(element, 'AXChildren', []) or []
            stack.extend(reversed(list(children)))
        if len(items) > self.max_items:
            items, truncated = items[:self.max_items], True
        kept = {item['ref'] for item in items if 'ref' in item}
        self._handles = {ref: value for ref, value in handles.items() if ref in kept}
        self._items = items
        self.observations += 1
        return {'app': self.bundle_id, 'window': self._text(self._get(window, 'AXTitle')),
                'frontmost': bool(self._get(app, 'AXFrontmost')), 'items': items, 'truncated': truncated,
                'menus': [list(m) for m in self.menus]}

    # --- actions -----------------------------------------------------------------------------------
    def resolve(self, ref):
        """A ref, or a control's id or unique label (the 4B student reached for `id=One` on its first G0 run)."""
        if ref in self._handles:
            return ref
        bracketed = re.match(r'\s*\[?(e\d+)\]', str(ref))      # the whole line: '[e12] button "外观" id=…'
        if bracketed and bracketed.group(1) in self._handles:
            return bracketed.group(1)
        for key in ('id', 'label'):
            matches = [item['ref'] for item in self._items if item.get('ref') and item.get(key) == ref]
            if len(matches) == 1:
                return matches[0]
        return None

    def _target(self, ref, operation):
        resolved = self.resolve(ref)
        if resolved is None:
            example = next((f"[{i['ref']}] for \"{i.get('label') or i.get('id')}\"" for i in self._items if i.get('ref')), '')
            raise StaleRef(f'{ref} is not a ref in the latest observation; pass the bracketed ref, e.g. {example}')
        ref = resolved
        element, role = self._handles[ref]
        if self._get(element, 'AXRole') != role:
            raise StaleRef(f'{ref} no longer exists; use the new observation')
        if operation == 'press' and 'AXPress' not in self._actions(element):
            raise DesktopError(f'{ref} cannot be pressed')
        if operation == 'fill' and not (role in TEXT_ROLES and self._settable(element, 'AXValue')):
            raise DesktopError(f'{ref} is not an editable text field')
        return element

    def press(self, ref):
        ax = self._load()[0]
        error = ax.AXUIElementPerformAction(self._target(ref, 'press'), 'AXPress')
        if error:
            raise RuntimeError(f'AXPress returned {error}; the action may or may not have happened')
        time.sleep(self.settle_s)

    def fill(self, ref, text):
        if not isinstance(text, str) or len(text) > 10000:
            raise DesktopError('text must be a string of at most 10000 characters')
        ax = self._load()[0]
        error = ax.AXUIElementSetAttributeValue(self._target(ref, 'fill'), 'AXValue', text)
        if error:
            raise RuntimeError(f'AXValue write returned {error}; the action may or may not have happened')
        time.sleep(self.settle_s)

    def menu_item(self, menu, item):
        """The live menu item element for an allowed (menu, item) pair, or None."""
        bar = self._get(self.app(), 'AXMenuBar')
        for bar_item in (self._get(bar, 'AXChildren', []) or [])[1:]:
            if self._text(self._get(bar_item, 'AXTitle')) != menu:
                continue
            for submenu in (self._get(bar_item, 'AXChildren', []) or [])[:1]:
                for entry in self._get(submenu, 'AXChildren', []) or []:
                    if self._text(self._get(entry, 'AXTitle')) == item:
                        return entry
        return None

    def menu(self, menu, item):
        if (menu, item) not in self.menus:
            raise DesktopError(f'menu command {menu} > {item} is not allowed in this task; allowed: {self.menus}')
        entry = self.menu_item(menu, item)
        if entry is None:
            raise DesktopError(f'menu command {menu} > {item} not found')
        if self._get(entry, 'AXEnabled', True) is False:
            raise DesktopError(f'menu command {menu} > {item} is disabled'
                               + ('' if self._get(self.app(), 'AXFrontmost') else
                                  ' (the app is in the background; its menus only work after desktop_activate)'))
        error = self._load()[0].AXUIElementPerformAction(entry, 'AXPress')
        if error:
            raise RuntimeError(f'menu AXPress returned {error}; the action may or may not have happened')
        time.sleep(self.settle_s * 2)

    def activate(self):
        """Bring the scoped app to the front (menus of a background app are disabled)."""
        app = self.app()
        error = self._load()[0].AXUIElementSetAttributeValue(app, 'AXFrontmost', True)
        if error:
            raise RuntimeError(f'activation returned {error}')
        for _ in range(20):
            if self._get(app, 'AXFrontmost'):
                time.sleep(self.settle_s)
                return
            time.sleep(.05)
        raise RuntimeError('activation was requested but the app did not become frontmost')

    def menu_checked(self, menu, item):
        entry = self.menu_item(menu, item)
        return entry is not None and bool(self._get(entry, 'AXMenuItemMarkChar'))

    def close_window(self, discard=('不存储', '删除', "Don't Save", 'Delete')):
        """Trusted cleanup only: close the scoped window; an unsaved test document is discarded."""
        ax = self._load()[0]
        try:
            _, window = self.window()
        except DesktopError:
            return 'absent'
        button = self._get(window, 'AXCloseButton')
        if button is None:
            return 'no close button'
        ax.AXUIElementPerformAction(button, 'AXPress')
        time.sleep(.8)
        for sheet in self._get(window, 'AXSheets', []) or []:
            for child in self._get(sheet, 'AXChildren', []) or []:
                if self._get(child, 'AXRole') == 'AXButton' and self._text(self._get(child, 'AXTitle')) in discard:
                    ax.AXUIElementPerformAction(child, 'AXPress')
                    time.sleep(.5)
                    return 'closed, unsaved changes discarded'
        return 'closed'

    def press_menu_unchecked(self, menu, item):
        """Trusted setup/cleanup only (not a model tool): press a menu item regardless of the allow-list."""
        entry = self.menu_item(menu, item)
        if entry is None:
            raise DesktopError(f'{menu} > {item} not found')
        self._load()[0].AXUIElementPerformAction(entry, 'AXPress')
        time.sleep(self.settle_s * 2)


def render(observation, max_value=400):
    """Plain-text state table for the model (one line per control or text)."""
    lines = [f"App {observation['app']}, window \"{observation['window']}\""
             + ('' if observation.get('frontmost') else ' (in background; you can still act on it)')]
    for item in observation['items']:
        if item['kind'] in ('text', 'heading'):
            lines.append(f"  {'#' if item['kind'] == 'heading' else '-'} {item['text']}")
            continue
        parts = [f"[{item['ref']}] {item['kind']}"]
        if item.get('label'):
            parts.append(f"\"{item['label']}\"")
        if item.get('id'):
            parts.append(f"id={item['id']}")
        if item.get('state') is not None:
            state = item['state']
            if item['kind'] in ('textfield', 'textarea'):
                shown = state if len(state) <= max_value else state[:max_value] + f'… ({len(state)} chars)'
                parts.append('value=' + repr(shown))
            else:
                parts.append(f'= {state}')
        if not item.get('enabled', True):
            parts.append('(disabled)')
        elif item.get('ops'):
            parts.append('(' + ', '.join(item['ops']) + ')')
        lines.append('  ' + ' '.join(parts))
    if observation.get('truncated'):
        lines.append('  … (observation truncated)')
    if observation.get('menus'):
        lines.append('Menu commands you may use: ' + '; '.join(f'{m} > {i}' for m, i in observation['menus']))
    return '\n'.join(lines)
