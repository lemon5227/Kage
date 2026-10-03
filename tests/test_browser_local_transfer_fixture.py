"""Predeclared transfer fixtures are actually saveable under the unchanged budget."""
import json
from pathlib import Path
import pytest
pytest.importorskip('playwright.async_api')
from test_browser_takeover import Actions

ROOT=Path(__file__).resolve().parents[1]

@pytest.mark.parametrize('task_id,actions',[
    ('preferences_local_v2_labels',['Product bulletins','Phone alerts','Weekly roundup','Commit preferences']),
    ('preferences_local_v2_four',['Email notices','Phone notices','Weekly digest','Offer alerts','Store channels']),
    ('preferences_local_v2_zh',['邮件提醒','短信提醒','保存通知配置']),
])
def test_frozen_transfer_fixture_is_saved_and_read_back(tmp_path,task_id,actions):
    from scripts.experiments.browser_skill_diagnosis import load_local_transfer,diagnostic_provider
    from core.evolution.budget import BudgetConfig,BudgetTracker
    from core.evolution.contracts import Candidate,RunSpec
    from core.evolution.journal import Journal
    from core.evolution.runner import EvolutionRunner
    tasks=load_local_transfer(ROOT/'eval/computer-use/browser-local-transfer-v2.json')
    task=next(t for t in tasks if t['task_id']==task_id)
    provider=diagnostic_provider(Actions(actions),task,None,'raw',local=True,model_label='scripted-fixture-check')
    runner=EvolutionRunner(Journal(tmp_path/'j.sqlite'),BudgetTracker(BudgetConfig(max_api_calls=6,
        max_input_tokens_total=48000,max_output_tokens_total=2000),tmp_path/'b.sqlite'),tmp_path/'runs',provider)
    result=runner.run(Candidate('fixture',(),'workflow',str(ROOT),'predeclared'),task,
        RunSpec(task_id,'fixture',task_id,max_steps=1,timeout_s=20))
    assert result.status=='passed' and result.score==1
    checked=json.loads((Path(result.final_state_path)/'browser-check.json').read_text())
    assert checked['posts']==1 and checked['readback_matches_backend']
    assert len(checked['record'])==(4 if task_id.endswith('four') else 3)
    assert result.metadata['chain'][0]['model_calls']==len(actions)
