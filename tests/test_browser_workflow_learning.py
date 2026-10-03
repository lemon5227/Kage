from scripts.experiments.browser_workflow_learning import skill_call_count


def test_skill_call_metric_reads_actor_evidence(tmp_path):
    import json
    workspace=tmp_path/'run';workspace.mkdir()
    (workspace/'actor-tools.jsonl').write_text(
        json.dumps({'name':'skill_search'})+'\n'+json.dumps({'name':'skill_call'})+'\n')
    assert skill_call_count(workspace)==1
