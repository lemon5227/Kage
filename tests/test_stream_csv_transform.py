from core.evolution.completion import check_python_function
from core.evolution.stream_tasks import csv_transform, make_task


REFERENCE = '''import csv, io


def {fn}(text):
    key, required, email, sort_col = {key!r}, {required!r}, {email!r}, {sort_col!r}
    if text == '':
        return ''
    rows = list(csv.reader(io.StringIO(text)))
    header, body = rows[0], rows[1:]
    idx = {{name: i for i, name in enumerate(header)}}
    out, seen = [], set()
    for row in body:
        row = [cell.strip() for cell in row]
        if not row[idx[required]]:
            continue
        if email:
            row[idx[email]] = row[idx[email]].lower()
        if row[idx[key]] in seen:
            continue
        seen.add(row[idx[key]])
        out.append(row)
    out.sort(key=lambda r: r[idx[sort_col]])
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator='\\n')
    writer.writerow(header)
    writer.writerows(out)
    return buf.getvalue()
'''


def test_deterministic():
    assert csv_transform(1001) == csv_transform(1001)
    assert csv_transform(1001) != csv_transform(1002)


def test_reference_passes_stub_fails(tmp_path):
    for seed in range(1000, 1030):
        task = make_task('csv_transform', seed)
        crit = task['scoring_criteria']
        path = tmp_path / crit['file']
        path.write_text(task['initial_files'][crit['file']])
        assert check_python_function(path, crit) == 0.0
        params = {k: v for k, v in csv_transform(seed)['params'].items() if k != 'columns'}
        path.write_text(REFERENCE.format(fn=crit['function'], **params))
        assert check_python_function(path, crit) == 1.0, seed


def test_variety_and_rules():
    specs = [csv_transform(s) for s in range(1000, 1060)]
    assert len({s['instruction'].split(' ')[0] for s in specs}) >= 3
    assert len({s['function'] for s in specs}) >= 4 and len({s['file'] for s in specs}) >= 3
    assert {s['params']['email'] for s in specs} == {'email', None}
    for spec in specs[:20]:
        p = spec['params']
        assert p['key'] in p['columns'] and p['required'] in p['columns'] and p['sort_col'] in p['columns']
        assert 'csv module' in spec['instruction'] and f'"{p["key"]}"' in spec['instruction']


def test_quoted_comma_case_present():
    spec = csv_transform(1003)
    assert any('"Lima, PE"' in c['args'][0] for c in spec['cases'])
