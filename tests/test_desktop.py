"""G0 desktop driver: the state-table rendering and the trusted checkers (no AX needed)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts' / 'experiments'))

from core.computer_use.desktop import render  # noqa: E402
import desktop_run  # noqa: E402


def observation(items, **extra):
    return {'app': 'com.apple.systempreferences', 'window': '外观', 'frontmost': False, 'items': items,
            'truncated': False, 'menus': [], **extra}


def test_render_shows_state_label_and_ops():
    text = render(observation([
        {'kind': 'text', 'text': '边栏图标大小'},
        {'ref': 'e1', 'kind': 'popup', 'label': '边栏图标大小', 'state': '中', 'id': 'SidebarIconSizePicker',
         'ops': ['press'], 'enabled': True},
        {'ref': 'e2', 'kind': 'switch', 'label': '基于墙纸颜色调整窗口背景色调', 'state': 'on', 'id': '', 'ops': [],
         'enabled': True},
        {'ref': 'e3', 'kind': 'textarea', 'label': '', 'state': 'a\nb\n', 'id': '', 'ops': ['fill'], 'enabled': True},
    ], menus=[['文件', '保存']]))
    assert '(in background; you can still act on it)' in text
    assert '[e1] popup "边栏图标大小" id=SidebarIconSizePicker = 中 (press)' in text
    assert '[e2] switch "基于墙纸颜色调整窗口背景色调" = on' in text
    assert "value='a\\nb\\n'" in text                     # exact text with newlines, as the checker compares it
    assert 'Menu commands you may use: 文件 > 保存' in text


class FakeAX:
    def __init__(self, items):
        self.items = items

    def snapshot(self):
        return observation(self.items)


def test_calculator_check_requires_a_computation():
    task = {'expected': '6912'}
    calc = desktop_run.Calculator.__new__(desktop_run.Calculator)
    calc.task = task
    calc.ax = FakeAX([{'kind': 'text', 'text': '上个表达式: 1 234 + 5 678'}, {'kind': 'text', 'text': '编辑字段: 6 912'}])
    assert calc.check(None)['passed']
    calc.ax = FakeAX([{'kind': 'text', 'text': '编辑字段: 6 912'}])  # typed the answer digits directly
    assert not calc.check(None)['passed']


def test_settings_switch_answer_matching():
    reader = desktop_run.SettingsRead.__new__(desktop_run.SettingsRead)
    reader.task = {'pane': 'p', 'check': {'id': 'TintWindowBackgroundToggle'}}
    reader.ax = FakeAX([{'ref': 'e1', 'kind': 'switch', 'id': 'TintWindowBackgroundToggle', 'state': 'on'}])
    assert reader.check({'answer': 'On'})['passed']
    assert reader.check({'answer': '是的，已开启'})['passed']
    assert not reader.check({'answer': 'off'})['passed']
    assert not reader.check({'answer': 'on or off, not sure'})['passed']
    assert not reader.check(None)['passed']


def test_app_desktop_tools_register_and_detect_corrections(tmp_path):
    from core.computer_use.desktop_service import DesktopService, is_correction, register_desktop_tools
    from core.tool_registry import ToolRegistry
    registry = ToolRegistry()
    service = DesktopService(model_provider=None, root=tmp_path)
    register_desktop_tools(registry, service)
    assert registry.has_tool('desktop_task') and registry.has_tool('desktop_learn') and registry.has_tool('open_documents')
    description = registry._tools['desktop_task'].description
    assert description.startswith('Last resort') and 'Never use it for arithmetic' in description
    assert is_correction('不对，应该是 126') and is_correction('That is wrong') and not is_correction('帮我改一下文档')
    assert not service.recent()                                  # nothing ran yet: a "不对" is ordinary chat
    assert service.learn('不对')['success'] is False
    assert 'unsupported app' in service.run('photoshop', 'x')['error']


def test_arithmetic_alone_does_not_surface_desktop_tools():
    from core.tool_visibility import select
    assert 'desktop_task' not in select('帮我算一下 (15 + 27) × 3', 'chat').names
    assert 'desktop_task' in select('系统设置里边栏图标大小是多少', 'chat').names


def test_doc_tools_edit_by_piece_and_line_and_are_undoable(tmp_path):
    import json
    from core.tools.file_ops import doc_append_lines, doc_read, doc_replace
    doc = tmp_path / 'notes.txt'
    doc.write_text('Meeting on Tuesdya.\nBring slides.\n')
    work = str(tmp_path / 'ws')
    assert json.loads(doc_read(str(doc)))['text'].startswith('Meeting')
    assert json.loads(doc_replace(str(doc), 'Tuesdya', 'Tuesday', workspace_dir=work))['success']
    assert json.loads(doc_append_lines(str(doc), ['- buy milk'], workspace_dir=work))['success']
    assert doc.read_text() == 'Meeting on Tuesday.\nBring slides.\n- buy milk\n'
    assert json.loads(doc_replace(str(doc), 'e', 'x', workspace_dir=work))['error'] == 'NotUnique'
    assert json.loads(doc_append_lines(str(doc), 'not a list', workspace_dir=work))['error'] == 'InvalidInput'


def test_doc_task_surfaces_the_locate_then_edit_tools():
    from core.tool_visibility import select
    names = select('把 TextEdit 里打开的会议纪要文档的错字改掉', 'command').names
    assert {'open_documents', 'doc_read', 'doc_replace'} <= set(names)


def test_doc_scope_blocks_unnamed_files_and_noop_edits(tmp_path):
    import json
    from core.tools import file_ops
    named, other = tmp_path / 'todo.txt', tmp_path / 'code.py'
    named.write_text('a\n')
    other.write_text('import os\n')
    work = str(tmp_path / 'ws')
    try:
        file_ops.set_doc_scope([str(named)])
        assert json.loads(file_ops.doc_replace(str(other), 'import os', 'import sys', workspace_dir=work))['error'] == 'OutOfScope'
        assert json.loads(file_ops.doc_append_lines(str(other), ['x'], workspace_dir=work))['error'] == 'OutOfScope'
        assert json.loads(file_ops.doc_replace(str(named), 'a', 'a', workspace_dir=work))['error'] == 'NoChange'
        assert json.loads(file_ops.doc_replace(str(named), 'a', 'b', workspace_dir=work))['success']
        file_ops.set_doc_scope([])
        assert json.loads(file_ops.doc_replace(str(named), 'b', 'c', workspace_dir=work))['error'] == 'OutOfScope'
    finally:
        file_ops.set_doc_scope(None)
    assert other.read_text() == 'import os\n' and named.read_text() == 'b\n'


def test_named_but_missing_file_never_offers_other_documents(monkeypatch):
    from core.computer_use import desktop_service as ds
    monkeypatch.setattr(ds, 'open_documents', lambda: [{'app': 'Code', 'window': 'x', 'path': '/Users/u/real/code.py'}])
    hint = ds.document_hint('把 nofile.txt 里的 A 改成 B')
    assert '没有找到用户说的文件 nofile.txt' in hint and 'code.py' not in hint
    assert ds.document_scope('把 nofile.txt 里的 A 改成 B') == ([], ['nofile.txt'])
    assert ds.document_scope('把 code.py 里的 A 改成 B')[0] == ['/Users/u/real/code.py']
