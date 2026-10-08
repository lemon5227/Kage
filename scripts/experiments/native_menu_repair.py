"""Frozen bounded native-menu deterministic repair validation; no inference.

python -m scripts.experiments.native_menu_repair --output DIR
Two fresh documents, one attempt each; no mutation retries or model requests.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import subprocess
import time

from core.computer_use.native_model import NativeDocumentEnvironment, ScopedNativeAdapter, check_native_completion
from core.evolution.agent_provider import run_sync
from scripts.experiments.native_lifecycle_diagnosis import OwnedTraceAdapter, unique, metrics

ROOT=Path(__file__).resolve().parents[2]
INITIAL='Kage menu repair validation.\nStatus: pending.\n'
EXPECTED='Kage menu repair validation.\nStatus: explicitly saved.\n'
PROTOCOL={'version':'native-menu-repair-v2-readiness','contexts':['main','run_sync'],'attempts_per_context':1,
          'max_editor_actions_per_context':4,'max_checker_cleanup_actions_per_context':4,
          'max_native_actions_per_context':8,'max_app_open_requests_per_context':2,
          'activation_dispatches_max':1,'activation_checks_max':10,
          'post_action_read_checks_max':3,'checker_observation_attempts_max':30,
          'checker_observation_deadline_s':3,'deadline_semantics':'cooperative before AX calls',
          'model_requests':0,'cloud_calls':0,'mutation_retries':0}
SOURCES=['scripts/experiments/native_menu_repair.py','tests/test_native_menu_repair.py',
         'core/computer_use/native_ax.py','core/computer_use/native_model.py',
         'core/computer_use/browser.py','core/evolution/agent_provider.py',
         'scripts/experiments/native_lifecycle_diagnosis.py']


def freeze(output):
    dirty=subprocess.check_output(['git','status','--porcelain','--',*SOURCES],cwd=ROOT,text=True)
    if dirty:raise ValueError('commit repair source and tests before validation')
    manifest={'protocol':PROTOCOL,'initial':INITIAL,'expected':EXPECTED,'expected_metrics':metrics(EXPECTED),
              'git_revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
              'source_hashes':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in SOURCES}}
    (output/'freeze.json').write_text(json.dumps(manifest,indent=2))


class BoundedOwnedTraceAdapter(OwnedTraceAdapter):
    """Count every native attempt across editing and trusted verification."""
    def __init__(self, document, trace_path):
        super().__init__(document, trace_path)
        self.actor='editor'
        self.attempts={'editor':0,'checker_cleanup':0}

    async def act(self, observation_id, operation, target_ref, value=None):
        phase='checker_cleanup' if self.actor in {'checker','cleanup'} else 'editor'
        if self.attempts[phase]>=4 or sum(self.attempts.values())>=8:
            result={'success':False,'error':'ActionLimit','outcome':'rejected',
                    'message':'native repair phase/total attempt cap reached','action_applied':False}
            self._record('quota_rejection',time.monotonic(),actor=self.actor,result=result)
            return result
        self.attempts[phase]+=1
        self._record('attempt',time.monotonic(),actor=self.actor,
                     operation=operation,attempts=dict(self.attempts))
        return await super().act(observation_id,operation,target_ref,value)


async def probe(output,context):
    output.mkdir()
    document=(output/f'kage-menu-validation-{context}.txt').resolve();document.write_text(INITIAL)
    env=NativeDocumentEnvironment(document,output);env.adapter=BoundedOwnedTraceAdapter(document,output/'ax-trace.jsonl')
    scope=ScopedNativeAdapter(env.adapter,'com.apple.TextEdit',document.name,document_path=document,max_actions=4)
    started=time.monotonic();stages=[]
    def record(phase,result):
        row={'phase':phase,'elapsed_s':time.monotonic()-started,'result':result};stages.append(row)
        with (output/'timeline.jsonl').open('a') as stream:stream.write(json.dumps(row)+'\n')
        return result
    def observation(result):
        if not result.get('success'):raise RuntimeError(json.dumps(result))
        return result['observation']
    async def action(obs,operation,predicate,value=None):
        target=unique(obs,predicate)
        return record(operation,await scope.act(obs['observation_id'],operation,target['target_ref'],value))
    checked={'status':'unknown'}
    try:
        record('setup',await env.setup());obs=observation(record('initial',await scope.initial()))
        if obs.get('application_active') is not True:
            if not obs.get('activation_supported'):raise RuntimeError('owned application activation unsupported; no edit dispatched')
            obs=observation(await action(obs,'activate',lambda t:t['role']=='AXWindow'))
        obs=observation(await action(obs,'fill',lambda t:t['role']=='AXTextArea',EXPECTED))
        obs=observation(await action(obs,'press',lambda t:t['role']=='AXMenuBarItem'))
        obs=observation(await action(obs,'press',lambda t:str(t.get('command','')).lower()=='s'))
        if not scope.save_applied:raise RuntimeError('no verified app Save applied')
        env.adapter.actor='checker'
        checked=record('completion',await check_native_completion(document,EXPECTED,env.reread))
        if checked['status']=='passed':
            env.adapter.actor='cleanup'
            record('cleanup',await env.cleanup())
    except Exception as exc:
        record('failure',{'error':type(exc).__name__,'message':str(exc)})
        if checked['status']!='passed':checked={'status':'unknown','error':f'{type(exc).__name__}: {exc}'}
        record('preserve',{'reason':'no mutation retry; retain uncertain owned document'})
    report={'context':context,'document':str(document),'completion':checked,'actions':scope.actions,
            'save_applied':scope.save_applied,'stages':stages,'model_requests':0,'cloud_calls':0,
            'native_attempts_by_phase':env.adapter.attempts,
            'native_attempts_total':sum(env.adapter.attempts.values()),
            'app_open_requests':sum(e['operation'] in {'open','reopen'} for e in env.events)}
    try:report['disk']={'expected_matches':document.read_text()==EXPECTED,**metrics(document.read_text())}
    except Exception as exc:report['disk']={'error':f'{type(exc).__name__}: {exc}'}
    (output/'report.json').write_text(json.dumps(report,indent=2));return report


async def run(output):
    if output.exists():raise ValueError('fresh artifact directory required; no overwrites')
    output.mkdir(parents=True);freeze(output)
    rows=[await probe(output/'main','main'),run_sync(lambda:probe(output/'run_sync','run_sync'))]
    (output/'summary.json').write_text(json.dumps({'protocol':PROTOCOL,'probes':rows},indent=2));return rows


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    rows=asyncio.run(run(parser.parse_args().output.resolve()))
    print(json.dumps({'passed':sum(r['completion']['status']=='passed' for r in rows),'total':len(rows)}))
    raise SystemExit(0 if all(r['completion']['status']=='passed' for r in rows) else 1)
