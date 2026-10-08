"""One frozen local model dev task after native menu/checker repair; no retries."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import time

from core.computer_use.native_model import NativeChainProvider, NativeEvaluator, NATIVE_SOUL, write_json
from core.evolution.budget import BudgetConfig, BudgetTracker
from core.evolution.contracts import Candidate, RunSpec
from core.evolution.journal import Journal
from core.evolution.runner import EvolutionRunner
from scripts.experiments.native_model_pilot import (
    ROOT, SOURCE_FILES, LocalService, DeterministicLocalModel, local_broker, file_hash,
)

TEXT='Kage native menu dev.\nStatus: verified through TextEdit.\n'
TASK={'task_id':'native_menu_repair_dev1','document_name':'kage-menu-repair-dev1.txt',
      'instruction':'In the dedicated TextEdit document replace the entire text with the decoded JSON string below. '
                    'Preserve its final newline. Activate the observed window only if application_active is false, '
                    'then use the observed document menu and its Save command.\nExact JSON text:\n'+json.dumps(TEXT),
      'initial_files':{'kage-menu-repair-dev1.txt':'Kage native menu dev.\nStatus: pending.\n'},
      'expected':TEXT,'output_file':'kage-menu-repair-dev1.txt'}
UNICODE_TEXT='项目进度\n状态：已保存\n复核：AX + 磁盘\n'
TASKS={'dev1':TASK,'dev2':{
    **TASK,'task_id':'native_menu_unicode_dev2','document_name':'kage-menu-unicode-dev2.txt',
    'instruction':TASK['instruction'].split('Exact JSON text:\n')[0]+'Exact JSON text:\n'+json.dumps(UNICODE_TEXT,ensure_ascii=False),
    'initial_files':{'kage-menu-unicode-dev2.txt':'项目进度\n状态：待保存\n'},
    'expected':UNICODE_TEXT,'output_file':'kage-menu-unicode-dev2.txt'}}
PROTOCOL={'version':'native-menu-model-dev-v1','tasks':1,'attempts_per_task':1,'max_loop_steps':8,
          'max_requests':10,'max_agent_actions':16,'max_checker_cleanup_native_actions':4,
          'max_total_native_actions':20,'max_app_open_requests':2,'cooperative_timeout_s':480,'cloud_calls':0,
          'temperature':0,'max_output_per_request':300,'split':'dev','purpose':'post-repair integration, not holdout'}
SOURCES=sorted(set(SOURCE_FILES+['scripts/experiments/native_menu_model_dev.py',
                               'core/computer_use/native_model.py','core/computer_use/native_ax.py',
                               'core/computer_use/browser.py','tests/test_native_menu_model_dev.py']))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--port',type=int,default=18082)
    parser.add_argument('--task',choices=tuple(TASKS),default='dev1')
    args=parser.parse_args()
    task=TASKS[args.task]
    dirty=subprocess.check_output(['git','status','--porcelain','--',*SOURCES],cwd=ROOT,text=True)
    if dirty:parser.error('commit source before the frozen dev attempt')
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    with LocalService(args.port,output) as service:
        frozen={'protocol':PROTOCOL,'task':task,'selected_task':args.task,
                'task_sha256':hashlib.sha256(json.dumps(task,sort_keys=True,ensure_ascii=False).encode('utf-8')).hexdigest(),
                'protocol_sha256':hashlib.sha256(json.dumps(PROTOCOL,sort_keys=True).encode()).hexdigest(),
                'prompt':NATIVE_SOUL,'runtime':service.runtime,
                'frozen_at_utc':datetime.now(timezone.utc).isoformat(),
                'git_revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                'source_hashes':{name:file_hash(ROOT/name) for name in SOURCES},
                'token_semantics':'conservative reservation; usage reported, no strict token claim',
                'timing_semantics':'cooperative inline; synchronous HTTP/AX can overrun deadline'}
        write_json(output/'freeze.json',frozen)
        budget=BudgetTracker(BudgetConfig(max_api_calls=10,max_input_tokens_total=1_000_000,
                                         max_output_tokens_total=3000,input_cost_per_million=0,
                                         output_cost_per_million=0),output/'budget.sqlite')
        journal=Journal(output/'journal.sqlite')
        provider=NativeChainProvider(DeterministicLocalModel(local_broker(args.port).background_provider),
                                     task,model_label='agents-a1-4b',max_model_calls=10)
        runner=EvolutionRunner(journal,budget,output/'workspaces',provider,step_isolation='inline')
        runner.evaluator=NativeEvaluator()
        candidate=Candidate('native-menu-model-dev-v1',(),'workflow',str(ROOT),
                            hashlib.sha256(json.dumps(frozen['source_hashes'],sort_keys=True).encode()).hexdigest())
        write_json(output/'submission.json',{'task_id':task['task_id'],'attempt':1,'protocol':PROTOCOL})
        started=time.monotonic()
        result=runner.run(candidate,task,RunSpec(task['task_id'],candidate.candidate_id,task['task_id'],
                                               max_steps=1,timeout_s=480))
        row={**asdict(result),'elapsed_s':time.monotonic()-started}
        write_json(output/'result.json',row);write_json(output/'budget-final.json',budget.to_dict())
        print(json.dumps({k:row[k] for k in ('status','score','usage','elapsed_s')},ensure_ascii=False),flush=True)
    return 0 if result.score==1 else 1


if __name__=='__main__':raise SystemExit(main())
