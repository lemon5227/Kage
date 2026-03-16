from core.intent_router import is_undo_request


def test_is_undo_request():
    assert is_undo_request("撤销上一步") is True
    assert is_undo_request("撤回") is True
    assert is_undo_request("回滚刚才的操作") is True
    assert is_undo_request("undo") is True
    assert is_undo_request("后悔了") is True
    assert is_undo_request("帮我找一下文件") is False
