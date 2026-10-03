"""One-family browser workflow generation and 3-repeat local parent/child pilot."""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))

from core.computer_use.experiment import BrowserChainProvider
from core.computer_use.episodes import generation_feedback
from core.computer_use.skill_mutator import BrowserWorkflowMutator
from core.computer_use.skills import BrowserSkillCatalog
from core.evolution.budget import BudgetConfig,BudgetTracker
from core.evolution.archive import ExperienceArchive
from core.evolution.contracts import Candidate
from core.evolution.journal import Journal
from core.evolution.mutator import bundle_digest
from core.evolution.promotion import Promoter
from scripts.experiments.task_suite import RecordedLocalProvider


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def reuse_task(task):
    """Predefined dev variant; this definition is not sent to the optimizer."""
    new=json.loads(json.dumps(task))
    new['task_id']='preferences_dev_reuse'
    new['split']='reuse'
    new['fixture']['title']='Notification options'
    new['fixture']['fields']=[
        {'name':'weekly','label':'Weekly digest','initial':False},
        {'name':'email','label':'Email notifications','initial':True},
        {'name':'sms','label':'SMS notifications','initial':True}]
    new['fixture']['submit']='Save settings'
    return new


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--feedback',type=Path,required=True)
    parser.add_argument('--suite',type=Path,default=ROOT/'eval/computer-use/browser-learning-v2.json')
    parser.add_argument('--frozen-test',type=Path,default=ROOT/'eval/computer-use/browser-transfer-v1.json')
    parser.add_argument('--teacher-config',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--port',type=int,default=18082)
    args=parser.parse_args()
    expected_test_sha='46c098fe99e972acca02c76b07584d8e0326c5a9b47ec89ebb07ea5366a4d6c1'
    if sha(args.frozen_test)!=expected_test_sha:
        parser.error('frozen test manifest changed; stop before generating a candidate')
    suite=json.loads(args.suite.read_text())
    task=next(t for t in suite['tasks'] if t['task_id']=='preferences_dev' and t['split']=='dev')
    feedback=json.loads(args.feedback.read_text())
    if feedback['task_id']!=task['task_id'] or feedback['source_kind'] not in {'student_only','mixed_student_teacher','teacher_only'}:
        parser.error('feedback is not a verified dev source for this task')
    prep=args.feedback.parent
    prep_manifest=json.loads((prep/'manifest.json').read_text())
    source=next((row for row in prep_manifest['episodes']
                 if row.get('feedback_path') and Path(row['feedback_path']).resolve()==args.feedback.resolve()),None)
    if source is None:
        parser.error('feedback is not in the prepared episode manifest')
    indexed=ExperienceArchive(Journal(prep/'journal.sqlite')).retrieve(task['family'],limit=100)
    episode=next((row for row in indexed if row['episode_id']==source['episode_id']),None)
    if episode is None or generation_feedback(episode)!=feedback:
        parser.error('feedback differs from intact archived episode evidence')
    cloud=json.loads(args.teacher_config.read_text())['model']['cloud_api']
    if cloud.get('model_name')!='deepseek-flash' or cloud.get('base_url','').rstrip('/')!='https://api.deepseek.com' or not cloud.get('api_key'):
        parser.error('requires configured official DeepSeek Flash endpoint')
    args.output_dir.mkdir(parents=True,exist_ok=False)
    sources=['core/computer_use/skills.py','core/computer_use/skill_mutator.py','core/computer_use/experiment.py',
             'core/evolution/promotion.py','core/evolution/mutator.py','scripts/experiments/browser_workflow_learning.py']
    config={'protocol':'c21-b21c-preferences-dev-v1','source_hashes':{name:sha(ROOT/name) for name in sources},
            'feedback_sha256':sha(args.feedback),'suite_sha256':sha(args.suite),'frozen_test_sha256':expected_test_sha,
            'model_sha256':sha(Path.home()/'.kage/models/agents-a1-4b/Agents-A1-4B-Q4_K_M.gguf'),
            'git_revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'optimizer':{'model':'deepseek-flash','max_calls':3,'max_input_message_bytes':11000,
                         'max_output_tokens_per_call':3000,'max_assumed_cost_usd':.05,
                         'assumed_input_rate_per_million':.3,'assumed_output_rate_per_million':1.2},
            'student':{'model':'agents-a1-4b','cloud_fallback':False,'max_model_calls':6,
                       'max_browser_primitives':16,'external_completion':True},
            'evaluation':{'dev_pairs':3,'reuse_runs':3,'restart_reuse_runs':1,'kernel_max_steps':1,
                          'step_isolation':'fork','timeout_s':480}}
    (args.output_dir/'config.json').write_text(json.dumps(config,ensure_ascii=False,indent=2))
    journal=Journal(args.output_dir/'journal.sqlite')
    optimizer_budget=BudgetTracker(BudgetConfig(max_api_calls=3,max_input_tokens_total=36000,
        max_output_tokens_total=9000,max_cost_usd=.05,input_cost_per_million=.3,
        output_cost_per_million=1.2),args.output_dir/'optimizer-budget.sqlite')
    local_budget=BudgetTracker(BudgetConfig(max_api_calls=72,max_input_tokens_total=600000,
        max_output_tokens_total=60000,input_cost_per_million=0,output_cost_per_million=0),
        args.output_dir/'student-budget.sqlite')
    parent_dir=args.output_dir/'parent';parent_dir.mkdir()
    (parent_dir/'manifest.json').write_text('{"version":2,"kind":"browser_workflow","skills":[]}')
    parent=Candidate('no-browser-skills',(),'workflow',str(parent_dir.resolve()),bundle_digest(parent_dir))
    optimizer=RecordedLocalProvider(args.output_dir/'optimizer-model.jsonl',api_key=cloud['api_key'],
        model_name=cloud['model_name'],base_url=cloud['base_url'],thinking=False,output_limit=3000)
    mutator=BrowserWorkflowMutator(optimizer,optimizer_budget,journal,args.output_dir/'mutation')
    try:
        child=mutator.propose(parent,feedback)
    except Exception as exc:
        failure={'phase':'generation','error':f'{type(exc).__name__}: {exc}',
                 'optimizer_usage':optimizer_budget.usage_by_type,
                 'optimizer_assumed_cost_usd':optimizer_budget.total_cost_usd}
        (args.output_dir/'failure.json').write_text(json.dumps(failure,ensure_ascii=False,indent=2))
        raise
    def provider_factory(task_def):
        def build(candidate):
            model=RecordedLocalProvider(args.output_dir/f'student-{candidate.digest[:16]}.jsonl',api_key='local',
                model_name='agents-a1-4b',base_url=f'http://127.0.0.1:{args.port}/v1',timeout_sec=120)
            return BrowserChainProvider(model,task_def,model_label='agents-a1-4b',max_model_calls=6,
                                        external_completion=True,browser_skill_bundle=Path(candidate.bundle_path))
        return build
    promoter=Promoter(journal,local_budget,provider_factory(task),args.output_dir/'evaluation',
                      timeout_s=480,step_isolation='fork',kernel_max_steps=1)
    comparison=promoter.compare(parent,child,[task],repeats=3)
    reuse=reuse_task(task)
    reuse_promoter=Promoter(journal,local_budget,provider_factory(reuse),args.output_dir/'evaluation',
                            timeout_s=480,step_isolation='fork',kernel_max_steps=1)
    reuse_results=[reuse_promoter.evaluate(child,reuse,repeat_id=i) for i in range(3)]
    before_restart=local_budget.total_api_calls
    restarted=Promoter(Journal(args.output_dir/'journal.sqlite'),
        BudgetTracker(local_budget.config,args.output_dir/'student-budget.sqlite'),provider_factory(reuse),
        args.output_dir/'evaluation',timeout_s=480,step_isolation='fork',kernel_max_steps=1)
    resumed=restarted.evaluate(child,reuse,repeat_id=0)
    if restarted.budget.total_api_calls!=before_restart or resumed.run_id!=reuse_results[0].run_id:
        raise AssertionError('same-repeat restart consumed another local run')
    def skill_calls(trace_path):
        return sum(json.loads(line).get('action',{}).get('name')=='skill_call'
                   for line in Path(trace_path).read_text().splitlines())
    all_child=[pair['child'] for pair in comparison['pairs']]
    calls=[skill_calls(row['trace_path']) for row in all_child]+[skill_calls(row.trace_path) for row in reuse_results]
    report={'parent':asdict(parent),'child':asdict(child),'comparison':comparison,
            'reuse':[asdict(row) for row in reuse_results],'restart_same_repeat_run_id':resumed.run_id,
            'actual_skill_calls':calls,'optimizer_usage':optimizer_budget.usage_by_type,
            'optimizer_assumed_cost_usd':optimizer_budget.total_cost_usd,
            'student_usage':local_budget.usage_by_type,'browser_skill_digests':BrowserSkillCatalog.from_bundle(child.bundle_path).digests,
            'capability_verified':comparison['promoted'] and all(row.status=='passed' for row in reuse_results) and all(c>0 for c in calls)}
    (args.output_dir/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({'promoted':comparison['promoted'],'parent_score':comparison['parent_score'],
                      'child_score':comparison['child_score'],'reuse_statuses':[r.status for r in reuse_results],
                      'actual_skill_calls':calls,'capability_verified':report['capability_verified']}),flush=True)


if __name__=='__main__': main()
