"""One frozen local TextEdit dev4 attempt with an independent read-only observer."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

from core.computer_use.native_model import NativeChainProvider, NativeEvaluator, NativeDocumentEnvironment
from core.evolution.budget import BudgetConfig, BudgetTracker
from core.evolution.contracts import Candidate, RunSpec
from core.evolution.journal import Journal
from core.evolution.runner import EvolutionRunner
from scripts.experiments.native_model_pilot import ROOT, LocalService, DeterministicLocalModel, local_broker, file_hash
from scripts.experiments.native_menu_model_dev import RECOVERY_SOUL, TASKS
from scripts.experiments.native_lifecycle_long import Reader, read_child, start_owned, stop_owned, error, write_json as atomic_json

MODULE='scripts.experiments.native_text_observed_dev'
TEXT='文档复核\n结论：已确认\n操作：保存并验证\n'
TASK={**TASKS['dev3'], 'task_id':'native_text_observed_dev4', 'document_name':'kage-text-observed-dev4.txt',
      'output_file':'kage-text-observed-dev4.txt', 'expected':TEXT,
      'initial_files':{'kage-text-observed-dev4.txt':'文档复核\n结论：待确认\n'},
      'instruction':TASKS['dev3']['instruction'].split('Exact JSON text:\n')[0].replace('读回','验证')+'Exact JSON text:\n'+json.dumps(TEXT,ensure_ascii=False)}
PROTOCOL={'version':'native-text-observed-dev4-v1','tasks':1,'attempts_per_task':1,'max_loop_steps':8,
          'max_requests':8,'max_agent_actions':16,'max_checker_cleanup_native_actions':4,
          'max_total_native_actions':20,'max_app_open_requests':2,'cooperative_timeout_s':480,
          'cloud_calls':0,'temperature':0,'max_output_per_request':300,'split':'dev',
          'observer_interval_s':2,'observer_max_samples':240,'observer_duration_s':480,
          'observer_gate_timeout_s':15,'reader_timeout_s':3,
          'purpose':'instrumented development; observer/pump may influence lifecycle; no causal attribution'}
SOURCES=sorted(set(str(p.relative_to(ROOT)) for p in (ROOT/'core').rglob('*.py')) |
               set(str(p.relative_to(ROOT)) for p in (ROOT/'scripts/experiments').glob('*.py')) |
               {'main.py'} | set(str(p.relative_to(ROOT)) for p in (ROOT/'tests').glob('test_native*.py')))


def budget_config():
    return BudgetConfig(max_api_calls=8,max_input_tokens_total=1_000_000,max_output_tokens_total=3000,
                        input_cost_per_million=0,output_cost_per_million=0)


def make_provider(model, environment_factory):
    return NativeChainProvider(model,TASK,model_label='agents-a1-4b',max_model_calls=8,
                               native_soul=RECOVERY_SOUL,environment_factory=environment_factory)


def owned_baseline(value):
    return (value.get('success') is True and value.get('owned_count')==1 and
            value.get('owned_url') is not None and value.get('app_pid') is not None)


def valid_ready(ready):
    baseline=ready.get('baseline',{})
    return (owned_baseline(baseline) and baseline.get('original_present') is True and
            baseline.get('original_pid') is not None and owned_baseline(ready.get('fresh',{})) and
            baseline.get('owned_url')==ready['fresh'].get('owned_url') and
            baseline.get('original_pid')==baseline.get('app_pid')==ready['fresh'].get('app_pid'))


def disk_metrics(document):
    try:
        data=document.read_bytes()
        return {'success':True,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
    except Exception as exc:return error(exc)


class ObservationController:
    def __init__(self,output):
        self.output=Path(output);self.child=None;self.calls=0;self.ready=False;self.environment=None

    def event(self,actor,stage,**fields):
        row={'actor':actor,'stage':stage,'monotonic':time.monotonic(),**fields}
        atomic_json(self.output/'stage.json',row)
        with (self.output/'events.jsonl').open('a') as stream:stream.write(json.dumps(row)+'\n')
        return row

    def start(self,document):
        self.event('setup','observer_start')
        self.child=start_owned([sys.executable,'-m',MODULE,'--observer',str(document),'--output',str(self.output)],
                               self.output/'observer.stdout',self.output/'observer.stderr')

    def gate(self):
        if self.ready:return
        deadline=time.monotonic()+15
        path=self.output/'observer-ready.json'
        while not path.exists():
            if self.child is None or self.child.poll() is not None or time.monotonic()>=deadline:
                raise TimeoutError('observer readiness')
            time.sleep(.01)
        ready=json.loads(path.read_text())
        if not valid_ready(ready):raise RuntimeError('invalid owned observer baseline')
        self.ready=True

    def stop(self):
        self.event('observer','stop_requested')
        atomic_json(self.output/'observer-stop.json',{'monotonic':time.monotonic()})
        report={}
        if self.child is not None:
            deadline=time.monotonic()+4
            while self.child.poll() is None and time.monotonic()<deadline:time.sleep(.02)
            try:report=stop_owned(self.child)
            except Exception as exc:report=error(exc)
        atomic_json(self.output/'observer-cleanup.json',report)
        return report


class DispatchModel:
    def __init__(self,inner,controller):self.inner=inner;self.controller=controller
    def generate(self,**kwargs):
        c=self.controller;c.gate()
        c.calls+=1
        row=c.event('agent','model_request',request=c.calls)
        if c.calls==1:atomic_json(c.output/'observer-start.json',{'first_model_dispatch_monotonic':row['monotonic']})
        try:
            response=self.inner.generate(**kwargs)
        except Exception as exc:
            c.event('agent','model_error',request=c.calls,**error(exc));raise
        c.event('agent','model_response',request=c.calls)
        return response


class ActionAdapter:
    def __init__(self,inner,controller):self.inner=inner;self.controller=controller
    def __getattr__(self,name):return getattr(self.inner,name)
    @property
    def current(self):return self.inner.current
    @current.setter
    def current(self,value):self.inner.current=value
    async def act(self,observation_id,operation,target_ref,value=None):
        marker=json.loads((self.controller.output/'stage.json').read_text()) if (self.controller.output/'stage.json').exists() else {}
        actor=marker.get('actor','agent')
        targets=(self.inner.current or {}).get('targets',[])
        target=next((t for t in targets if t.get('target_ref')==target_ref),{})
        phase='close' if operation=='press' and str(target.get('command','')).lower()=='w' else 'native_action'
        self.controller.event(actor,phase+'_dispatch',operation=operation)
        try:
            result=await self.inner.act(observation_id,operation,target_ref,value)
            self.controller.event(actor,phase+'_result',operation=operation,action_applied=result.get('action_applied'),success=result.get('success'))
            return result
        except Exception as exc:
            self.controller.event(actor,phase+'_error',operation=operation,**error(exc));raise


class ObservedEnvironment(NativeDocumentEnvironment):
    def __init__(self,document,output,controller):
        super().__init__(document,output)
        self.adapter.trace_path=None
        self.controller=controller;controller.environment=self
        self.adapter=ActionAdapter(self.adapter,controller)
    async def setup(self):
        self.controller.event('setup','setup')
        result=await super().setup()
        if result.get('success'):
            self.controller.start(self.document)
            self.controller.gate()
        return result
    def record(self,actor,operation,result):
        # Setup discovery may enumerate foreign windows in memory; never retain its raw trace.
        if actor=='setup':
            safe={'success':result.get('success'),'error':result.get('error')}
            super().record(actor,operation,safe)
            return result
        self.controller.event(actor,operation,success=result.get('success'),action_applied=result.get('action_applied'))
        return super().record(actor,operation,result)
    async def close(self,actor):
        self.controller.event(actor,'close')  # Intent only: action result proves whether Close applied.
        return await super().close(actor)
    async def reread(self):
        self.controller.event('checker','reread')
        return await super().reread()
    async def cleanup(self):
        self.controller.event('cleanup','cleanup')
        return await super().cleanup()


def observe(output,reader,fresh,pump,*,interval=2,maximum=240,duration=480,disk=None):
    report={'baseline':{},'sample_count':0,'observer_start_monotonic':time.monotonic()}
    try:
        report['baseline']=reader.sample();report['baseline_monotonic']=time.monotonic()
        report['fresh']=fresh();report['fresh_baseline_monotonic']=time.monotonic()
        atomic_json(output/'observer-ready.json',report)
        if not valid_ready(report):raise RuntimeError('invalid owned observer baseline')
        gate_deadline=time.monotonic()+15
        while not (output/'observer-start.json').exists():
            if (output/'observer-stop.json').exists():return report
            if time.monotonic()>=gate_deadline:raise TimeoutError('model start gate')
            pump(.01)
        gate=json.loads((output/'observer-start.json').read_text())
        report.update(gate)
        started=time.monotonic();report['sampling_start_monotonic']=started
        for index in range(min(maximum,240)):
            if (output/'observer-stop.json').exists() or time.monotonic()-started>=min(duration,480):break
            read_start=time.monotonic()
            marker=json.loads((output/'stage.json').read_text())
            try:cached=reader.sample()
            except Exception as exc:cached={**error(exc),'original_present':None,'original_pid':reader.original_pid,'original_window_ref':reader.original_ref}
            row={'sample':index,'read_start_monotonic':read_start,'actor':marker.get('actor'),'stage':marker.get('stage'),'stage_marker':marker,
                 'cached':cached,'fresh':fresh()}
            if disk is not None:row['disk']=disk()
            row['read_end_monotonic']=time.monotonic()
            row['stage_after_reads']=json.loads((output/'stage.json').read_text())
            with (output/'timeline.jsonl').open('a') as stream:stream.write(json.dumps(row)+'\n')
            report['sample_count']+=1
            until=min(started+(index+1)*interval,started+duration)
            while time.monotonic()<until and not (output/'observer-stop.json').exists():pump(min(.05,until-time.monotonic()))
    except Exception as exc:report.update(error(exc))
    finally:
        report['observer_end_monotonic']=time.monotonic()
        atomic_json(output/'observer-report.json',report)
    return report


def observer(document,output):
    import Foundation
    def pump(seconds):
        Foundation.NSRunLoop.currentRunLoop().runUntilDate_(Foundation.NSDate.dateWithTimeIntervalSinceNow_(max(0,seconds)))
    def fresh():return read_child([sys.executable,'-m','scripts.experiments.native_lifecycle_long','--reader',str(document)])
    return observe(output,Reader(document),fresh,pump,disk=lambda:disk_metrics(document))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--port',type=int,default=18082)
    parser.add_argument('--observer',type=Path,help=argparse.SUPPRESS)
    args=parser.parse_args()
    if args.observer:
        observer(args.observer.resolve(),args.output.resolve());return 0
    if subprocess.check_output(['git','status','--porcelain','--',*SOURCES],cwd=ROOT,text=True):
        parser.error('commit source before frozen dev attempt')
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    controllers=[];budget=None;cleanup_reports=[]
    with LocalService(args.port,output) as service:
        frozen={'protocol':PROTOCOL,'task':TASK,'selected_task':'dev4','prompt':RECOVERY_SOUL,'runtime':service.runtime,
                'python':platform.python_version(),'python_executable':sys.executable,'platform':platform.platform(),
                'git_revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                'source_hashes':{name:file_hash(ROOT/name) for name in SOURCES},'frozen_at_utc':datetime.now(timezone.utc).isoformat(),
                'token_semantics':'conservative kernel reservation 3000, actual output limit 300 per request',
                'timing_semantics':'cooperative synchronous AX/HTTP may overrun task deadline; observer bounded separately'}
        for key,value in [('task',TASK),('protocol',PROTOCOL)]:
            frozen[key+'_sha256']=hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        frozen['prompt_sha256']=hashlib.sha256(RECOVERY_SOUL.encode()).hexdigest()
        atomic_json(output/'freeze.json',frozen)
        def environment_factory(document,workspace):
            c=ObservationController(workspace);controllers.append(c)
            model.controller=c
            return ObservedEnvironment(document,workspace,c)
        model=DispatchModel(DeterministicLocalModel(local_broker(args.port).background_provider),None)
        provider=make_provider(model,environment_factory)
        budget=BudgetTracker(budget_config(),output/'budget.sqlite')
        runner=EvolutionRunner(Journal(output/'journal.sqlite'),budget,output/'workspaces',provider,step_isolation='inline')
        runner.evaluator=NativeEvaluator()
        candidate=Candidate(PROTOCOL['version'],(),'workflow',str(ROOT),hashlib.sha256(json.dumps(frozen['source_hashes'],sort_keys=True).encode()).hexdigest())
        atomic_json(output/'submission.json',{'task_id':TASK['task_id'],'attempt':1,'protocol':PROTOCOL})
        try:
            result=runner.run(candidate,TASK,RunSpec(TASK['task_id'],candidate.candidate_id,TASK['task_id'],max_steps=1,timeout_s=480))
            atomic_json(output/'result.json',asdict(result))
        finally:
            for controller in controllers:cleanup_reports.append(controller.stop())
            atomic_json(output/'budget-final.json',budget.to_dict())
    cleanup_failed=any(any(key in report for key in ('error','cleanup_error','group_signal_error')) for report in cleanup_reports)
    atomic_json(output/'instrumentation.json',{'actual_model_requests':sum(c.calls for c in controllers),
                'observer_cleanup_failed':cleanup_failed,'observer_cleanup':cleanup_reports})
    return 0 if result.score==1 and not cleanup_failed else 1


if __name__=='__main__':raise SystemExit(main())
