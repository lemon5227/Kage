"""Frozen browser-transfer protocol and arm accounting."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from core.computer_use.experiment import BrowserChainProvider
from core.computer_use.task_environment import atomic_json
from core.evolution.runner import Evaluator

ARMS=('raw','cloud_takeover','dev_trajectory','learned_workflow','local_retries')


@dataclass(frozen=True)
class TransferPlan:
    suite_id: str
    suite_sha256: str
    task_ids: tuple[str,...]
    repeats: int
    arms: tuple[str,...]

    @property
    def expected_runs(self):
        return len(self.task_ids)*self.repeats*len(self.arms)


def load_plan(path):
    path=Path(path)
    data=json.loads(path.read_text())
    protocol=data.get('protocol',{})
    if data.get('status')!='frozen-before-browser-workflow-generation':
        raise ValueError('transfer suite must be frozen before candidate generation')
    if protocol.get('split')!='test' or tuple(protocol.get('arms',()))!=ARMS:
        raise ValueError('transfer suite must declare the five frozen arms in order')
    tasks=data.get('tasks',[])
    if not tasks or any(task.get('split')!='test' for task in tasks):
        raise ValueError('transfer suite must contain test tasks only')
    ids=[task.get('task_id') for task in tasks]
    if len(set(ids))!=len(ids) or any(not task.get('scoring_criteria') for task in tasks):
        raise ValueError('transfer tasks need unique ids and independent checkers')
    repeats=protocol.get('repeats_per_arm_per_task')
    if not isinstance(repeats,int) or repeats<1: raise ValueError('invalid repeat count')
    return TransferPlan(data['suite_id'],hashlib.sha256(path.read_bytes()).hexdigest(),tuple(ids),repeats,ARMS)


def candidate_manifest(path):
    path=Path(path)
    manifest=json.loads((path/'manifest.json').read_text())
    if manifest.get('version')!=2 or manifest.get('kind')!='browser_workflow':
        raise ValueError('learned candidate is not a browser workflow v2 bundle')
    return manifest


def result_key(task_id,arm,repeat):
    if arm not in ARMS: raise ValueError('unknown transfer arm')
    if not isinstance(repeat,int) or repeat<0: raise ValueError('repeat must be nonnegative')
    return f'{task_id}--{arm}--r{repeat}'


def trajectory_prompt(feedback):
    """Project a verified dev demonstration into labels/states, never old refs."""
    def visible(observation):
        return [{key:target[key] for key in ('label','input_type','checked','value') if key in target}
                for target in (observation or {}).get('targets',[])]
    previous=feedback['initial_observation']
    actions=[]
    for row in feedback['actions']:
        args=row['arguments']
        label=next((t.get('label') for t in (previous or {}).get('targets',[])
                    if t.get('target_ref')==args.get('target_ref')),None)
        actions.append({'actor':row['actor'],'tool':row['tool'],'operation':args.get('operation'),
                        'label':label,'value':args.get('value'),'outcome':row['outcome'],
                        'visible_after':visible(row.get('observation'))})
        if row.get('observation'): previous=row['observation']
    demo={'instruction':feedback['instruction'],'initial_targets':visible(feedback['initial_observation']),
          'actions':actions}
    return ('\nVerified development demonstration; adapt its method to the current instruction and DOM. '
            'Labels and desired values may differ. Do not replay old identifiers or copy its goal values.\n'
            +json.dumps(demo,ensure_ascii=False,separators=(',',':'))+'\n')


class BrowserTrajectoryProvider(BrowserChainProvider):
    def __init__(self,model,task,*,dev_feedback,**kwargs):
        self.dev_prompt=trajectory_prompt(dev_feedback)
        super().__init__(model,task,**kwargs)

    def _experiment_soul(self):
        return super()._experiment_soul()+self.dev_prompt


class BrowserRetryProvider(BrowserChainProvider):
    """Fixed 2/2/1-step attempts on one page; calls/primitives/deadline shared."""
    def _student_step_limit(self):
        return 2

    def cache_identity(self):
        return {**super().cache_identity(),'retry_policy':'same-page-2-2-1-v1',
                'transfer_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}

    async def _after_student(self,task,step,workspace,adapter,registry,executor,student):
        attempts=[student]
        consumed=student['chain']['chain_steps']
        while (Evaluator.score(self.task_def,workspace)<1 and consumed<5
               and len(self._model.calls)<self._model.max_calls
               and executor.browser_quota.used<executor.browser_quota.limit):
            last=attempts[-1]['chain']
            notice=('\nRetry: the previous attempt did not pass the external completion check. '
                    'Continue this same live page and current state; recheck the instruction and save. '
                    f'Previous stop: {last["stop_reason"]}. Previous response: {last["final_text"][:500]}')
            attempt=await self._run_actor(task,step,workspace,adapter,registry,executor,self._model,
                f'student_retry_{len(attempts)}',self._experiment_soul(),notice,
                reset_quota=False,max_steps=min(2,5-consumed))
            attempts.append(attempt)
            # Reserve a step even for an early exception/empty result; no unbounded retries.
            consumed+=max(1,attempt['chain']['chain_steps'])
        usage={'api_calls':sum(a['usage']['api_calls'] for a in attempts)}
        if all('input_tokens' in a['usage'] and 'output_tokens' in a['usage'] for a in attempts):
            usage.update({key:sum(a['usage'][key] for a in attempts) for key in ('input_tokens','output_tokens')})
        info={'policy':'same-page-2-2-1-v1','surface_id':adapter.surface_id,
              'attempts':[a['chain'] for a in attempts]}
        atomic_json(workspace/'retries.json',info)
        chain={**attempts[-1]['chain'],'retries':info,'chain_steps':consumed,
               'model_calls':usage['api_calls'],'browser_primitives':executor.browser_quota.used}
        for key in ('model_elapsed_ms','agent_elapsed_ms'):
            chain[key]=sum(a['chain'][key] for a in attempts)
        for key in ('call_usage','model_errors'):
            chain[key]=[item for a in attempts for item in a['chain'][key]]
        tools=[item for a in attempts for item in a['tool_results']]
        chain['tool_calls']=len(tools)
        return {'usage':usage,'chain':chain,'tool_results':tools}
