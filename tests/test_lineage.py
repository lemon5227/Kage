import importlib.util
from pathlib import Path

import pytest

from core.evolution.lineage import Lineage, Version


def v(id, parent, passed, total, status='active', created=0.0, hyp=''):
    return Version(id=id, parent=parent, target='recovery', digest='d-' + id, hypothesis=hyp or f'try {id}',
                   created=created, validation={'passed': passed, 'total': total}, status=status)


def tree(path):
    lin = Lineage(path)
    lin.record(v('root', None, 5, 10, created=1))
    lin.record(v('A', 'root', 8, 10, created=2))
    lin.record(v('A1', 'A', 0, 10, 'rejected', created=3))
    lin.record(v('A2', 'A', 0, 10, 'rejected', created=4))
    lin.record(v('B', 'root', 6, 10, created=5))
    lin.record(v('B1', 'B', 7, 10, created=6))
    return lin


def test_subtree_scores_and_parent_selection(tmp_path):
    lin = tree(tmp_path / 'lineage.jsonl')
    assert lin.subtree_score('A') == pytest.approx((9 / 12 + 1 / 12 + 1 / 12) / 3)
    assert lin.subtree_score('B') == pytest.approx((7 / 12 + 8 / 12) / 2)
    assert lin.subtree_score('root') == pytest.approx((6 + 9 + 1 + 1 + 7 + 8) / 12 / 6)
    # A has the best own score but a clade of rejected children; B1's clade wins.
    assert lin.select_parent().id == 'B1'
    lin.set_status('B1', 'rejected')
    assert lin.select_parent().id == 'B'


def test_reload_ties_and_integrity(tmp_path):
    path = tmp_path / 'lineage.jsonl'
    tree(path)
    lin = Lineage(path)                       # replay from disk, including status updates
    lin.set_status('B1', 'retired')
    again = Lineage(path)
    assert again.nodes['B1'].status == 'retired' and len(again.nodes) == 6
    lin.record(v('C', 'B1', 7, 10, created=9))   # same score as B1, newer
    assert lin.select_parent().id == 'C'
    with pytest.raises(ValueError):
        lin.record(v('X', 'missing', 1, 1))
    with pytest.raises(ValueError):
        lin.record(Version(id='A', parent='B', target='recovery', digest='d-A'))


def test_svg_has_one_node_per_version(tmp_path):
    path = tmp_path / 'lineage.jsonl'
    tree(path)
    spec = importlib.util.spec_from_file_location(
        'lineage_plot_under_test', Path(__file__).resolve().parents[1] / 'scripts/experiments/lineage_plot.py')
    plot = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(plot)
    out = tmp_path / 'tree.svg'
    plot.main(['--lineage', str(path), '--out', str(out)])
    svg = out.read_text()
    assert svg.startswith('<svg') and svg.count('class="node"') == 6 and svg.count('<line') == 5
    assert '#c62828' in svg and 'clade' in svg
