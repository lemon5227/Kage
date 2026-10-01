"""E3: real cloud source patch, identical skills/prompts, paired local checks."""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import shutil
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from core.evolution.agent_provider import KageChainProvider
from core.evolution.artifacts import atomic_json
from core.evolution.budget import BudgetConfig, BudgetTracker
from core.evolution.bundle import RecoveryPolicy
from core.evolution.contracts import Candidate, RunSpec
from core.evolution.journal import Journal
from core.evolution.mutator import bundle_digest
from core.evolution.promotion import Promoter
from core.evolution.recovery_mutator import RecoveryMutator
from core.evolution.runner import EvolutionRunner
from core.evolution.sandbox import DockerSkillRunner
from core.evolution.skills import SkillCatalog
from task_suite import RecordedLocalProvider


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate-record', type=Path, required=True)
    parser.add_argument('--teacher-config', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--port', type=int, default=18082)
    args = parser.parse_args()
    dev_path = ROOT/'eval/computer-use/recovery-dev-v1.json'
    test_path = ROOT/'eval/computer-use/recovery-transfer-v1.json'
    dev = json.loads(dev_path.read_text())['tasks'][0]
    test = json.loads(test_path.read_text())['tasks'][0]
    data = json.loads(args.candidate_record.read_text())['candidate']; data['parent_ids']=tuple(data['parent_ids'])
    skill = Candidate(**data)
    if bundle_digest(Path(skill.bundle_path)) != skill.digest:
        raise ValueError('frozen skill bundle changed')
    cloud = json.loads(args.teacher_config.read_text())['model']['cloud_api']
    if cloud['model_name'] != 'deepseek-flash' or cloud['base_url'].rstrip('/') != 'https://api.deepseek.com':
        raise ValueError('official Flash configuration required')
    docker = DockerSkillRunner(timeout_s=10)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    parent_path = args.output_dir/'parent'
    shutil.copytree(skill.bundle_path, parent_path)
    source = (ROOT/'core/evolvable/recovery.py').read_bytes()
    (parent_path/'recovery.py').write_bytes(source)
    manifest = json.loads((parent_path/'manifest.json').read_text())
    manifest['modules']={'recovery':{'entrypoint':'recovery.py:recover','digest':hashlib.sha256(source).hexdigest()}}
    atomic_json(parent_path/'manifest.json', manifest)
    parent = Candidate('recovery-stop', (), 'recovery', str(parent_path.resolve()), bundle_digest(parent_path))
    journal = Journal(args.output_dir/'journal.sqlite')
    local_budget = BudgetTracker(BudgetConfig(max_api_calls=48,input_cost_per_million=0,output_cost_per_million=0),args.output_dir/'local-budget.sqlite')
    cloud_budget = BudgetTracker(BudgetConfig(max_api_calls=3,max_input_tokens_total=36000,max_output_tokens_total=9000,max_cost_usd=.03,input_cost_per_million=.3,output_cost_per_million=1.2),args.output_dir/'optimizer-budget.sqlite')
    atomic_json(args.output_dir/'config.json',{'skill_bundle_digest':skill.digest,'dev_sha256':hashlib.sha256(dev_path.read_bytes()).hexdigest(),'test_sha256':hashlib.sha256(test_path.read_bytes()).hexdigest(),
        'local_max_model_calls':6,'local_max_steps':5,'local_output_tokens':300,'skill_context_mode':'search','cloud_off_during_evaluation':True,'optimizer_calls_max':3,'optimizer_output_max':3000,'optimizer_input_bytes_max':12000,'optimizer_cost_cap_usd':.03,'docker_image_id':docker.image_id})
    def provider_factory(candidate):
        catalog = SkillCatalog.from_bundle(Path(candidate.bundle_path), runner=docker)
        policy = RecoveryPolicy.from_bundle(Path(candidate.bundle_path),runner=docker,skill_catalog=catalog)
        model = RecordedLocalProvider(args.output_dir/f'student-{candidate.digest[:16]}.jsonl',api_key='local',model_name='agents-a1-4b',base_url=f'http://127.0.0.1:{args.port}/v1',timeout_sec=120)
        return KageChainProvider(model,model_label='agents-a1-4b',max_model_calls=6,skill_catalog=catalog,skill_context_mode='search',recovery_policy=policy)
    # Record an actual dev failure before any optimizer call; no test feedback used.
    runner = EvolutionRunner(journal,local_budget,args.output_dir/'baseline',provider_factory(parent),step_isolation='fork')
    baseline = runner.run(parent,dev,RunSpec('baseline',parent.candidate_id,dev['task_id'],max_steps=1,timeout_s=150))
    atomic_json(args.output_dir/'baseline-result.json',asdict(baseline))
    if baseline.status != 'failed':
        atomic_json(args.output_dir/'report.json',{'baseline':asdict(baseline),'capability_verified':False,'stop_reason':'no_valid_dev_failure'})
        print(json.dumps({'stop_reason':'no_valid_dev_failure','baseline':baseline.status}),flush=True)
        return
    trace = [json.loads(line) for line in Path(baseline.trace_path).read_text().splitlines()]
    feedback = {'task_id':dev['task_id'],'instruction':dev['instruction'],'failure_reason':'The local model read code then ended without fixing it. Existing matching skill was not used; default recovery stopped. Change recovery source to select an appropriate tool from actual observed state. No hidden evaluator data is provided.',
                'trace':[row for row in trace if row.get('event_type') in {'action','observation'}]}
    optimizer = RecordedLocalProvider(args.output_dir/'optimizer-model.jsonl',api_key=cloud['api_key'],model_name=cloud['model_name'],base_url=cloud['base_url'],thinking=False,output_limit=3000,timeout_sec=60)
    child = RecoveryMutator(optimizer,cloud_budget,journal,args.output_dir/'mutation').propose(parent,feedback)
    parent_provider,child_provider=provider_factory(parent),provider_factory(child)
    if parent_provider.metadata()['experiment_prompt_sha256'] != child_provider.metadata()['experiment_prompt_sha256'] or parent_provider.skill_catalog.digests != child_provider.skill_catalog.digests:
        raise ValueError('paired prompt or skill catalog changed')
    # E1 promotes on dev only. Its active file is provisional inside evaluation/;
    # final experiment activation below additionally requires the fixed new test.
    promoter = Promoter(journal,local_budget,provider_factory,args.output_dir/'evaluation',timeout_s=150,step_isolation='fork')
    comparison = promoter.compare(parent,child,[dev])
    result = promoter.evaluate(child,test)
    rows=[json.loads(line) for line in Path(result.trace_path).read_text().splitlines()]
    skill_calls=[r for r in rows if r.get('action',{}).get('name')=='skill_call' and r.get('observation',{}).get('actor')=='recovery_policy']
    recovery_trace=[r for chain in result.metadata.get('chain',[]) for r in chain.get('recovery_trace',[])]
    verified = comparison['promoted'] and result.status=='passed' and len(skill_calls)>0 and len(recovery_trace)>0
    if verified:
        atomic_json(args.output_dir/'active.json',{'candidate':asdict(child),'dev_comparison':comparison['reason'],'test_run_id':result.run_id})
    report={'baseline':asdict(baseline),'comparison':comparison,'new_variant':asdict(result),'variant_recovery_skill_calls':len(skill_calls),'recovery_trace':recovery_trace,
            'capability_verified':verified,'activation_scope':'experiment only','same_prompt_sha256':parent_provider.metadata()['experiment_prompt_sha256'],
            'unchanged_skill_digests':parent_provider.skill_catalog.digests,'parent':asdict(parent),'child':asdict(child),'optimizer_usage':cloud_budget.usage_by_type,
            'optimizer_estimated_cost_usd':cloud_budget.total_cost_usd,'docker_image_id':docker.image_id,'cloud_off_during_evaluation':True}
    atomic_json(args.output_dir/'report.json',report)
    print(json.dumps({'promoted':comparison['promoted'],'parent_score':comparison['parent_score'],'child_score':comparison['child_score'],'variant_status':result.status,'recovery_skill_calls':len(skill_calls),'capability_verified':verified}),flush=True)


if __name__=='__main__':
    main()
