"""Frozen two-task local-only native model pilot; one attempt per task.

python -m scripts.experiments.native_model_pilot --output-dir artifacts/native-model/controlled1
Source must be committed before running. Never overwrites an existing experiment.
"""
import argparse
from dataclasses import asdict
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import time
import urllib.request

from core.computer_use.native_model import NativeChainProvider,NativeEvaluator,NATIVE_SOUL,write_json
from core.evolution.budget import BudgetConfig,BudgetTracker
from core.evolution.contracts import Candidate,RunSpec
from core.evolution.journal import Journal
from core.evolution.runner import EvolutionRunner
from core.model_broker import ModelBroker

ROOT=Path(__file__).resolve().parents[2]
MODEL=Path.home()/'.kage/models/agents-a1-4b/Agents-A1-4B-Q4_K_M.gguf'
SERVER=Path('/opt/homebrew/bin/llama-server')
PROTOCOL={'version':'native-controlled-v1','attempts_per_task':1,'max_loop_steps':8,
          'max_requests_per_task':10,'max_actions_per_task':16,'timeout_s_per_task':480,
          'max_requests_total':20,'cloud_calls':0,'temperature':0}
TASKS=[
    {'task_id':'native_status','document_name':'kage-controlled-native-status.txt',
     'instruction':'In the dedicated TextEdit document, replace the entire text with exactly:\nKage native model task.\nStatus: reviewed and saved.\n\nSave through TextEdit using its document Save menu command.',
     'initial_files':{'kage-controlled-native-status.txt':'Kage native model task.\nStatus: pending.\n'},
     'expected':'Kage native model task.\nStatus: reviewed and saved.\n','output_file':'kage-controlled-native-status.txt'},
    {'task_id':'native_agenda','document_name':'kage-controlled-native-agenda.txt',
     'instruction':'In the dedicated TextEdit document, replace the entire text with exactly:\nAgenda\n1. Inspect the native interface\n2. Save the completed document\n\nSave through TextEdit using its document Save menu command.',
     'initial_files':{'kage-controlled-native-agenda.txt':'Agenda\n- draft item\n'},
     'expected':'Agenda\n1. Inspect the native interface\n2. Save the completed document\n','output_file':'kage-controlled-native-agenda.txt'},
]
SOURCE_FILES=['core/computer_use/native_model.py','core/computer_use/native_ax.py','core/agentic_loop.py',
              'core/prompt_builder.py','core/tool_executor.py','core/tool_registry.py','core/model_provider.py',
              'core/model_broker.py','core/evolution/agent_provider.py','core/evolution/runner.py',
              'core/evolution/budget.py','core/evolution/journal.py','scripts/experiments/native_model_pilot.py']


def file_hash(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def local_broker(port):
    # Construct only a fresh local config; never read private/cloud settings.
    return ModelBroker({'model':{'local_runtime':{'host':'127.0.0.1','port':port,'model_name':'agents-a1-4b','timeout_sec':120},
                                'hybrid':{'enabled':False}}})


def freeze_manifest(output,runtime):
    manifest={'protocol':PROTOCOL,'tasks':TASKS,'prompt':NATIVE_SOUL,
              'prompt_sha256':hashlib.sha256(NATIVE_SOUL.encode()).hexdigest(),
              'source_hashes':{f:file_hash(ROOT/f) for f in SOURCE_FILES},'runtime':runtime,
              'git_revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
              'frozen_at':datetime.now(timezone.utc).isoformat(),
              'timing_semantics':'cooperative inline execution; synchronous AX/HTTP calls may overrun 480 seconds',
              'token_semantics':'usage recorded, conservative kernel reservations; no strict token cap claim'}
    write_json(Path(output)/'freeze.json',manifest)
    return manifest


def server_argv(port):
    return [str(SERVER),'-m',str(MODEL),'--alias','agents-a1-4b','--jinja','--host','127.0.0.1','--port',str(port),
            '-ngl','99','--flash-attn','auto','-c','8192','-np','1','-n','1024','--reasoning','off',
            '--cache-type-k','q8_0','--cache-type-v','q8_0','--temp','0.85','--top-p','0.95','--top-k','20','--presence-penalty','1.1']


def occupied(port):
    with socket.socket() as sock:
        sock.settimeout(.5)
        return sock.connect_ex(('127.0.0.1',port))==0


def get_json(port,path):
    with urllib.request.urlopen(f'http://127.0.0.1:{port}{path}',timeout=3) as response:
        return json.loads(response.read())


class LocalService:
    """Starts only when absent; stops only the process created by this context."""
    def __init__(self,port,output):self.port=port;self.output=output;self.process=None;self.log=None
    def __enter__(self):
        argv=server_argv(self.port)
        if not occupied(self.port):
            self.log=(self.output/'server.log').open('w')
            self.process=subprocess.Popen(argv,stdout=self.log,stderr=subprocess.STDOUT)
        try:
            deadline=time.monotonic()+180
            while True:
                if self.process and self.process.poll() is not None:raise RuntimeError('owned llama server exited during startup')
                try:
                    health=get_json(self.port,'/health')
                    if health.get('status')=='ok':break
                except Exception:
                    pass
                if time.monotonic()>=deadline:raise RuntimeError('local llama server not healthy before startup deadline')
                time.sleep(.5)
            # Existing listeners require observable process provenance, not alias alone.
            listener=subprocess.check_output(['lsof','-nP','-iTCP:'+str(self.port),'-sTCP:LISTEN','-t'],text=True).splitlines()
            pids=sorted(set(listener))
            if len(pids)!=1:raise RuntimeError('local service owner could not be uniquely identified')
            actual_argv=subprocess.check_output(['ps','-p',pids[0],'-o','command='],text=True).strip()
            if str(MODEL) not in actual_argv or str(SERVER) not in actual_argv:
                raise RuntimeError('existing service does not match frozen model/server paths')
            models=get_json(self.port,'/v1/models')
            if not any(m.get('id')=='agents-a1-4b' for m in models.get('data',[])):
                raise RuntimeError('local server model alias mismatch')
            self.runtime={'model_path':str(MODEL),'model_sha256':file_hash(MODEL),
                          'server_path':str(SERVER),'server_sha256':file_hash(SERVER.resolve()),
                          'server_version':subprocess.check_output([str(SERVER),'--version'],stderr=subprocess.STDOUT,text=True).strip(),
                          'server_argv':argv,'actual_server_command':actual_argv,'server_pid':int(pids[0]),
                          'owned_service':self.process is not None,'health':health,'models':models,'port':self.port}
            return self
        except BaseException:
            self.__exit__(None,None,None)
            raise
    def __exit__(self,*args):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=5)
        if self.log:self.log.close()
        write_json(self.output/'service-cleanup.json',{'owned_service':self.process is not None,
                                                      'owned_service_stopped':self.process is not None and self.process.poll() is not None})


class DeterministicLocalModel:
    def __init__(self,inner):self.inner=inner
    def generate(self,**kwargs):return self.inner.generate(**{**kwargs,'temperature':0})


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True);parser.add_argument('--port',type=int,default=18082)
    args=parser.parse_args()
    dirty=subprocess.check_output(['git','status','--porcelain','--',*SOURCE_FILES,'tests/test_native_model_chain.py','tests/test_native_controlled_cli.py'],cwd=ROOT,text=True)
    if dirty:parser.error('commit source and focused tests before the controlled runs')
    output=args.output_dir.resolve();output.mkdir(parents=True,exist_ok=False)
    rows=[]
    with LocalService(args.port,output) as service:
        frozen=freeze_manifest(output,service.runtime)  # Written before the first model request.
        journal=Journal(output/'journal.sqlite')
        budget=BudgetTracker(BudgetConfig(max_api_calls=20,max_input_tokens_total=2_000_000,max_output_tokens_total=6000,
                             input_cost_per_million=0,output_cost_per_million=0),output/'budget.sqlite')
        candidate=Candidate('native-controlled-v1',(),'workflow',str(ROOT),hashlib.sha256(json.dumps(frozen['source_hashes'],sort_keys=True).encode()).hexdigest())
        for task in TASKS:
            model=DeterministicLocalModel(local_broker(args.port).background_provider)
            provider=NativeChainProvider(model,task,model_label='agents-a1-4b')
            runner=EvolutionRunner(journal,budget,output/'workspaces',provider,step_isolation='inline')
            runner.evaluator=NativeEvaluator()
            start=time.monotonic()
            result=runner.run(candidate,task,RunSpec(task['task_id'],candidate.candidate_id,task['task_id'],max_steps=1,timeout_s=480))
            row={**asdict(result),'elapsed_s':time.monotonic()-start}
            rows.append(row);write_json(output/'results.json',rows)
            print(json.dumps({'task_id':task['task_id'],'status':result.status,'score':result.score,'usage':result.usage,'elapsed_s':row['elapsed_s']}),flush=True)
        write_json(output/'budget-final.json',budget.to_dict())
    print(json.dumps({'passed':sum(r['score']==1 for r in rows),'total':len(rows),'output':str(output)}))
    return 0 if all(r['score']==1 for r in rows) else 1


if __name__=='__main__':raise SystemExit(main())
