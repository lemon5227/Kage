"""Deterministically compile intact verified visible form demonstrations."""
import json
from pathlib import Path
import shutil
import tempfile

from core.computer_use.episodes import generation_feedback
from core.computer_use.skills import BrowserSkillCatalog, descriptor_digest


def compile_demonstration(episode: dict, output_dir, *, skill_id: str) -> dict:
    feedback = generation_feedback(episode)
    if feedback['source_kind'] not in {'human_demonstration_declared', 'automation_demonstration'}:
        raise ValueError('compilation requires a demonstration episode')
    final = feedback.get('final_observation') or {}
    forms = final.get('demonstration_forms', [])
    if len(forms) != 1 or final.get('truncated'):
        raise ValueError('demonstration requires one complete visible form')
    controls = forms[0]['controls']
    labels = [control['label'] for control in controls]
    if any(not label for label in labels) or len({label.casefold() for label in labels}) != len(labels):
        raise ValueError('duplicate or empty semantic label')
    fields, saves = [], []
    for control in controls:
        kind, tag = control.get('input_type'), control.get('tag')
        if control.get('disabled') or control.get('read_only'):
            raise ValueError('unsupported disabled or read-only control')
        if tag in {'button', 'input'} and kind == 'submit':
            saves.append(control)
        elif tag == 'input' and kind == 'checkbox':
            fields.append((control, 'ensure_checked'))
        elif tag == 'textarea' or (tag == 'input' and kind in {'text', 'email', 'search', 'tel', 'url'}):
            fields.append((control, 'fill'))
        else:
            raise ValueError('unsupported form control')
    if len(saves) != 1 or not fields:
        raise ValueError('requires one unambiguous save action and editable fields')
    save = saves[0]
    save_actions = [action for action in feedback['actions'] if action['tool'] == 'browser_act'
                    and action['outcome'] == 'ok' and action['arguments'].get('operation') == 'click'
                    and any(target['target_ref'] == action['arguments'].get('target_ref')
                            and target['label'] == save['label'] and target.get('input_type') == 'submit'
                            for target in (action.get('observation') or {}).get('targets', []))]
    if not save_actions:
        raise ValueError('demonstration has no actual save action')
    if len(fields) + 1 > 16:
        raise ValueError('workflow exceeds 16 steps')
    # Reject edits after the last save: final visible fields must be the saved form.
    saved_controls = (save_actions[-1].get('observation') or {}).get('demonstration_forms', [])
    if len(saved_controls) != 1 or saved_controls[0]['controls'] != controls:
        raise ValueError('final form changed after save action')
    properties, arguments, workflow = {}, {}, []
    for index, (field, op) in enumerate(fields, 1):
        label_key, value_key = f'field_{index}_label', f'field_{index}_value'
        properties[label_key] = {'type': 'string', 'minLength': 1}
        properties[value_key] = {'type': 'boolean' if op == 'ensure_checked' else 'string'}
        arguments[label_key] = field['label']
        arguments[value_key] = field['checked'] if op == 'ensure_checked' else field['value']
        workflow.append({'op': op, 'label_param': label_key,
                         'checked_param' if op == 'ensure_checked' else 'value_param': value_key})
    properties['save_label'], arguments['save_label'] = {'type': 'string', 'minLength': 1}, save['label']
    workflow.append({'op': 'click', 'label_param': 'save_label'})
    parameters = {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}
    descriptor = {'skill_id': skill_id, 'description': 'Fill named form fields, ensure checkbox settings and save the form.',
                  'parameters': parameters, 'workflow': workflow}
    descriptor['digest'] = descriptor_digest(descriptor)
    destination = Path(output_dir).resolve()
    if destination.exists():
        raise ValueError('candidate output directory already exists')
    destination.parent.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(prefix='.demonstration-', dir=destination.parent))
    try:
        manifest = {'version': 2, 'kind': 'browser_workflow', 'skills': [descriptor]}
        (staged / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
        lesson = {'bundle_path': str(destination), 'digest': descriptor['digest'], 'skill_id': skill_id,
                  'arguments': arguments, 'parameters': parameters, 'source_kind': feedback['source_kind'],
                  'source_hashes': feedback['source_hashes']}
        (staged / 'demonstration.json').write_text(json.dumps(lesson, ensure_ascii=False, indent=2))
        BrowserSkillCatalog.from_bundle(staged)
        staged.rename(destination)
        return lesson
    finally:
        if staged.exists():
            shutil.rmtree(staged)
