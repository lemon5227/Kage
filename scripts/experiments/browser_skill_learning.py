"""Prepare verified browser episodes for later skill generation; no model calls."""
import argparse
from dataclasses import fields
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.computer_use.episodes import generation_feedback
from core.evolution.archive import ExperienceArchive
from core.evolution.contracts import RunResult
from core.evolution.journal import Journal


def prepare(suite_path, results_path, output_dir):
    suite = json.loads(Path(suite_path).read_text())
    tasks = {task['task_id']: task for task in suite['tasks'] if task.get('split') == 'dev'}
    rows = json.loads(Path(results_path).read_text())
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    archive = ExperienceArchive(Journal(output / 'journal.sqlite'))
    prepared = []
    for row in rows:
        metadata = row.get('metadata', {})
        chain = metadata.get('chain') or [{}]
        task_id = metadata.get('task_id') or chain[-1].get('task_id') or row.get('run_id', '').rsplit('-', 1)[0]
        task = tasks.get(task_id)
        if task is None:
            raise ValueError(f'unknown or non-dev browser task: {task_id}')
        result = RunResult(**{field.name: row[field.name] for field in fields(RunResult) if field.name in row})
        episode_id = archive.record(task, result)
        stored = next(e for e in archive.list_episodes() if e['episode_id'] == episode_id)
        if (stored['status'] != 'verified' or not stored['browser']['final_external_passed']
                or stored['browser']['source_kind'] == 'no_action'):
            prepared.append({'run_id': result.run_id, 'episode_id': episode_id,
                             'source_kind': stored['browser']['source_kind'],
                             'verification': stored['browser']['verification'],
                             'feedback_path': None, 'skip_reason': 'not a verified action demonstration'})
            continue
        episode = next(e for e in archive.retrieve(task['family'], limit=len(rows)+1)
                       if e['episode_id'] == episode_id)
        feedback = generation_feedback(episode)
        path = output / f'{result.run_id}-generation-feedback.json'
        path.write_text(json.dumps(feedback, ensure_ascii=False, indent=2))
        prepared.append({'run_id': result.run_id, 'episode_id': episode_id,
                         'source_kind': episode['browser']['source_kind'],
                         'verification': episode['browser']['verification'],
                         'feedback_path': str(path), 'source_hashes': feedback['source_hashes']})
    (output / 'manifest.json').write_text(json.dumps({'source_suite': str(Path(suite_path).resolve()),
        'source_results': str(Path(results_path).resolve()), 'episodes': prepared}, ensure_ascii=False, indent=2))
    return prepared


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', type=Path, required=True)
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    prepared = prepare(args.suite, args.results, args.output_dir)
    print(json.dumps({'episodes': len(prepared),
                      'sources': [row['source_kind'] for row in prepared]}, ensure_ascii=False))


if __name__ == '__main__':
    main()
