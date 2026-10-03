"""Frozen browser-transfer protocol and arm accounting."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

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
