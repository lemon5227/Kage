"""Frozen browser suite through the original hard-deadline runner and evaluator."""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from core.computer_use.experiment import BrowserChainProvider
from core.agentic_loop import AgenticLoop
from core.evolution.budget import BudgetConfig,BudgetTracker
from core.evolution.contracts import Candidate,RunSpec
from core.evolution.journal import Journal
from core.evolution.runner import EvolutionRunner
from scripts.experiments.task_suite import RecordedLocalProvider

def file_hash(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''): digest.update(chunk)
    return digest.hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite',type=Path,default=ROOT/'eval/computer-use/browser-v1.json')
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--port',type=int,default=18082)
    parser.add_argument('--model-path',type=Path,default=Path.home()/'.kage/models/agents-a1-4b/Agents-A1-4B-Q4_K_M.gguf')
    parser.add_argument('--task')
    args=parser.parse_args()
    suite=json.loads(args.suite.read_text());protocol=suite['protocol']
    if protocol['repeats']!=1 or protocol['max_loop_steps']!=AgenticLoop.MAX_STEPS or protocol['cloud']:
        parser.error('this baseline implements one repeat, the frozen AgenticLoop step cap, and no cloud')
    tasks=[t for t in suite['tasks'] if not args.task or t['task_id']==args.task]
    if not tasks: parser.error('no matching browser task')
    args.output_dir.mkdir(parents=True,exist_ok=False)
    sources=['core/computer_use/browser.py','core/computer_use/experiment.py','core/computer_use/task_environment.py',
             'core/evolution/runner.py','core/evolution/agent_provider.py','core/agentic_loop.py',
             'core/prompt_builder.py','scripts/experiments/browser_suite.py','scripts/experiments/task_suite.py']
    hashes={f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in sources}
    config={'model':'agents-a1-4b','cloud':False,'port':args.port,'protocol':protocol,
            'suite_sha256':hashlib.sha256(args.suite.read_bytes()).hexdigest(),'source_hashes':hashes,
            'task_ids':[t['task_id'] for t in tasks],'git_revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'server_settings':{'context':8192,'parallel':1,'gpu_layers':99,'flash_attention':'auto','kv_cache':'q8_0','reasoning':'off'},
            'client_settings':{'temperature':0,'http_timeout_s':120,'output_tokens':'original AgenticLoop dynamic limits; recorded per request'},
            'model_path':str(args.model_path.resolve()),'model_sha256':file_hash(args.model_path),
            'model_hash_provenance':'streamed SHA256 of the local GGUF before inference; server launch log retained separately'}
    (args.output_dir/'config.json').write_text(json.dumps(config,ensure_ascii=False,indent=2))
    cap=len(tasks)*protocol['max_model_calls']
    journal=Journal(args.output_dir/'journal.sqlite')
    budget=BudgetTracker(BudgetConfig(max_api_calls=cap,max_input_tokens_total=cap*8000,
                         max_output_tokens_total=cap*400),args.output_dir/'budget.sqlite')
    candidate=Candidate('browser-baseline',(),'workflow',str(ROOT),hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest())
    results=[]
    for task in tasks:
        model=RecordedLocalProvider(args.output_dir/f'{task["task_id"]}-model.jsonl',api_key='local',model_name='agents-a1-4b',
                                    base_url=f'http://127.0.0.1:{args.port}/v1',timeout_sec=120)
        provider=BrowserChainProvider(model,task,model_label='agents-a1-4b',max_model_calls=protocol['max_model_calls'])
        runner=EvolutionRunner(journal,budget,args.output_dir/'workspaces',provider)
        start=time.monotonic()
        result=runner.run(candidate,task,RunSpec(task['task_id'],candidate.candidate_id,task['task_id'],max_steps=1,timeout_s=protocol['timeout_s']))
        row={'task':task['task_id'],'family':task['family'],'split':task['split'],'seconds':round(time.monotonic()-start,3),**asdict(result)}
        results.append(row)
        (args.output_dir/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
        print(json.dumps({k:row[k] for k in ['task','status','score','seconds','usage']}|{'completion':row['metadata'].get('completion')},ensure_ascii=False),flush=True)
    print(json.dumps({'passed':sum(r['status']=='passed' for r in results),'total':len(results)}),flush=True)


if __name__=='__main__':main()
