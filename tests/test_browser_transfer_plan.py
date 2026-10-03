import json
from pathlib import Path
import pytest

from core.computer_use.transfer import ARMS,load_plan,result_key


def test_frozen_transfer_plan_has_expected_five_arm_denominator():
    path=Path(__file__).resolve().parents[1]/'eval/computer-use/browser-transfer-v1.json'
    plan=load_plan(path)
    assert plan.arms==ARMS and plan.repeats==3
    assert plan.expected_runs==45
    assert plan.suite_sha256=='46c098fe99e972acca02c76b07584d8e0326c5a9b47ec89ebb07ea5366a4d6c1'


def test_plan_rejects_exposed_or_duplicate_tasks(tmp_path):
    source=json.loads((Path(__file__).resolve().parents[1]/'eval/computer-use/browser-transfer-v1.json').read_text())
    source['tasks'][1]['task_id']=source['tasks'][0]['task_id']
    path=tmp_path/'suite.json';path.write_text(json.dumps(source))
    with pytest.raises(ValueError,match='unique'):
        load_plan(path)


def test_result_keys_are_arm_and_repeat_specific():
    assert result_key('preferences_transfer_state','learned_workflow',2)=='preferences_transfer_state--learned_workflow--r2'
    with pytest.raises(ValueError): result_key('x','unknown',0)
