import hashlib
import json

from core.evolution.skills import SkillCatalog

CODE = 'def run(arguments, context):\n    return {"success": True}\n'


def bundle(tmp_path, skills):
    items = []
    for i, (skill_id, description) in enumerate(skills):
        descriptor = {'skill_id': skill_id, 'description': description,
                      'parameters': {'type': 'object', 'properties': {}}, 'entrypoint': f's{i}.py:run'}
        canonical = json.dumps(descriptor, sort_keys=True, separators=(',', ':'), allow_nan=False)
        descriptor['digest'] = hashlib.sha256(canonical.encode() + b'\n' + CODE.encode()).hexdigest()
        (tmp_path / f's{i}.py').write_text(CODE)
        items.append(descriptor)
    (tmp_path / 'manifest.json').write_text(json.dumps({'version': 1, 'skills': items}))
    return SkillCatalog.from_bundle(tmp_path)


def test_natural_student_query_finds_skill_by_overlap(tmp_path):
    # Real E-0 query that returned [] under all-terms matching while the skill existed.
    catalog = bundle(tmp_path, [
        ('log_line_count_by_field', "Implement a function that parses '<timestamp> <LEVEL> <service>: <message>' "
                                    'log lines and counts them per service, filtering by allowed levels.'),
        ('slugify_title', 'Turn a title into a URL slug.')])
    found = catalog.search('digest_lines log lines per service ERROR WARN')['skills']
    assert [s['skill_id'] for s in found] == ['log_line_count_by_field']


def test_ranking_and_empty_query(tmp_path):
    catalog = bundle(tmp_path, [
        ('merge_intervals', 'Merge overlapping intervals sorted by start.'),
        ('count_log_levels', 'Count log lines per level; log format with level and service.')])
    ranked = catalog.search('count log level lines')['skills']
    assert ranked[0]['skill_id'] == 'count_log_levels'
    assert all(s['skill_id'] != 'merge_intervals' for s in ranked)          # zero overlap is not returned
    assert len(catalog.search('')['skills']) == 2                           # empty query lists all (preview)
    assert catalog.search('weather forecast')['skills'] == []
