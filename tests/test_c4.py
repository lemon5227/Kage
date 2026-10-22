"""C4 interface arms: page_state table, student context packing, environment wiring (no browser, no GPU)."""
import pytest

from core.computer_use.browser import page_state
from core.evolution.stream import browser_interface
from scripts.experiments import kaggle_e1


def test_page_state_lists_toggles_on_and_off_and_field_values():
    targets = [
        {'target_ref': 'e1', 'label': 'Email notifications', 'input_type': 'checkbox', 'checked': True},
        {'target_ref': 'e2', 'label': 'SMS notifications', 'input_type': 'checkbox', 'checked': False},
        {'target_ref': 'e3', 'label': 'Total', 'input_type': 'text', 'operations': ['fill', 'click'], 'value': '42'},
        {'target_ref': 'e4', 'label': 'Save', 'input_type': 'submit', 'operations': ['click']},
    ]
    assert page_state(targets) == {'toggles': ['Email notifications: on', 'SMS notifications: off'],
                                   'fields': ['Total = "42"']}


def test_browser_interface_defaults_to_the_frozen_v1_protocol(monkeypatch):
    for key in ('KAGE_BROWSER_OBS', 'KAGE_BROWSER_PACK', 'KAGE_BROWSER_STATE'):
        monkeypatch.delenv(key, raising=False)
    assert browser_interface() == {'observation_format': 'compact-v1', 'pack_context': False, 'state_table': False}
    monkeypatch.setenv('KAGE_BROWSER_OBS', 'compact-v2')
    monkeypatch.setenv('KAGE_BROWSER_PACK', '1')
    monkeypatch.setenv('KAGE_BROWSER_STATE', '1')
    assert browser_interface() == {'observation_format': 'compact-v2', 'pack_context': True, 'state_table': True}


class _Model:
    max_calls = 10
    calls = []


def test_chain_identity_only_changes_when_an_interface_arm_is_on(tmp_path):
    from core.computer_use.experiment import BrowserChainProvider
    from core.evolution.stream_tasks import FAMILIES
    task = FAMILIES['web_prefs'](17000)
    task['task_id'] = 'x'
    plain = BrowserChainProvider(_Model(), task, max_model_calls=10, max_loop_steps=8)
    armed = BrowserChainProvider(_Model(), task, max_model_calls=10, max_loop_steps=8,
                                 observation_format='compact-v2', pack_context=True, state_table=True)
    assert 'pack_context' not in plain.cache_identity() and 'state_table' not in plain.metadata()
    assert armed.cache_identity()['pack_context'] and armed.metadata()['state_table']
    assert 'page_state' in armed._experiment_soul() and 'page_state' not in plain._experiment_soul()
    from core.computer_use.context_pack import BrowserContextProvider
    assert isinstance(armed._actor_model(object(), 'student', tmp_path), BrowserContextProvider)
    assert not isinstance(plain._actor_model(object(), 'student', tmp_path), BrowserContextProvider)


def test_c4_jobs_cover_four_arms_three_runs_with_distinct_ports():
    jobs = kaggle_e1.c4_jobs()
    assert len(jobs) == 12 and len({argv[-1] for _, argv, _ in jobs}) == 12
    env = {name: e for name, _, e in jobs}
    assert env['web-V1-r1'] == {'KAGE_CTX': kaggle_e1.BROWSER_CTX}
    assert env['web-V2PKST-r3']['KAGE_BROWSER_STATE'] == '1' and env['web-V2-r2']['KAGE_BROWSER_OBS'] == 'compact-v2'
    assert all('eval/stream_web_v1/eval.json' in ' '.join(argv) for _, argv, _ in jobs)
