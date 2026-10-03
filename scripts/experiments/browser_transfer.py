"""Frozen five-arm browser transfer pilot. No optimization or test-driven retuning."""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from core.computer_use.experiment import BrowserChainProvider
from core.computer_use.episodes import generation_feedback
from core.computer_use.teacher_takeover import BrowserTeacherTakeoverProvider
from core.computer_use.transfer import ARMS,load_plan,result_key,BrowserRetryProvider,BrowserTrajectoryProvider
from core.computer_use.skills import BrowserSkillCatalog
from core.computer_use.task_environment import atomic_json
from core.evolution.archive import ExperienceArchive
from core.evolution.budget import BudgetConfig,BudgetTracker
from core.evolution.contracts import Candidate,RunSpec
from core.evolution.journal import Journal
from core.evolution.mutator import bundle_digest
from core.evolution.runner import EvolutionRunner
from core.model_provider import ModelProvider
from scripts.experiments.task_suite import RecordedLocalProvider

FROZEN_SHA='46c098fe99e972acca02c76b07584d8e0326c5a9b47ec89ebb07ea5366a4d6c1'


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class ReservedTeacher(ModelProvider):
    """Teacher-only nominal cost ledger, persisted even if its worker is killed."""
    def __init__(self,inner,config,path,run_id):
        self.inner,self.config,self.path,self.run_id=inner,config,path,run_id

    def generate(self,**kwargs):
        budget=BudgetTracker(self.config,self.path)
        reservation=budget.reserve(12000,1024,run_id=self.run_id)
        try:
            response=self.inner.generate(**kwargs)
        except BaseException:
            budget.settle(reservation,None)
            raise
        budget.settle(reservation,{**response.usage,'api_calls':1})
        return response


def summarize(plan,rows):
    arms={}
    for arm in ARMS:
        group=[r for r in rows if r['arm']==arm]
        info={'expected_runs':len(plan.task_ids)*plan.repeats,'recorded_runs':len(group),
              'passed':sum(r['status']=='passed' for r in group),
              'statuses':{status:sum(r['status']==status for r in group) for status in sorted({r['status'] for r in group})},
              'actual_skill_calls':sum(r['actual_skill_calls'] for r in group),
              'student_tokens':{'input_tokens':0,'output_tokens':0},
              'teacher_tokens':{'input_tokens':0,'output_tokens':0},
              'unknown_usage_runs':0,'nominal_token_overrun_runs':0,'takeovers':0,'student_passed':0,
              'model_calls':0,'browser_primitives':0,
              'median_seconds':statistics.median(r['seconds'] for r in group) if group else None}
        for row in group:
            chain=(row.get('metadata',{}).get('chain') or [{}])[-1]
            takeover=chain.get('takeover',{})
            student=takeover.get('student_usage',row.get('usage',{}))
            teacher=takeover.get('teacher_usage',{'api_calls':0,'input_tokens':0,'output_tokens':0})
            info['takeovers']+=bool(takeover.get('triggered'))
            info['student_passed']+=bool(takeover.get('student_check_passed',row['status']=='passed'))
            info['model_calls']+=chain.get('model_calls',0)
            info['browser_primitives']+=((takeover.get('student_chain',{}).get('browser_primitives',0) or 0)
                +(takeover.get('teacher_chain',{}).get('browser_primitives',0) or 0)) if takeover else (chain.get('browser_primitives',0) or 0)
            unknown=False
            for label,usage in [('student',student),('teacher',teacher)]:
                if not all(key in usage for key in ('input_tokens','output_tokens')): unknown=True
                for key in ('input_tokens','output_tokens'): info[label+'_tokens'][key]+=usage.get(key,0)
            info['unknown_usage_runs']+=unknown
            info['nominal_token_overrun_runs']+=student.get('input_tokens',0)>48000 or student.get('output_tokens',0)>2000
        arms[arm]=info
    return {'expected_runs':plan.expected_runs,'recorded_runs':len(rows),
            'complete':len(rows)==plan.expected_runs,'arms':arms}


def verified_feedback(path):
    feedback=json.loads(path.read_text())
    manifest=json.loads((path.parent/'manifest.json').read_text())
    source=next(r for r in manifest['episodes'] if r.get('feedback_path') and Path(r['feedback_path']).resolve()==path.resolve())
    archive=ExperienceArchive(Journal(path.parent/'journal.sqlite'))
    episode=next(r for r in archive.retrieve(feedback['family'],limit=100) if r['episode_id']==source['episode_id'])
    if generation_feedback(episode)!=feedback: raise ValueError('dev feedback changed or evidence is no longer intact')
    return feedback


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite',type=Path,default=ROOT/'eval/computer-use/browser-transfer-v1.json')
    parser.add_argument('--learning-dir',type=Path,required=True)
    parser.add_argument('--feedback',type=Path,required=True)
    parser.add_argument('--teacher-config',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--port',type=int,default=18082)
    args=parser.parse_args()
    plan=load_plan(args.suite)
    learning=json.loads((args.learning_dir/'report.json').read_text())
    generation=json.loads((args.learning_dir/'config.json').read_text())
    if plan.suite_sha256!=FROZEN_SHA or generation['frozen_test_sha256']!=FROZEN_SHA:
        parser.error('test manifest differs from the pre-generation freeze')
    if sha(args.feedback)!=generation['feedback_sha256']: parser.error('wrong development demonstration')
    feedback=verified_feedback(args.feedback)
    child_data=learning['child'];child_data['parent_ids']=tuple(child_data['parent_ids'])
    child=Candidate(**child_data)
    if bundle_digest(child.bundle_path)!=child.digest: parser.error('generated candidate changed')
    BrowserSkillCatalog.from_bundle(child.bundle_path)
    parent_data=learning['parent'];parent_data['parent_ids']=tuple(parent_data['parent_ids'])
    parent=Candidate(**parent_data)
    if bundle_digest(parent.bundle_path)!=parent.digest: parser.error('empty baseline bundle changed')
    cloud=json.loads(args.teacher_config.read_text())['model']['cloud_api']
    if cloud.get('model_name')!='deepseek-flash' or cloud.get('base_url','').rstrip('/')!='https://api.deepseek.com' or not cloud.get('api_key'):
        parser.error('requires configured official DeepSeek Flash')
    model_path=Path.home()/'.kage/models/agents-a1-4b/Agents-A1-4B-Q4_K_M.gguf'
    if sha(model_path)!=generation['model_sha256']: parser.error('student model changed')
    sources=['core/computer_use/'+name for name in ('transfer.py','experiment.py','teacher_takeover.py','skills.py','browser.py','context_pack.py','task_environment.py')]
    sources+=['core/'+name for name in ('agentic_loop.py','prompt_builder.py','model_provider.py','tool_executor.py','tool_registry.py')]
    sources+=['core/evolution/'+name for name in ('agent_provider.py','runner.py','budget.py')]
    sources+=['scripts/experiments/browser_transfer.py','scripts/experiments/task_suite.py']
    config={'protocol':'c21-b22-preferences-five-arm-v1','suite_sha256':plan.suite_sha256,
            'source_hashes':{s:sha(ROOT/s) for s in sources},'candidate_digest':child.digest,
            'feedback_sha256':sha(args.feedback),'model_sha256':generation['model_sha256'],
            'git_revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'port':args.port,'expected_runs':plan.expected_runs,'arms':list(ARMS),
            'student':{'model':'agents-a1-4b','max_calls':6,'total_loop_steps':5,'output_cap':300,
                       'nominal_input_reservation':48000,'nominal_output_reservation':2000,'primitives':16},
            'teacher':{'model':'deepseek-flash','max_calls_per_run':6,'output_cap':1024,'input_bytes_cap':12000,
                       'max_assumed_cost_usd':.30,'input_rate_per_million':.3,'output_rate_per_million':1.2},
            'timeout_s':480,'step_isolation':'fork','external_completion':True,
            'retry_policy':'same-page-2-2-1-v1','order':'repeat/task/rotating-arm-order',
            'candidate_promoted_on_dev':learning['comparison']['promoted']}
    args.output_dir.mkdir(parents=True,exist_ok=True)
    config_path=args.output_dir/'config.json'
    if config_path.exists():
        if json.loads(config_path.read_text())!=config: parser.error('resume configuration changed')
    else: atomic_json(config_path,config)
    suite=json.loads(args.suite.read_text())
    journal=Journal(args.output_dir/'journal.sqlite')
    max_calls=plan.expected_runs*6+len(plan.task_ids)*plan.repeats*6
    budget=BudgetTracker(BudgetConfig(max_api_calls=max_calls,max_input_tokens_total=max_calls*12000,
        max_output_tokens_total=max_calls*2000,input_cost_per_million=0,output_cost_per_million=0),args.output_dir/'chain-budget.sqlite')
    teacher_config=BudgetConfig(max_api_calls=54,max_input_tokens_total=648000,max_output_tokens_total=55296,
        max_cost_usd=.30,input_cost_per_million=.3,output_cost_per_million=1.2)
    results_path=args.output_dir/'results.json'
    rows=json.loads(results_path.read_text()) if results_path.exists() else []
    expected_keys={result_key(t,a,r) for t in plan.task_ids for a in ARMS for r in range(plan.repeats)}
    keys=[row['key'] for row in rows]
    if len(set(keys))!=len(keys) or set(keys)-expected_keys: parser.error('duplicate or unexpected recorded result keys')
    for repeat in range(plan.repeats):
        for index,task in enumerate(suite['tasks']):
            shift=(repeat+index)%len(ARMS)
            for arm in ARMS[shift:]+ARMS[:shift]:
                key=result_key(task['task_id'],arm,repeat)
                if key in keys: continue  # all terminal failures count; never sample again for success.
                model=RecordedLocalProvider(args.output_dir/(key+'-student.jsonl'),api_key='local',model_name='agents-a1-4b',
                    base_url=f'http://127.0.0.1:{args.port}/v1',timeout_sec=120)
                kwargs={'model_label':'agents-a1-4b','max_model_calls':6,'external_completion':True}
                if arm=='cloud_takeover':
                    remote=RecordedLocalProvider(args.output_dir/(key+'-teacher.jsonl'),api_key=cloud['api_key'],
                        model_name=cloud['model_name'],base_url=cloud['base_url'],timeout_sec=60,thinking=False,output_limit=1024)
                    teacher=ReservedTeacher(remote,teacher_config,args.output_dir/'teacher-budget.sqlite',key)
                    provider=BrowserTeacherTakeoverProvider(model,teacher,task,max_teacher_calls=6,teacher_output_tokens=1024,
                        teacher_context_pack=True,**kwargs)
                elif arm=='dev_trajectory': provider=BrowserTrajectoryProvider(model,task,dev_feedback=feedback,**kwargs)
                elif arm=='learned_workflow': provider=BrowserChainProvider(model,task,browser_skill_bundle=child.bundle_path,**kwargs)
                elif arm=='local_retries': provider=BrowserRetryProvider(model,task,**kwargs)
                else: provider=BrowserChainProvider(model,task,**kwargs)
                runner=EvolutionRunner(journal,budget,args.output_dir/'runs',provider,step_isolation='fork')
                candidate=child if arm=='learned_workflow' else parent
                start=time.monotonic()
                result=runner.run(candidate,task,RunSpec(key,candidate.candidate_id,task['task_id'],max_steps=1,timeout_s=480))
                workspace=Path(result.final_state_path)
                def evidence(name):
                    path=workspace/name
                    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []
                actor_tools=evidence('actor-tools.jsonl');browser_events=evidence('browser.jsonl')
                row={**asdict(result),'key':key,'task_id':task['task_id'],'arm':arm,'repeat':repeat,
                     'seconds':round(time.monotonic()-start,3),'actual_skill_calls':sum(r['name']=='skill_call' for r in actor_tools),
                     'observation_snapshots':sum(r.get('phase')=='observe' for r in browser_events),
                     'explicit_observe_calls':sum(r['name']=='browser_observe' for r in actor_tools),
                     'evidence_hashes':{name:sha(workspace/name) for name in ('actor-tools.jsonl','browser.jsonl','browser-outcome.json','browser-check.json') if (workspace/name).exists()}}
                rows.append(row);keys.append(key)
                atomic_json(results_path,rows)
                report=summarize(plan,rows)
                report['teacher_assumed_ledger']=BudgetTracker(teacher_config,args.output_dir/'teacher-budget.sqlite').to_dict()
                atomic_json(args.output_dir/'report.json',report)
                print(json.dumps({k:row[k] for k in ('key','status','score','seconds','actual_skill_calls')},ensure_ascii=False),flush=True)
    print(json.dumps(summarize(plan,rows),ensure_ascii=False),flush=True)


if __name__=='__main__': main()
