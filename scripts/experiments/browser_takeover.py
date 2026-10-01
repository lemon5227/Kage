"""Frozen three-attempt dev-only same-page teacher pilot; private key stays private."""
import argparse
from dataclasses import asdict
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from core.computer_use.teacher_takeover import BrowserTeacherTakeoverProvider
from core.evolution.budget import BudgetConfig,BudgetTracker
from core.evolution.contracts import Candidate,RunSpec
from core.evolution.journal import Journal
from core.evolution.runner import EvolutionRunner
from scripts.experiments.task_suite import RecordedLocalProvider
from scripts.experiments.browser_suite import file_hash

INPUT_RATE=.3
OUTPUT_RATE=1.2

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--teacher-config',type=Path,required=True)
    parser.add_argument('--port',type=int,default=18082)
    parser.add_argument('--external-completion',action='store_true',help='Stop after independently verified saved output; bounded save settlement')
    args=parser.parse_args()
    cloud=json.loads(args.teacher_config.read_text())['model']['cloud_api']
    if cloud.get('model_name')!='deepseek-flash' or cloud.get('base_url','').rstrip('/')!='https://api.deepseek.com' or not cloud.get('api_key'):
        parser.error('requires configured official DeepSeek Flash endpoint and credential')
    suite_path=ROOT/'eval/computer-use/browser-learning-v2.json'
    suite=json.loads(suite_path.read_text());protocol=suite['protocol']
    task=next(t for t in suite['tasks'] if t['task_id']=='preferences_dev')
    args.output_dir.mkdir(parents=True,exist_ok=False)
    files=['core/computer_use/browser.py','core/computer_use/task_environment.py','core/computer_use/experiment.py',
           'core/computer_use/teacher_takeover.py','core/agentic_loop.py','core/model_provider.py',
           'core/prompt_builder.py','core/tool_executor.py','core/evolution/runner.py','core/evolution/agent_provider.py',
           'scripts/experiments/task_suite.py','scripts/experiments/browser_takeover.py']
    hashes={f:file_hash(ROOT/f) for f in files}
    ceiling=protocol['max_teacher_calls']*(protocol['teacher_input_bytes']*INPUT_RATE+protocol['teacher_output_tokens']*OUTPUT_RATE)/1_000_000
    config={'protocol':protocol,'external_completion':args.external_completion,'task_id':task['task_id'],'teacher':{'model':'deepseek-flash','thinking':False,
            'cloud_ceiling_per_attempt_usd':ceiling,'cloud_ceiling_total_usd':ceiling*protocol['repeats'],
            'input_rate_assumed_per_million':INPUT_RATE,'output_rate_assumed_per_million':OUTPUT_RATE},
            'student':'agents-a1-4b','source_hashes':hashes,'suite_sha256':file_hash(suite_path),
            'model_sha256':file_hash(Path.home()/'.kage/models/agents-a1-4b/Agents-A1-4B-Q4_K_M.gguf'),
            'started_at':datetime.now(timezone.utc).isoformat(),
            'git_revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'budget_semantics':'global conservative cloud rates include local tokens; actual paid estimate uses only teacher usage',
            'timing':'seconds is monotonic (macOS excludes sleep); wall_seconds includes sleep/clock adjustments'}
    (args.output_dir/'config.json').write_text(json.dumps(config,ensure_ascii=False,indent=2))
    journal=Journal(args.output_dir/'journal.sqlite')
    budget=BudgetTracker(BudgetConfig(max_api_calls=36,max_input_tokens_total=360000,max_output_tokens_total=24432,
                         max_cost_usd=.16,input_cost_per_million=INPUT_RATE,output_cost_per_million=OUTPUT_RATE),args.output_dir/'budget.sqlite')
    candidate=Candidate('browser-takeover',(),'workflow',str(ROOT),hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest())
    rows=[]
    for repeat in range(protocol['repeats']):
        rid=f'preferences_dev-{repeat}'
        local=RecordedLocalProvider(args.output_dir/(rid+'-student.jsonl'),api_key='local',model_name='agents-a1-4b',base_url=f'http://127.0.0.1:{args.port}/v1',timeout_sec=protocol['http_timeout_s'])
        teacher=RecordedLocalProvider(args.output_dir/(rid+'-teacher.jsonl'),api_key=cloud['api_key'],model_name=cloud['model_name'],base_url=cloud['base_url'],timeout_sec=protocol['http_timeout_s'],thinking=False,output_limit=protocol['teacher_output_tokens'])
        chain=BrowserTeacherTakeoverProvider(local,teacher,task,model_label='agents-a1-4b',max_model_calls=protocol['max_model_calls'],max_teacher_calls=protocol['max_teacher_calls'],teacher_output_tokens=protocol['teacher_output_tokens'],external_completion=args.external_completion)
        runner=EvolutionRunner(journal,budget,args.output_dir/'workspaces',chain)
        start=time.monotonic();wall_start=time.time()
        result=runner.run(candidate,task,RunSpec(rid,candidate.candidate_id,task['task_id'],max_steps=1,timeout_s=protocol['timeout_s']))
        row={'repeat':repeat,'seconds':round(time.monotonic()-start,3),'wall_seconds':round(time.time()-wall_start,3),
             'started_at':datetime.fromtimestamp(wall_start,timezone.utc).isoformat(),'finished_at':datetime.now(timezone.utc).isoformat(),**asdict(result)}
        chains=row['metadata'].get('chain') or [{}]
        takeover=chains[-1].get('takeover',{})
        usage=takeover.get('teacher_usage',{})
        row['teacher_cost_estimate_usd']=(usage['input_tokens']*INPUT_RATE+usage['output_tokens']*OUTPUT_RATE)/1_000_000 if 'input_tokens' in usage and 'output_tokens' in usage else None
        row['teacher_cost_ceiling_usd']=ceiling
        rows.append(row)
        (args.output_dir/'results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
        print(json.dumps({k:row[k] for k in ['repeat','status','score','seconds','wall_seconds','teacher_cost_estimate_usd']}|{'takeover':takeover.get('triggered'),'student_check_passed':takeover.get('student_check_passed'),'student_usage':takeover.get('student_usage'),'teacher_usage':usage},ensure_ascii=False),flush=True)
    print(json.dumps({'passed':sum(r['status']=='passed' for r in rows),'total':len(rows)}),flush=True)

if __name__=='__main__':main()
