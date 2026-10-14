"""Bootstrap in-task help policy (W3-2): ask instead of finishing silently.

Standard library only; runs inside the recovery sandbox and touches no files.
"""


def recover(error, history, checkpoints):
    goal = str(error.get('goal', '')).lower()
    written = error.get('written_files') or []
    wants_write = any(w in goal for w in ('implement', 'fix', 'write', 'save', 'create', 'update'))
    if error.get('trigger') == 'finish_after_tool_error' and not written:
        return {'action': 'request_help', 'reason': 'last tool failed and nothing was written'}
    if wants_write and not written:
        return {'action': 'request_help', 'reason': 'task asks for a file change but none was made'}
    return {'action': 'stop'}
