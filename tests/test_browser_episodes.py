"""Browser learning input must be derived from real, intact actor evidence."""
import json
from pathlib import Path
import pytest

from core.computer_use.episodes import normalize_browser_episode,generation_feedback
from core.evolution.archive import ExperienceArchive
from core.evolution.contracts import RunResult
from core.evolution.journal import Journal


def sample(tmp_path,*,split='dev',student_passed=False,teacher_error=False):
    workspace=tmp_path/'run';workspace.mkdir()
    task={'task_id':'preferences_dev','family':'preferences','split':split,
          'instruction':'Enable Email notifications and save.',
          'fixture':{'kind':'preferences','title':'A','fields':[{'name':'email','label':'Email notifications','initial':False}], 'submit':'Save'},
          'scoring_criteria':{'type':'json_exact_match','expected':{'checker_secret':'NEVER_SEND_TO_GENERATOR'}}}
    initial={'observation_id':'old','source':'dom','surface_id':'page','targets':[{'target_ref':'e1','label':'Email notifications','checked':False}]}
    fresh={**initial,'observation_id':'new','targets':[{'target_ref':'e1','label':'Email notifications','checked':True}]}
    (workspace/'initial-observation.json').write_text(json.dumps(initial))
    actions=[{'actor':'student','name':'browser_act','arguments':{'observation_id':'old','operation':'click','target_ref':'e1'},
              'outcome':'ok','success':True,'result':json.dumps({'success':True,'observation':fresh,'checker_secret':'HIDDEN_RESULT'})}]
    if not student_passed:
        actions.append({'actor':'teacher','name':'browser_act','arguments':{'observation_id':'new','operation':'click','target_ref':'e2'},
                        'outcome':'ok','success':True,'result':json.dumps({'success':True,'observation':fresh})})
    (workspace/'actor-tools.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in actions))
    (workspace/'browser.jsonl').write_text('{"phase":"observe"}\n')
    (workspace/'browser-check.json').write_text(json.dumps({'record':{'email':True},'readback_matches_backend':True,'checker_secret':'HIDDEN_CHECK'}))
    (workspace/'backend.json').write_text(json.dumps({'record':{'email':True},'posts':1}))
    trace=tmp_path/'trace.jsonl';trace.write_text('{"event":"finish"}\n')
    takeover={'triggered':not student_passed,'student_check_passed':student_passed,
              'student_chain':{'stop_reason':'model_returned','model_errors':[]},
              'teacher_check_passed':False if teacher_error else True,
              'teacher_chain':{'stop_reason':'call_error' if teacher_error else 'external_check',
                               'model_errors':['TimeoutError'] if teacher_error else []}}
    result=RunResult('preferences_dev-0','passed',1,str(trace),final_state_path=str(workspace),
                     metadata={'environment_kind':'resettable-local-http-browser','chain':[{'takeover':takeover}]})
    return task,result,workspace


def test_browser_episode_restart_filter_and_whitelisted_generation(tmp_path):
    task,result,workspace=sample(tmp_path,teacher_error=True)
    archive=ExperienceArchive(Journal(tmp_path/'journal.sqlite'))
    episode_id=archive.record(task,result)
    resumed=ExperienceArchive(Journal(tmp_path/'journal.sqlite'))
    episode=resumed.retrieve('preferences',failure_status='external_incomplete')[0]
    assert episode['episode_id']==episode_id
    assert episode['browser']['source_kind']=='mixed_student_teacher'
    assert episode['browser']['verification']=='legacy_final_verified'
    assert episode['browser']['student']['model_errors']==[]
    assert episode['browser']['teacher']['model_errors']==['TimeoutError']
    setup=next(Path(ref['path']) for ref in episode['evidence'] if '.episode-setups' in ref['path'])
    assert json.loads(setup.read_text())['fixture']==task['fixture']
    for name in ('actor-tools.jsonl','browser.jsonl','initial-observation.json'):
        assert any(Path(ref['path']).name==name for ref in episode['evidence'])
    feedback=generation_feedback(episode)
    encoded=json.dumps(feedback)
    assert feedback['instruction']==task['instruction']
    assert feedback['source_kind']=='mixed_student_teacher'
    assert len(feedback['actions'])==2 and feedback['initial_observation']['observation_id']=='old'
    assert 'NEVER_SEND_TO_GENERATOR' not in encoded and 'HIDDEN_RESULT' not in encoded and 'HIDDEN_CHECK' not in encoded
    assert 'scoring_criteria' not in encoded and 'fixture' not in encoded
    assert 'evidence' not in feedback and 'run' not in feedback
    (workspace/'actor-tools.jsonl').write_text('{}\n')
    with pytest.raises(ValueError,match='evidence changed'):
        generation_feedback(episode)
    assert resumed.retrieve('preferences')==[]
    assert resumed.list_episodes()[0]['status']=='stale'


def test_browser_episode_rejects_failed_and_holdout_as_generation_source(tmp_path):
    task,result,workspace=sample(tmp_path,split='holdout',student_passed=True)
    episode=normalize_browser_episode(task,result,workspace)
    assert episode['source_kind']=='student_only'
    archive=ExperienceArchive(Journal(tmp_path/'journal.sqlite'))
    archive.record(task,result)
    assert archive.retrieve('preferences')==[]
    with pytest.raises(ValueError,match='verified dev'):
        generation_feedback(archive.list_episodes()[0])


def test_browser_episode_model_timeout_is_not_skill_failure(tmp_path):
    task,result,workspace=sample(tmp_path,teacher_error=True)
    normalized=normalize_browser_episode(task,result,workspace)
    assert normalized['failure_status']=='external_incomplete'
    assert normalized['teacher']['model_errors']==['TimeoutError']
    assert normalized['teacher']['stop_reason']=='call_error'


def test_preparation_uses_real_run_evidence_but_never_test_tasks(tmp_path):
    from dataclasses import replace
    from scripts.experiments.browser_skill_learning import prepare
    task,result,workspace=sample(tmp_path)
    suite=tmp_path/'suite.json';suite.write_text(json.dumps({'tasks':[task]}))
    rows=tmp_path/'results.json';rows.write_text(json.dumps([result.__dict__]))
    prepared=prepare(suite,rows,tmp_path/'prepared')
    assert len(prepared)==1 and prepared[0]['source_kind']=='mixed_student_teacher'
    assert json.loads(Path(prepared[0]['feedback_path']).read_text())['instruction']==task['instruction']
    failed=replace(result,status='failed',score=0,run_id='preferences_dev-1')
    rows.write_text(json.dumps([failed.__dict__]))
    skipped=prepare(suite,rows,tmp_path/'failed-prepared')
    assert skipped[0]['feedback_path'] is None
    assert skipped[0]['skip_reason']=='not a verified action demonstration'
    task['split']='test';suite.write_text(json.dumps({'tasks':[task]}))
    with pytest.raises(ValueError,match='non-dev'):
        prepare(suite,rows,tmp_path/'not-prepared')


def test_archived_fixture_rebuilds_real_page_and_independent_readback(tmp_path):
    import asyncio
    playwright=pytest.importorskip('playwright.async_api')
    from core.computer_use.task_environment import browser_task_server,checkpoint
    from core.evolution.runner import Evaluator
    task,result,_=sample(tmp_path)
    task['scoring_criteria']={'type':'json_exact_match','file':'browser-outcome.json',
                              'expected':{'record':{'email':True},'readback_matches_backend':True}}
    episode_id=ExperienceArchive(Journal(tmp_path/'journal.sqlite')).record(task,result)
    setup=tmp_path/'.episode-setups'/f'{episode_id}.json'
    restored=json.loads(setup.read_text())
    reset=tmp_path/'reset';reset.mkdir()

    async def run():
        with browser_task_server(restored['fixture'],reset) as (url,_):
            async with playwright.async_playwright() as p:
                browser=await p.chromium.launch(headless=True)
                try:
                    page=await browser.new_page();await page.goto(url)
                    await page.get_by_label('Email notifications').click()
                    await page.get_by_text('Save',exact=True).click()
                    await page.wait_for_function('document.querySelector("[data-result]").textContent.length>0')
                    checked=await checkpoint(page,url,reset)
                    assert checked['record']=={'email':True} and checked['readback_matches_backend']
                    assert Evaluator.score(restored,reset)==1
                finally: await browser.close()
    asyncio.run(run())


def test_frozen_transfer_fixture_and_checker_agree_on_actual_saved_state(tmp_path):
    import asyncio
    playwright=pytest.importorskip('playwright.async_api')
    from core.computer_use.task_environment import browser_task_server,checkpoint
    from core.evolution.runner import Evaluator
    suite=json.loads((Path(__file__).resolve().parents[1]/'eval/computer-use/browser-transfer-v1.json').read_text())
    assert len(suite['tasks'])==3

    async def run():
        async with playwright.async_playwright() as p:
            browser=await p.chromium.launch(headless=True)
            try:
                for task in suite['tasks']:
                    workspace=tmp_path/task['task_id'];workspace.mkdir()
                    with browser_task_server(task['fixture'],workspace) as (url,_):
                        page=await browser.new_page();await page.goto(url)
                        desired=task['scoring_criteria']['expected']['record']
                        for field in task['fixture']['fields']:
                            checkbox=page.get_by_label(field['label'])
                            if await checkbox.is_checked()!=desired[field['name']]:
                                await checkbox.click()
                        await page.get_by_text(task['fixture']['submit'],exact=True).click()
                        await page.wait_for_function('document.querySelector("[data-result]").textContent.length>0')
                        checked=await checkpoint(page,url,workspace)
                        assert checked['readback_matches_backend'] and Evaluator.score(task,workspace)==1
                        await page.close()
            finally: await browser.close()
    asyncio.run(run())
