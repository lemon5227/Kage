"""Project browser run evidence into an audit episode and a safe generation view."""
import hashlib
import json
from pathlib import Path


_EVIDENCE_FILES = ('initial-observation.json', 'actor-tools.jsonl', 'browser.jsonl',
                   'browser-check.json', 'backend.json')


def _ref(path):
    return {'path': str(path.resolve()), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'bytes': path.stat().st_size}


def _read_checked(ref):
    path = Path(ref['path'])
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ValueError('browser episode evidence changed or disappeared') from exc
    if hashlib.sha256(data).hexdigest() != ref['sha256']:
        raise ValueError('browser episode evidence changed')
    return data


def normalize_browser_episode(task, result, workspace):
    """Audit projection; scoring data stays in the archive, outside generation input."""
    root = Path(workspace).resolve()
    refs = {}
    declaration = result.metadata.get('demonstration_source')
    if declaration is not None and declaration not in {'human_declared', 'automation'}:
        raise ValueError('invalid demonstration source declaration')
    names = _EVIDENCE_FILES
    if declaration is not None:
        names += ('demonstration-events.jsonl', 'demonstration-inputs.jsonl', 'final-observation.json',
                  'demonstration-summary.json', 'trace.jsonl')
    for name in names:
        path = root / name
        if not path.is_file():
            raise ValueError(f'missing browser episode evidence: {name}')
        refs[name] = _ref(path)
    actions = [json.loads(line) for line in _read_checked(refs['actor-tools.jsonl']).splitlines() if line.strip()]
    check = json.loads(_read_checked(refs['browser-check.json']))
    takeover = (result.metadata.get('chain') or [{}])[-1].get('takeover') or {}
    student = takeover.get('student_chain') or {}
    teacher = takeover.get('teacher_chain') or {}
    # Merely observing the page is not a corrective action or a teacher skill.
    active = {row.get('actor') for row in actions if row.get('name') == 'browser_act' and row.get('outcome') == 'ok'}
    source_kind = ('mixed_student_teacher' if active == {'student', 'teacher'} else
                   'teacher_only' if active == {'teacher'} else
                   'student_only' if active == {'student'} else 'no_action')
    capture_ok = True
    if declaration is not None:
        source_kind = ('human_demonstration_declared' if declaration == 'human_declared'
                       else 'automation_demonstration')
        summary = json.loads(_read_checked(refs['demonstration-summary.json']))
        capture_ok = (summary.get('success') is True and not summary.get('error')
                      and 0 < summary.get('event_count', 0) <= 64
                      and summary.get('source_kind') == declaration)
    final_verified = result.status == 'passed' and result.score >= 1 and check.get('readback_matches_backend') is True
    final_verified = final_verified and capture_ok
    student_passed = takeover.get('student_check_passed', final_verified if not takeover else None)
    if declaration is not None:
        student_passed = None
    verification = ('legacy_final_verified' if final_verified and takeover.get('teacher_check_passed') is False else
                    'final_verified' if final_verified else 'not_verified')
    return {'environment_kind': 'resettable-local-http-browser',
            'fixture_schema_version': task.get('fixture', {}).get('version', 'fixture-v1'),
            'task_id': task['task_id'], 'family': task.get('family', 'unknown'),
            'split': task.get('split', 'unknown'), 'source_kind': source_kind,
            'failure_status': ('demonstration_verified' if final_verified else 'demonstration_incomplete')
                              if declaration is not None else
                              ('passed' if student_passed is True else 'external_incomplete'),
            'student': {'external_passed': student_passed,
                        'stop_reason': student.get('stop_reason'), 'model_errors': student.get('model_errors', [])},
            'teacher': {'attempted': bool(takeover.get('triggered')),
                        'actual_actions': sum(row.get('actor') == 'teacher' and row.get('name') == 'browser_act' for row in actions),
                        'check_passed': takeover.get('teacher_check_passed'),
                        'stop_reason': teacher.get('stop_reason'), 'model_errors': teacher.get('model_errors', [])},
            'final_external_passed': final_verified, 'verification': verification,
            'actor_segments': [{'actor': actor, 'tool_calls': sum(row.get('actor') == actor for row in actions)}
                               for actor in (('human', 'automation') if declaration is not None else ('student', 'teacher'))
                               if any(row.get('actor') == actor for row in actions)],
            'evidence': refs}


def generation_feedback(episode):
    """Only visible task/DOM/actions enter a skill proposal; verify source bytes again."""
    browser = episode.get('browser')
    if (episode.get('status') != 'verified' or episode.get('split') != 'dev' or not browser
            or browser.get('verification') == 'not_verified' or browser.get('source_kind') == 'no_action'):
        raise ValueError('generation requires a verified dev browser episode with actions')
    refs = browser['evidence']
    for ref in episode.get('evidence', []):
        _read_checked(ref)
    for ref in refs.values():
        _read_checked(ref)
    initial = json.loads(_read_checked(refs['initial-observation.json']))
    actions = []
    for line in _read_checked(refs['actor-tools.jsonl']).splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get('name') not in {'browser_open', 'browser_observe', 'browser_act'}:
            continue
        try:
            result = json.loads(row.get('result') or '{}')
        except (TypeError, ValueError):
            result = {}
        actions.append({'actor': row.get('actor'), 'tool': row['name'],
                        'arguments': row.get('arguments', {}), 'outcome': row.get('outcome'),
                        'error': result.get('error'), 'message': result.get('message'),
                        'action_applied': result.get('action_applied'),
                        'observation': result.get('observation')})
    feedback = {'task_id': episode['task_id'], 'family': episode['family'],
            'instruction': episode['goal'], 'source_kind': browser['source_kind'],
            'verification': browser['verification'], 'initial_observation': initial,
            'actions': actions,
            'source_hashes': {name: ref['sha256'] for name, ref in refs.items()}}
    if browser['source_kind'] in {'human_demonstration_declared', 'automation_demonstration'}:
        feedback['final_observation'] = json.loads(_read_checked(refs['final-observation.json']))
    return feedback
