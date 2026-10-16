"""One persistent G1 recovery entry: --config CONFIG --task TASK_JSON_OR_ID.

Config: root, optional continuation_root (frozen prior run, shared budgets),
bootstrap_candidate (record/path), validation_suite, task_suite
(optional for task IDs), student_settings (mapping/path), teacher_settings
(optional private path), teacher_budget (explicit caps/rates). Paths are relative
 to CONFIG. Paid generation additionally requires --allow-paid-teacher.
"""
import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.agentic_loop import AgenticLoop
from core.model_broker import ModelBroker
from core.evolution.agent_provider import KageChainProvider
from core.evolution.artifacts import atomic_json
from core.evolution.budget import BudgetConfig, BudgetTracker
from core.evolution.bundle import RecoveryPolicy
from core.evolution.contracts import Candidate
from core.evolution.journal import Journal
from core.evolution.mutator import bundle_digest
from core.evolution.promotion import Promoter
from core.evolution.recovery_loop import RecoveryLoop
from core.evolution.recovery_mutator import RecoveryMutator
from core.evolution.sandbox import DockerSkillRunner
from core.evolution.skills import SkillCatalog
from scripts.experiments.task_suite import RecordedLocalProvider


class BoundedRecoveryMutator(RecoveryMutator):
    def _validate_request(self, messages):
        payload=self.model._request_payload(messages, temperature=0, max_tokens=3000)
        if len(self.model._serialize_request(payload)) > 12000:
            raise ValueError('teacher request exceeds 12000 bytes')


class FiveStepLoop(AgenticLoop):
    MAX_STEPS = 5


def build_loop(config_path, allow_paid_teacher=False):
    config_path=Path(config_path).expanduser().resolve()
    cfg=json.loads(config_path.read_text())
    def path(value):
        return (config_path.parent / Path(value).expanduser()).resolve()
    def record(value):
        return json.loads(path(value).read_text()) if isinstance(value,str) else value
    root=path(cfg['root'])
    if (root/'continuation.json').exists():
        raise ValueError('recovery root delegated to its continuation')
    raw=record(cfg['bootstrap_candidate']); raw=raw.get('candidate',raw)
    bootstrap=Candidate(**{**raw,'parent_ids':tuple(raw['parent_ids']), 'bundle_path':str(path(raw['bundle_path']))})
    if bootstrap.target != 'recovery' or bundle_digest(Path(bootstrap.bundle_path)) != bootstrap.digest:
        raise ValueError('immutable recovery bootstrap required')
    validation_path=path(cfg['validation_suite'])
    validation=record(cfg['validation_suite'])['tasks']
    if not validation or any(t.get('split')!='validation' for t in validation):
        raise ValueError('isolated validation suite required')
    student=record(cfg['student_settings'])
    model_cfg=student.get('model',{})
    if model_cfg.get('hybrid',{}).get('enabled') is not False or any(v!='local' for v in model_cfg.get('broker',{}).values()):
        raise ValueError('student must be explicitly local-only')
    runtime_cfg=model_cfg.get('local_runtime',{})
    local={'model':{'local_runtime':{k:runtime_cfg[k] for k in ('host','port','model_name','timeout_sec') if k in runtime_cfg}, 'hybrid':{'enabled':False}}}
    teacher_cfg=cfg['teacher_budget']
    calls=teacher_cfg['max_api_calls']; cost=teacher_cfg['max_cost_usd']
    if isinstance(calls,bool) or not isinstance(calls,int) or not 1<=calls<=6 or not 0<cost<=.03:
        raise ValueError('teacher caps must be positive: calls <=6, cost <=.03')
    teacher_budget_cfg=BudgetConfig(max_api_calls=calls,max_input_tokens_total=calls*12000,
        max_output_tokens_total=calls*3000,max_cost_usd=cost,
        input_cost_per_million=teacher_cfg['input_cost_per_million'],
        output_cost_per_million=teacher_cfg['output_cost_per_million'])
    if teacher_budget_cfg.input_cost_per_million<=0 or teacher_budget_cfg.output_cost_per_million<=0:
        raise ValueError('explicit positive teacher pricing required')
    # Only sanitized, behavior-relevant settings enter public artifacts.
    protocol={'bootstrap':asdict(bootstrap),'validation_sha256':hashlib.sha256(validation_path.read_bytes()).hexdigest(),
        'student':local,'teacher_budget':asdict(teacher_budget_cfg), 'max_candidates':2,'max_evaluations':12,
        'run_namespace':hashlib.sha256(str(root).encode()).hexdigest()[:12],
        'max_model_calls':6,'max_steps':5,'max_tool_actions':12,'timeout_s':150,
        'teacher_input_bytes':12000,'teacher_output_tokens':3000,'step_isolation':'fork',
        'source_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in
            ('scripts/kage_recover.py','core/evolution/recovery_loop.py','core/evolution/agent_provider.py',
             'core/evolution/recovery_mutator.py','core/evolution/promotion.py')}}
    protocol=json.loads(json.dumps(protocol))
    max_candidates,max_evaluations=2,12
    budget_root=root
    if cfg.get('continuation_root'):
        budget_root=path(cfg['continuation_root'])
        if budget_root==root:
            raise ValueError('continuation requires a distinct root')
        try:
            prior_bytes=(budget_root/'recovery_state.json').read_bytes()
            prior=json.loads(prior_bytes)
            prior_protocol=json.loads((budget_root/'protocol.json').read_text())
            expected=protocol['bootstrap']
            if (prior['protocol']['bootstrap']!=expected or prior_protocol['bootstrap']!=expected
                    or prior['last_verified_parent']!=expected):
                raise ValueError('bootstrap lineage mismatch')
            if any(prior['protocol'][key]!=cap or prior_protocol[key]!=cap
                   for key,cap in (('max_candidates',2),('max_evaluations',12))):
                raise ValueError('prior caps mismatch')
            for key in ('student','teacher_budget','max_model_calls','max_steps','max_tool_actions',
                        'timeout_s','teacher_input_bytes','teacher_output_tokens','step_isolation','validation_sha256'):
                if prior_protocol[key]!=protocol[key]:
                    raise ValueError('prior execution protocol mismatch')
            active_path=budget_root/'active.json'
            active_bytes=active_path.read_bytes() if active_path.exists() else None
            if active_bytes is not None and json.loads(active_bytes)['candidate']!=expected:
                raise ValueError('active child migration is unsupported')
            for key,cap in (('candidates',2),('evaluations',12)):
                count=prior[key]
                if isinstance(count,bool) or not isinstance(count,int) or not 0<=count<cap:
                    raise ValueError('prior limit exhausted or invalid')
            if not all((budget_root/name).is_file() for name in ('local-budget.sqlite','teacher-budget.sqlite')):
                raise ValueError('prior budget ledger missing')
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ValueError('invalid continuation state or protocol') from exc
        max_candidates=2-prior['candidates']
        max_evaluations=12-prior['evaluations']
        protocol.update(max_candidates=max_candidates,max_evaluations=max_evaluations,
            continuation={'root':str(budget_root),'state_sha256':hashlib.sha256(prior_bytes).hexdigest(),
                'protocol_sha256':hashlib.sha256((budget_root/'protocol.json').read_bytes()).hexdigest(),
                'active_sha256':hashlib.sha256(active_bytes).hexdigest() if active_bytes is not None else None,
                'prior_candidates':prior['candidates'],'prior_evaluations':prior['evaluations']})
    protocol_path=root/'protocol.json'
    if protocol_path.exists() and json.loads(protocol_path.read_text())!=protocol:
        raise ValueError('persistent CLI protocol changed')
    if budget_root!=root:
        claim_path=budget_root/'continuation.json'
        claim={'root':str(root),'prior_state_sha256':protocol['continuation']['state_sha256'],
               'prior_protocol_sha256':protocol['continuation']['protocol_sha256']}
        try:
            fd=os.open(claim_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        except FileExistsError:
            try:
                existing=json.loads(claim_path.read_text())
            except (OSError,ValueError):
                raise ValueError('continuation allowance already claimed; invalid claim') from None
            if existing!=claim:
                raise ValueError('continuation allowance already claimed by another root or snapshot')
        else:
            with os.fdopen(fd,'w') as out:
                json.dump(claim,out,sort_keys=True)
                out.flush()
                os.fsync(out.fileno())
    root.mkdir(parents=True,exist_ok=True)
    atomic_json(protocol_path,protocol)
    journal=Journal(root/'journal.sqlite')
    budget=BudgetTracker(BudgetConfig(max_api_calls=72,max_input_tokens_total=1_000_000,
        max_output_tokens_total=24_000,input_cost_per_million=0,output_cost_per_million=0),budget_root/'local-budget.sqlite')
    teacher_budget=BudgetTracker(teacher_budget_cfg,budget_root/'teacher-budget.sqlite')
    # Broker receives no cloud credentials or routing, even if private student settings contain them.
    student_provider=ModelBroker(local).background_provider
    runtime=local['model']['local_runtime']
    docker=DockerSkillRunner(timeout_s=10)
    def provider_factory(candidate):
        catalog=SkillCatalog.from_bundle(Path(candidate.bundle_path),runner=docker)
        policy=RecoveryPolicy.from_bundle(Path(candidate.bundle_path),runner=docker,skill_catalog=catalog)
        provider=RecordedLocalProvider(root/f'student-{candidate.digest[:16]}.jsonl',api_key='local',
            model_name=runtime.get('model_name','local-model'),base_url=f"http://{runtime.get('host','127.0.0.1')}:{int(runtime.get('port',18080))}/v1",
            timeout_sec=min(120,int(runtime.get('timeout_sec',120))))
        return KageChainProvider(provider,provider_mode='local',model_label=student_provider.model_name,
            max_model_calls=6,max_tool_actions=12,agentic_loop_cls=FiveStepLoop,
            skill_catalog=catalog,recovery_policy=policy,skill_context_mode='search')
    def mutator_factory(slot):
        if not allow_paid_teacher:
            raise RuntimeError('paid_teacher_not_authorized')
        try:
            cloud=record(cfg.get('teacher_settings') or '~/.config/kage/teachers/deepseek.json')['model']['cloud_api']
            public={k:cloud[k] for k in ('model_name','base_url')}
            if not cloud.get('api_key'): raise ValueError()
        except (OSError, ValueError, KeyError, TypeError):
            raise RuntimeError('invalid_private_teacher_settings') from None
        if budget_root!=root:
            prior_teacher_protocol=budget_root/'teacher-protocol.json'
            if prior_teacher_protocol.exists() and json.loads(prior_teacher_protocol.read_text())!=public:
                raise ValueError('continuation teacher protocol changed')
        teacher_protocol=root/'teacher-protocol.json'
        if teacher_protocol.exists() and json.loads(teacher_protocol.read_text())!=public:
            raise ValueError('persistent teacher protocol changed')
        atomic_json(teacher_protocol,public)
        provider=RecordedLocalProvider(root/'teacher-model.jsonl',api_key=cloud['api_key'],
            model_name=cloud['model_name'],base_url=cloud['base_url'],thinking=False,output_limit=3000,timeout_sec=60)
        return BoundedRecoveryMutator(provider,teacher_budget,journal,slot)
    promoter=Promoter(journal,budget,provider_factory,root,timeout_s=150,step_isolation='fork',kernel_max_steps=1,run_namespace=protocol['run_namespace'])
    return RecoveryLoop(promoter,mutator_factory,root,bootstrap,validation,max_candidates=max_candidates,max_evaluations=max_evaluations)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--task',required=True)
    parser.add_argument('--allow-paid-teacher',action='store_true')
    args=parser.parse_args(argv)
    if not args.allow_paid_teacher:
        raise RuntimeError('paid_teacher_not_authorized: task execution requires explicit --allow-paid-teacher and an approved fixed teacher budget')
    args.config=args.config.expanduser().resolve()
    cfg=json.loads(args.config.read_text())
    task_path=(args.config.parent/Path(args.task).expanduser()).resolve()
    if task_path.is_file():
        task=json.loads(task_path.read_text())
    else:
        suite=json.loads((args.config.parent/Path(cfg['task_suite']).expanduser()).read_text())
        tasks=[t for t in suite['tasks'] if t['task_id']==args.task]
        if len(tasks)!=1: raise ValueError('unique task ID required')
        task=tasks[0]
    loop=build_loop(args.config,args.allow_paid_teacher)
    report=loop.run_task(task)
    artifact=hashlib.sha256(json.dumps(task,sort_keys=True).encode()).hexdigest()
    atomic_json(loop.root/'task-reports'/f'{artifact}.json',report)
    print(json.dumps(report,ensure_ascii=False))
    return report


if __name__=='__main__':
    main()
