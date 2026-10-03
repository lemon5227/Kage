"""Fixed dev matrix: raw cloud actions, search, preview, or a retrieval repair probe."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from core.computer_use.experiment import BrowserCloudProvider
from core.computer_use.skills import BrowserSkillCatalog
from core.computer_use.task_environment import atomic_json
from core.evolution.budget import BudgetConfig,BudgetTracker
from core.evolution.contracts import Candidate,RunSpec
from core.evolution.journal import Journal
from core.evolution.mutator import bundle_digest
from core.evolution.runner import EvolutionRunner
from scripts.experiments.browser_state_diagnosis import development_tasks,sha
from scripts.experiments.browser_transfer import ReservedTeacher
from scripts.experiments.task_suite import RecordedLocalProvider

ARMS=('raw','search','preview')


def summarize(rows,selected_arms=ARMS,protocol='c21-r2-discovery-dev-v1'):
    arms={}
    for arm in selected_arms:
        group=[r for r in rows if r['arm']==arm]
        calls=[c for r in group for c in r['chain'].get('call_usage',[])]
        arms[arm]={'expected_runs':3,'recorded_runs':len(group),'passed':sum(r['status']=='passed' for r in group),
            'model_calls':len(calls),'skill_search':sum(r['skill_search'] for r in group),
            'skill_call':sum(r['skill_call'] for r in group),
            'passed_with_skill_call':sum(r['status']=='passed' and r['skill_call']>0 for r in group),
            'browser_primitives':sum(r['chain'].get('browser_primitives',0) or 0 for r in group),
            'reported_tokens':{k:sum(c.get(k,0) for c in calls) for k in ('input_tokens','output_tokens')},
            'unknown_usage_calls':sum(not all(k in c for k in ('input_tokens','output_tokens')) for c in calls),
            'seconds':round(sum(r['seconds'] for r in group),3)}
    return {'protocol':protocol,'complete':len(rows)==3*len(selected_arms),'arms':arms}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cloud-config',type=Path,required=True)
    parser.add_argument('--skill-bundle',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--study',choices=['discovery','retrieval-repair'],default='discovery')
    args=parser.parse_args()
    selected_arms=('search',) if args.study=='retrieval-repair' else ARMS
    protocol='c21-r2-retrieval-repair-dev-v1' if args.study=='retrieval-repair' else 'c21-r2-discovery-dev-v1'
    expected_runs=3*len(selected_arms)
    call_cap=6*expected_runs
    cloud=json.loads(args.cloud_config.read_text())['model']['cloud_api']
    if cloud.get('model_name')!='deepseek-flash' or cloud.get('base_url','').rstrip('/')!='https://api.deepseek.com' or not cloud.get('api_key'):
        parser.error('requires configured official DeepSeek Flash')
    catalog=BrowserSkillCatalog.from_bundle(args.skill_bundle)
    tasks=development_tasks()
    candidate=Candidate('existing_browser_candidate',(),'workflow',str(args.skill_bundle.resolve()),bundle_digest(args.skill_bundle))
    if candidate.digest!='9400d42f5119acfff14f1c6acf153f66efe16323e66b9d8f32fe6904ab63ffba':
        parser.error('R2 requires the unchanged, unpromoted B2.1c candidate')
    sources=['core/computer_use/'+s for s in ('browser.py','experiment.py','context_pack.py','skills.py','task_environment.py')]
    sources+=['core/'+s for s in ('model_provider.py','agentic_loop.py','prompt_builder.py','tool_executor.py','tool_registry.py')]
    sources+=['core/evolution/'+s for s in ('agent_provider.py','runner.py','budget.py','mutator.py')]
    sources+=['scripts/experiments/'+s for s in ('browser_state_diagnosis.py','browser_skill_diagnosis.py','browser_transfer.py','task_suite.py')]
    prompts={arm:BrowserCloudProvider(None,tasks[0],browser_skill_bundle=args.skill_bundle if arm!='raw' else None,
        skill_context_mode='preview' if arm=='preview' else 'search').cache_identity()['experiment_prompt_sha256'] for arm in selected_arms}
    config={'protocol':protocol,'tasks':tasks,'split':'dev-only','expected_runs':expected_runs,'repeats':1,'arms':list(selected_arms),
        'executor':'cloud_direct','model':cloud['model_name'],'endpoint':cloud['base_url'],'thinking':False,'temperature':0,
        'observation_format':'compact-v2','max_calls_per_run':6,'max_loop_steps':5,'max_primitives':16,
        'timeout_s':480,'request_timeout_s':60,'max_request_input_bytes':12000,'max_output_tokens':1024,
        'context_pack':True,'external_completion':True,'candidate':asdict(candidate),'skill_digests':catalog.digests,
        'candidate_previously_promoted':False,'generation_calls':0,'promotion_in_this_experiment':False,
        'source_hashes':{s:sha(ROOT/s) for s in sources},'prompt_hashes':prompts,
        'git_revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'max_assumed_cost_usd':.10*len(selected_arms),'conservative_cost_ceiling_usd':call_cap*(12000*.3+1024*1.2)/1000000,
        'assumed_rates_per_million':{'input':.3,'output':1.2},'order':'task/rotating-arm-order'}
    args.output_dir.mkdir(parents=True,exist_ok=True)
    config_path=args.output_dir/'config.json'
    if config_path.exists():
        if json.loads(config_path.read_text())!=config:parser.error('resume configuration changed')
    else:atomic_json(config_path,config)
    cloud_config=BudgetConfig(max_api_calls=call_cap,max_input_tokens_total=call_cap*12000,max_output_tokens_total=call_cap*1024,
        max_cost_usd=config['max_assumed_cost_usd'],input_cost_per_million=.3,output_cost_per_million=1.2)
    budget=BudgetTracker(BudgetConfig(max_api_calls=call_cap,max_input_tokens_total=call_cap*12000,max_output_tokens_total=call_cap*1024,
        input_cost_per_million=0,output_cost_per_million=0),args.output_dir/'chain-budget.sqlite')
    journal=Journal(args.output_dir/'journal.sqlite')
    path=args.output_dir/'results.json'
    rows=json.loads(path.read_text()) if path.exists() else []
    expected={t['task_id']+'--'+a for t in tasks for a in selected_arms};keys=[r['key'] for r in rows]
    if len(set(keys))!=len(keys) or set(keys)-expected:parser.error('unexpected or duplicate result keys')
    for index,task in enumerate(tasks):
        shift=index%len(selected_arms)
        for arm in selected_arms[shift:]+selected_arms[:shift]:
            key=task['task_id']+'--'+arm
            if key in keys:continue
            remote=RecordedLocalProvider(args.output_dir/(key+'-cloud.jsonl'),api_key=cloud['api_key'],
                model_name=cloud['model_name'],base_url=cloud['base_url'],timeout_sec=60,thinking=False,output_limit=1024)
            model=ReservedTeacher(remote,cloud_config,args.output_dir/'cloud-budget.sqlite',key)
            provider=BrowserCloudProvider(model,task,model_label=cloud['model_name'],provider_mode='cloud',max_model_calls=6,
                external_completion=True,observation_format='compact-v2',browser_skill_bundle=args.skill_bundle if arm!='raw' else None,
                skill_context_mode='preview' if arm=='preview' else 'search')
            runner=EvolutionRunner(journal,budget,args.output_dir/'runs',provider,step_isolation='fork')
            start=time.monotonic()
            result=runner.run(candidate,task,RunSpec(key,candidate.candidate_id,task['task_id'],max_steps=1,timeout_s=480))
            ws=Path(result.final_state_path)
            entries=[json.loads(line) for line in (ws/'actor-tools.jsonl').read_text().splitlines()] if (ws/'actor-tools.jsonl').exists() else []
            names=('actor-tools.jsonl','browser.jsonl','browser-check.json','browser-outcome.json','initial-observation.json','loop-result.json','cloud-context-pack.jsonl','final.png')
            chain=(result.metadata.get('chain') or [{}])[-1]
            row={**asdict(result),'key':key,'task_id':task['task_id'],'arm':arm,'chain':chain,
                'seconds':round(time.monotonic()-start,3),'skill_search':sum(e['name']=='skill_search' for e in entries),
                'skill_call':sum(e['name']=='skill_call' for e in entries),
                'evidence_hashes':{name:sha(ws/name) for name in names if (ws/name).exists()}}
            rows.append(row);keys.append(key);atomic_json(path,rows)
            report=summarize(rows,selected_arms,protocol);report['cloud_assumed_ledger']=BudgetTracker(cloud_config,args.output_dir/'cloud-budget.sqlite').to_dict()
            atomic_json(args.output_dir/'report.json',report)
            print(json.dumps({k:row[k] for k in ('key','status','score','skill_search','skill_call','seconds')},ensure_ascii=False),flush=True)
    print(json.dumps(summarize(rows,selected_arms,protocol),ensure_ascii=False),flush=True)


if __name__=='__main__':main()
