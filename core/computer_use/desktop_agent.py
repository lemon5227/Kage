"""The desktop agent loop shared by the G0 experiments (scripts/experiments/desktop_run.py) and the Kage app
(the `desktop_task` tool): model-facing tools over one app's Accessibility tree, grounded lessons, the loop.

Interface history (each step measured in `evidence/reports/g0/analysis.md`): v2 accepts a whole observation line
or a control id as a ref and reminds once when the model replies without a tool; v4 edits text by lines (line
breaks written by the program), because the 4B student cannot write line breaks reliably inside JSON strings.
Lesson mode `plan` puts lessons next to the task and asks for a grounded plan first (system-prompt lessons were
ignored: 3/15, the same as no lessons; plan 10/15).
"""
from __future__ import annotations

import json

from core.computer_use.desktop import DesktopError, render

SYSTEM = (
    'You operate one macOS application through its accessibility controls. The observation lists the window '
    'contents in reading order: "[e7] button "7" id=Seven (press)" is a control you can act on by its ref, '
    '"= value" is its current state, and lines starting with "-" are plain text on screen. '
    'Tools: press(ref) clicks a control; fill(ref, text) replaces the whole text of a text field or text area; '
    'activate() brings the app to the front (its menus only work while it is in front); menu(menu, item) runs '
    'one of the allowed menu commands; answer(text) gives your final answer to a question; done() ends the task. '
    'Every action returns a fresh observation and refs can change, so always use refs from the latest '
    'observation. Act one step at a time. The result is checked by reading the app or the file afterwards: '
    'saying the task is done does not make it done.'
)
TOOLS = {
    'press': ('Click (AXPress) a control from the latest observation.', {'ref': {'type': 'string'}}, ['ref']),
    'fill': ('Replace the whole text of a text field or text area with the given text.',
             {'ref': {'type': 'string'}, 'text': {'type': 'string'}}, ['ref', 'text']),
    'activate': ('Bring the application to the front.', {}, []),
    'menu': ('Run an allowed menu command, e.g. menu="文件", item="保存".',
             {'menu': {'type': 'string'}, 'item': {'type': 'string'}}, ['menu', 'item']),
    'replace_text': ('In a text field or text area, replace one exact piece of its current text (must occur exactly once) '
                     'with new text; everything else is kept as it is.',
                     {'ref': {'type': 'string'}, 'old': {'type': 'string'}, 'new': {'type': 'string'}}, ['ref', 'old', 'new']),
    'append_text': ('Add text at the very end of a text field or text area; the existing text is kept as it is.',
                    {'ref': {'type': 'string'}, 'text': {'type': 'string'}}, ['ref', 'text']),
    'append_lines': ('Add lines at the end of a text area; each given line is written followed by a line break. '
                     'The existing text is kept as it is.',
                     {'ref': {'type': 'string'}, 'lines': {'type': 'array', 'items': {'type': 'string'}}}, ['ref', 'lines']),
    'set_lines': ('Replace the whole text of a text area with the given lines; each line is written followed by a '
                  'line break.', {'ref': {'type': 'string'}, 'lines': {'type': 'array', 'items': {'type': 'string'}}},
                  ['ref', 'lines']),
    'observe': ('Observe the window again.', {}, []),
    'answer': ('Give the final answer to the question and end the task.', {'text': {'type': 'string'}}, ['text']),
    'done': ('End the task when it is complete.', {}, []),
}
FAMILY_TOOLS = {'calculator': ['press', 'observe', 'done'],
                'textedit': ['fill', 'activate', 'menu', 'observe', 'done'],
                'textedit-v3': ['fill', 'replace_text', 'append_text', 'activate', 'menu', 'observe', 'done'],
                'textedit-v4': ['replace_text', 'append_lines', 'set_lines', 'activate', 'menu', 'observe', 'done'],
                'settings_read': ['observe', 'answer']}

def tool_schemas(names):
    return [{'type': 'function', 'function': {'name': n, 'description': TOOLS[n][0],
             'parameters': {'type': 'object', 'properties': TOOLS[n][1], 'required': TOOLS[n][2]}}} for n in names]



TEACH_PROMPT = (
    'A small assistant model operates a macOS application through accessibility tools (press a control, fill a text '
    'field, run a menu command). It failed the task below. You see the task, the actions it took with their results, '
    'and what a trusted checker found. Write ONE general lesson for this application: one or two imperative '
    'sentences that would prevent the same mistake on other tasks of the same kind. Do not mention this task\'s '
    'specific numbers, words or file names, and do not give the answer. The lesson may only use controls that '
    'appear in the application window shown; never assume a control that is not listed. Reply with the lesson only.')


class DesktopTools:
    """The model-facing tools of one task; every call returns a status line plus the fresh observation."""

    def __init__(self, ax, task, interface='v4'):
        """task: {'family': calculator|textedit|settings_read, 'press_ids': optional id prefix that may be pressed
        in a read-only task}. interface picks the TextEdit tool set (v2 fill, v3, v4 line-based)."""
        self.ax, self.task, self.final, self.actions = ax, task, None, 0
        suffix = f'-{interface}'
        family = task['family'] + (suffix if task['family'] + suffix in FAMILY_TOOLS else '')
        self.allowed = FAMILY_TOOLS[family] + (['press'] if task.get('press_ids') else [])

    def observation(self):
        observation = self.ax.snapshot()
        if self.task['family'] == 'settings_read':      # read-only: show no operations except allowed navigation
            for item in observation['items']:
                navigable = self.task.get('press_ids') and str(item.get('id', '')).startswith(self.task['press_ids'])
                item['ops'] = ['press'] if navigable else []
        return render(observation)

    def call(self, name, arguments):
        if name not in self.allowed:
            return f'error: tool {name} is not available in this task'
        try:
            if name == 'press':
                ref = str(arguments.get('ref', ''))
                ref = self.ax.resolve(ref) or ref
                if self.task['family'] == 'settings_read':
                    item = next((i for i in self.ax._items if i.get('ref') == ref), {})
                    if not str(item.get('id', '')).startswith(self.task.get('press_ids') or '\0'):
                        return 'error: only page navigation buttons in the sidebar may be pressed in this task'
                self.ax.press(ref)
            elif name == 'fill':
                self.ax.fill(str(arguments.get('ref', '')), arguments.get('text', ''))
            elif name in ('replace_text', 'append_text', 'append_lines', 'set_lines'):
                # Interface v3 (G0): edits that keep the rest of the text, so the student never retypes a document
                # (v2: 7/9 TextEdit failures dropped the final newline or wrote a literal \\n while retyping).
                ref = self.ax.resolve(str(arguments.get('ref', ''))) or str(arguments.get('ref', ''))
                current = next((i.get('state') for i in self.ax._items if i.get('ref') == ref), None)
                if not isinstance(current, str):
                    return 'error: that ref is not a text field in the latest observation\n' + self.observation()
                lines = arguments.get('lines')
                if name in ('append_lines', 'set_lines') and not (isinstance(lines, list) and all(isinstance(x, str) for x in lines)):
                    return 'error: lines must be a list of strings\n' + self.observation()
                if name == 'append_lines':
                    # Interface v4: line breaks are written by the program; the 4B student could not emit them
                    # reliably in JSON arguments (v3: dropped final newlines, or a literal "\\n" from over-escaping).
                    updated = (current if not current or current.endswith('\n') else current + '\n') + ''.join(x + '\n' for x in lines)
                elif name == 'set_lines':
                    updated = ''.join(x + '\n' for x in lines)
                elif name == 'append_text':
                    updated = current + str(arguments.get('text', ''))
                else:
                    old = str(arguments.get('old', ''))
                    if not old or current.count(old) != 1:
                        return (f'error: the old text occurs {current.count(old) if old else 0} times; it must occur exactly '
                                'once\n' + self.observation())
                    updated = current.replace(old, str(arguments.get('new', '')))
                self.ax.fill(ref, updated)
            elif name == 'activate':
                self.ax.activate()
            elif name == 'menu':
                self.ax.menu(str(arguments.get('menu', '')), str(arguments.get('item', '')))
            elif name == 'answer':
                self.final = {'answer': arguments.get('text')}
                return 'answer recorded'
            elif name == 'done':
                self.final = {'done': True}
                return 'task ended'
            if name != 'observe':
                self.actions += 1
            return 'ok\n' + self.observation()
        except DesktopError as exc:
            return f'error: {exc}\n' + self.observation()
        except Exception as exc:
            return f'error: {type(exc).__name__}: {exc}\n' + self.observation()



def system_prompt(task, lessons, mode='plan'):
    learned = (lessons or {}).get(task['family'], [])
    if not learned or mode != 'system':
        return SYSTEM
    return SYSTEM + '\n\nLessons learned from earlier tasks in this app (follow them):\n' + '\n'.join(f'- {x}' for x in learned)


def user_lessons(task, lessons, mode='plan'):
    """lesson-mode `plan`: lessons next to the task, and the student must say how each applies before acting
    (in G0 the 4B student ignored the same lessons placed in the system prompt: 3/15 with and without)."""
    if mode == 'plan-only':                     # control: the same planning request, no lessons
        return ('\n\nBefore your first action, write a short plan for this task (for example the exact text or the '
                'exact button order you will use). Then follow the plan.')
    learned = (lessons or {}).get(task['family'], [])
    if not learned or mode != 'plan':
        return ''
    return ('\n\nLessons from your earlier attempts at this kind of task:\n' + '\n'.join(f'- {x}' for x in learned)
            + '\nBefore your first action, write a short plan that says how each lesson applies to this task '
              '(for example the exact text or the exact button order you will use). Then follow the plan.')


def run_agent(model, tools, task, trace, max_tokens=400, lessons=None, mode='plan'):
    """task: {'instruction', 'family', 'max_steps'}; trace: a text stream receiving one JSON line per step."""
    messages = [{'role': 'system', 'content': system_prompt(task, lessons, mode)},
                {'role': 'user', 'content': task['instruction'] + user_lessons(task, lessons, mode)
                 + '\n\nCurrent observation:\n' + tools.observation()}]
    schemas = tool_schemas(tools.allowed)
    stop, calls, nudged = 'max_steps', 0, False
    for step in range(task['max_steps']):
        response = model.generate(messages=messages, tools=schemas, max_tokens=max_tokens, temperature=0.7)
        trace.write(json.dumps({'step': step, 'request_messages': len(messages), 'text': response.text,
                                'tool_calls': response.tool_calls, 'error': response.error,
                                'usage': response.usage}, ensure_ascii=False) + '\n')
        if response.error and not response.tool_calls:
            stop = 'model_error'
            break
        if not response.tool_calls:
            if nudged:
                stop = 'no_tool_call'
                break
            # Interface v2: one reminder (the student once wrote "Answer: 中" as plain text instead of calling answer).
            nudged = True
            finish = 'answer(text)' if 'answer' in tools.allowed else 'done()'
            # In plan mode the student sometimes writes the plan and stops; tell it to start executing.
            start = 'Your plan is written; now carry out its first step by calling a tool. ' if calls == 0 else ''
            messages += [{'role': 'assistant', 'content': response.text or ''},
                         {'role': 'user', 'content': f'{start}Reply only through the tools. If you are finished, call {finish}.'}]
            continue
        call = response.tool_calls[0]                              # one action per turn
        calls += 1
        call_id = f'call_{calls}'
        messages.append({'role': 'assistant', 'content': response.text or '',
                         'tool_calls': [{'id': call_id, 'type': 'function',
                                         'function': {'name': call['name'],
                                                      'arguments': json.dumps(call['arguments'], ensure_ascii=False)}}]})
        result = tools.call(call['name'], call['arguments'])
        trace.write(json.dumps({'step': step, 'tool': call['name'], 'arguments': call['arguments'],
                                'result': result}, ensure_ascii=False) + '\n')
        # Context packing (C4): only the latest observation stays in full; earlier tool results keep their status line.
        for message in messages:
            if message['role'] == 'tool' and '\n' in message['content']:
                message['content'] = message['content'].split('\n', 1)[0] + ' (observation superseded)'
        messages.append({'role': 'tool', 'tool_call_id': call_id, 'content': result})
        if tools.final is not None:
            stop = call['name']
            break
    return {'stop': stop, 'tool_calls': calls, 'actions': tools.actions, 'steps': step + 1}
