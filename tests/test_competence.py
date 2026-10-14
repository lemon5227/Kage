from core.evolution.competence import CompetenceModel


def test_explores_first_then_asks_when_competence_is_low(tmp_path):
    model = CompetenceModel()
    assert model.should_request_help('logs')['ask'] is False          # unseen: try first
    model.record_task('logs', False)
    model.record_task('logs', False)
    decision = model.should_request_help('logs')
    assert decision['ask'] is True and decision['why'] == 'low competence'
    for _ in range(10):                                            # p = 11/14 -> loss 0.21 < 0.25
        model.record_task('logs', True)
    assert model.should_request_help('logs')['ask'] is False


def test_helped_tasks_count_as_student_failures_and_persist(tmp_path):
    model = CompetenceModel()
    model.record_task('csv', True, helped=True)
    assert model.families['csv'].successes == 0 and model.families['csv'].helped == 1
    model.record_help('csv', True, when='before_attempt', reason='p low')
    path = tmp_path / 'c.json'
    model.save(path)
    again = CompetenceModel.load(path)
    assert again.families['csv'].failures == 1 and again.help_log[0]['when'] == 'before_attempt'


def test_practice_prefers_frontier_families():
    model = CompetenceModel()
    for _ in range(5):
        model.record_task('solved', True)          # p high -> little to learn
    for ok in (True, False, True, False):
        model.record_task('frontier', ok)          # p ~ 0.5
    for _ in range(4):
        model.record_task('hopeless', False)
    assert model.practice_targets(1)[0]['family'] == 'frontier'


def test_skill_adoption_by_use_and_retirement():
    model = CompetenceModel()
    model.record_skill('s1', True)
    assert model.skills['s1'].status == 'active'
    for _ in range(3):
        model.record_skill('bad', False)
    assert any(r['skill_id'] == 'bad' for r in model.retirement_candidates())
