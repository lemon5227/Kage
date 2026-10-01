"""Bounded teacher recovery within the student's still-live browser session."""
import json
import hashlib
from pathlib import Path
from core.computer_use.experiment import BrowserChainProvider,BROWSER_SOUL
from core.computer_use.task_environment import atomic_json,checkpoint
from core.evolution.agent_provider import MeteredProvider
from core.evolution.runner import Evaluator
from core.computer_use.context_pack import BrowserContextProvider

class BrowserTeacherTakeoverProvider(BrowserChainProvider):
    def __init__(self,student_model,teacher_model,task_def,*,teacher_label='deepseek-flash',max_teacher_calls=6,teacher_output_tokens=1024,teacher_context_pack=False,**kwargs):
        super().__init__(student_model,task_def,**kwargs)
        self.teacher_context_pack=bool(teacher_context_pack)
        self.teacher_label=teacher_label
        self._teacher=MeteredProvider(teacher_model,label=teacher_label,max_calls=max_teacher_calls)
        self.RESERVATION_INPUT_CAP+=max_teacher_calls*12000
        self.RESERVATION_OUTPUT_CAP+=max_teacher_calls*teacher_output_tokens
        self.max_model_calls+=max_teacher_calls

    def cache_identity(self):
        return {**super().cache_identity(),'teacher':self.teacher_label,'teacher_calls':self._teacher.max_calls,
                'teacher_context_pack':self.teacher_context_pack,'context_pack_sha256':hashlib.sha256(Path(__file__).with_name('context_pack.py').read_bytes()).hexdigest(),
                'policy':'same-page-failed-external-check-v1','takeover_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}

    def metadata(self):
        return {**super().metadata(),'provider_mode':'same-page-browser-takeover','teacher':self.teacher_label,'teacher_context_pack':self.teacher_context_pack,
                'student_call_guard':self._model.max_calls,'teacher_call_guard':self._teacher.max_calls}

    def _actor_model(self,model,actor,workspace):
        return BrowserContextProvider(model,workspace) if actor=='teacher' and self.teacher_context_pack else model

    async def _after_student(self,task,step,workspace,adapter,registry,executor,student):
        checked=await checkpoint(adapter.page,executor.url,workspace)
        passed=Evaluator.score(self.task_def,workspace)>=1
        info={'triggered':not passed,'continued_same_page':True,
              'student_surface_id':adapter.surface_id,'student_state':checked,
              'student_check_passed':passed,'student_chain':student['chain'],'student_usage':student['usage'],
              'teacher_usage':{'api_calls':0,'input_tokens':0,'output_tokens':0}}
        atomic_json(workspace/'student-state.json',info)
        final=student
        if not passed:
            teacher=await self._run_actor(task,step,workspace,adapter,registry,executor,self._teacher,'teacher',BROWSER_SOUL,
                '\nThe student attempt failed the external check. Continue this same live page. Reobserve the saved/current values and correct them. Revisions are allowed. Do not restart the task or navigate away.')
            info.update(teacher_usage=teacher['usage'],teacher_chain=teacher['chain'],teacher_check_passed=Evaluator.score(self.task_def,workspace)>=1)
            keys=['api_calls','input_tokens','output_tokens'] if all('input_tokens' in r['usage'] and 'output_tokens' in r['usage'] for r in [student,teacher]) else ['api_calls']
            final={'usage':{k:student['usage'].get(k,0)+teacher['usage'].get(k,0) for k in keys},
                   'tool_results':student['tool_results']+teacher['tool_results'],
                   'chain':{**teacher['chain'],'model_elapsed_ms':student['chain']['model_elapsed_ms']+teacher['chain']['model_elapsed_ms'],
                            'agent_elapsed_ms':student['chain']['agent_elapsed_ms']+teacher['chain']['agent_elapsed_ms'],
                            'chain_steps':student['chain']['chain_steps']+teacher['chain']['chain_steps']}}
        info['final_surface_id']=adapter.surface_id
        info['final_state']=await checkpoint(adapter.page,executor.url,workspace)
        atomic_json(workspace/'takeover.json',info)
        final['chain']={**final['chain'],'takeover':info,'model_calls':final['usage']['api_calls'],'tool_calls':len(final['tool_results'])}
        return final
