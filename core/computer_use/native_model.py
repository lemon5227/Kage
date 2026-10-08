"""Document-scoped native tools through Kage's existing model execution chain.

Imports of AppKit/Quartz remain lazy in native_ax. Completion is trusted runtime
work after the loop and is never part of the model's registry or messages.
"""
from dataclasses import asdict
import json
from pathlib import Path
import time
from urllib.parse import urlparse,unquote

from core.agentic_loop import AgenticLoop, LoopResult
from core.computer_use.native_ax import NativeAXAdapter
from core.evolution.agent_provider import ExperimentIdentityStore, HistorySession, MeteredProvider, resolve_in_workspace
from core.evolution.budget import BudgetExhaustedError
from core.model_provider import ModelCallLimitExceeded
from core.prompt_builder import PromptBuilder
from core.tool_executor import ToolExecutor
from core.tool_registry import ToolRegistry,ToolDefinition

NATIVE_SOUL = '''You are Kage completing a dedicated native document task through accessibility tools.
Only use provided native tools. Initial native observation is the actual current state.
Use current observation_id and target_ref exactly. Every action returns fresh refs.
On stale errors use the returned fresh observation, or observe the owned window again.
Use semantic roles, values and menu command keys. If application_active is false,
use the observed window activate operation once and require success before editing.
Activation consumes a native action. If activation is unsupported or fails, stop.
Fill the text area with the complete
requested text, then open the document menu and press its Save command (command s).
Tool success and your final statement do not prove completion. Save through the app.
Never use file writes, global keystrokes, other windows or invented references.
Call one tool at a time and give a brief final statement when finished.
'''


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def append_json(path, value):
    with Path(path).open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(value, ensure_ascii=False)+'\n')


class ScopedNativeAdapter:
    """Expose only one allowed document, with cooperative deadline/action guards."""
    def __init__(self, adapter, bundle_id, document_name, *, max_actions=16, deadline=None, document_path=None):
        self.adapter=adapter; self.bundle_id=bundle_id; self.document_name=document_name
        self.document_path=Path(document_path).resolve() if document_path is not None else None
        self.allowed_ref=None; self.max_actions=max_actions; self.actions=0; self.deadline=deadline;self.save_applied=False

    def rejected(self, code, message):
        return {'success':False,'outcome':'rejected','error':code,'message':message,'action_applied':False}

    def expired(self):
        return self.deadline is not None and time.monotonic() >= self.deadline

    def owns(self, observation):
        if observation.get("title")!=self.document_name:return False
        if self.document_path is None:return True
        parsed=urlparse(observation.get("document_url", ""))
        return parsed.scheme=="file" and parsed.netloc in {"", "localhost"} and Path(unquote(parsed.path)).resolve()==self.document_path

    async def windows(self, bundle_id):
        if self.expired():return self.rejected('Deadline','native task deadline reached')
        if bundle_id != self.bundle_id:return self.rejected('ScopeViolation','application outside dedicated scope')
        result=await self.adapter.windows(bundle_id)
        self.allowed_ref=None
        if not result['success']:return result
        matches=[w for w in result['windows'] if self.owns(w)]
        if len(matches)!=1:return self.rejected('ScopeUnavailable','dedicated document must match exactly one window')
        self.allowed_ref=matches[0]['window_ref']
        return {**result,'windows':matches}

    def scoped_result(self, result):
        observation=result.get("observation")
        if observation is not None and (observation.get("window_ref")!=self.allowed_ref or not self.owns(observation)):
            self.adapter.current=None
            rejected=self.rejected("ScopeViolation","document identity changed")
            rejected["action_applied"]=result.get("action_applied")
            return rejected
        return result

    async def observe(self, window_ref):
        if self.expired():return self.rejected('Deadline','native task deadline reached')
        if self.allowed_ref is None:
            identified=await self.windows(self.bundle_id)
            if not identified['success']:return identified
        if window_ref!=self.allowed_ref:return self.rejected('ScopeViolation','window outside dedicated scope')
        result=await self.adapter.observe(window_ref)
        return self.scoped_result(result)

    async def initial(self):
        result=await self.windows(self.bundle_id)
        if not result['success']:return result
        return await self.observe(self.allowed_ref)

    async def act(self, observation_id, operation, target_ref, value=None):
        if self.expired():return self.rejected('Deadline','native task deadline reached')
        current=self.adapter.current
        if not current or current.get('window_ref')!=self.allowed_ref or not self.owns(current):
            self.adapter.current=None
            return self.rejected('ScopeViolation','observe dedicated document before acting')
        if self.actions>=self.max_actions:return self.rejected('ActionLimit','primitive action guard reached')
        self.actions+=1  # Counts every attempted primitive dispatch, including stale/failed.
        target=next((t for t in current["targets"] if t["target_ref"]==target_ref),{})
        result=await self.adapter.act(observation_id,operation,target_ref,value)
        if operation=="fill" and result.get("action_applied") is not False:
            self.save_applied=False
        result=self.scoped_result(result)
        if result.get("success") and operation=="press" and str(target.get("command", "")).lower()=="s" and result.get("action_applied") is True:
            self.save_applied=True
        return result

    def register_tools(self, registry):
        # Reuse the adapter's production schemas; replace only their bound handlers.
        schemas=ToolRegistry();self.adapter.register_tools(schemas)
        definitions={s["function"]["name"]:s["function"] for s in schemas.get_all_schemas()}
        for name, method in [('native_windows',self.windows),('native_observe',self.observe),('native_act',self.act)]:
            async def handler(_method=method, **arguments):
                return json.dumps(await _method(**arguments),ensure_ascii=False)
            definition=definitions[name]
            registry.register(ToolDefinition(name,definition["description"],definition["parameters"],handler))


class NativePromptBuilder(PromptBuilder):
    BEHAVIOR_RULE='Complete the native task with the provided tools and current observations.'
    COMMAND_RULE=BEHAVIOR_RULE
    CHAT_RULE=BEHAVIOR_RULE


class NativeExecutor(ToolExecutor):
    def __init__(self,registry,output):
        super().__init__(registry,str(output));self.output=output;self.entries=[]
    async def execute(self,name,arguments,require_confirmation=None):
        result=await super().execute(name,arguments,require_confirmation)
        entry={**asdict(result),'arguments':arguments,'actor':'agent'}
        self.entries.append(entry);append_json(self.output/'agent-tools.jsonl',entry)
        return result


class NativeRecordedModel:
    def __init__(self,model,output,deadline,budget=None):
        self.model=model;self.output=output;self.deadline=deadline;self.budget=budget;self.dispatched=0
    def generate(self,**kwargs):
        kwargs['temperature']=0
        if time.monotonic()>=self.deadline:raise ModelCallLimitExceeded('cooperative task deadline reached')
        reservation=None
        if self.budget:
            try:reservation=self.budget.reserve(100000,kwargs.get('max_tokens',300))
            except BudgetExhaustedError as exc:raise ModelCallLimitExceeded(str(exc)) from exc
        request={'messages':kwargs['messages'],'request':{k:v for k,v in kwargs.items() if k!='messages'}}
        append_json(self.output/'model.jsonl',{'phase':'request',**request})
        self.dispatched+=1
        try:
            response=self.model.generate(**kwargs)
        except Exception as exc:
            if reservation:self.budget.settle(reservation,None)
            append_json(self.output/'model.jsonl',{'phase':'error','error':f'{type(exc).__name__}: {exc}'})
            raise
        if reservation:self.budget.settle(reservation,response.usage)
        append_json(self.output/'model.jsonl',{'phase':'response','response':asdict(response)})
        return response


class NativeModelChain:
    def __init__(self,model,adapter,bundle_id,document_name,output,*,max_requests=10,max_steps=8,max_actions=16,timeout_s=480,budget=None,document_path=None):
        self.model=model;self.adapter=adapter;self.bundle_id=bundle_id;self.document_name=document_name
        self.output=Path(output);self.max_requests=max_requests;self.max_steps=max_steps
        self.max_actions=max_actions;self.timeout_s=timeout_s;self.budget=budget;self.document_path=document_path

    async def run(self,instruction):
        self.output.mkdir(parents=True,exist_ok=True)
        deadline=time.monotonic()+self.timeout_s
        scoped=ScopedNativeAdapter(self.adapter,self.bundle_id,self.document_name,max_actions=self.max_actions,deadline=deadline,document_path=self.document_path)
        initial=await scoped.initial();write_json(self.output/'initial-observation.json',initial)
        if not initial['success']:
            return {'loop':asdict(LoopResult('',stop_reason='initial_observation_error')),'agent_actions':0,'model_requests':0,'usage':{'api_calls':0},'tool_results':[]}
        registry=ToolRegistry();scoped.register_tools(registry)
        executor=NativeExecutor(registry,self.output)
        recorded=NativeRecordedModel(self.model,self.output,deadline,self.budget)
        metered=MeteredProvider(recorded,max_calls=self.max_requests)
        builder=NativePromptBuilder(ExperimentIdentityStore(NATIVE_SOUL),None,registry,prune_tools=False,memory_cfg={'recall_enabled':False})
        loop=AgenticLoop(metered,executor,builder,HistorySession());loop.MAX_STEPS=self.max_steps
        try:
            result=await loop.run(instruction+'\nInitial native observation:\n'+json.dumps(initial,ensure_ascii=False))
        except Exception as exc:
            result=LoopResult('',stop_reason='call_error')
            write_json(self.output/'chain-error.json',{'error':f'{type(exc).__name__}: {exc}'})
        usage={'api_calls':recorded.dispatched}
        actual_calls=metered.calls[:recorded.dispatched]
        if all('input_tokens' in c['usage'] and 'output_tokens' in c['usage'] for c in actual_calls):
            usage.update({key:sum(c['usage'][key] for c in actual_calls) for key in ['input_tokens','output_tokens']})
        report={'loop':asdict(result),'agent_actions':scoped.actions,'agent_save_applied':scoped.save_applied,'model_requests':recorded.dispatched,
                'usage':usage,'tool_results':executor.entries,
                'timing_semantics':'cooperative deadline; synchronous model/AX requests may overrun deadline'}
        write_json(self.output/'chain.json',report)
        return report


async def check_native_completion(document,expected,reopen_observation):
    """Read disk and an actual independently reopened AX view; never edit content."""
    result={'status':'unknown','disk_matches':None,'reopened_ax_matches':None}
    try:
        result['disk_matches']=Path(document).read_text(encoding='utf-8')==expected
        observation=await reopen_observation()
        if not observation.get('success'):raise RuntimeError(json.dumps(observation))
        areas=[t for t in observation['observation']['targets'] if t.get('role')=='AXTextArea']
        if len(areas)!=1:raise RuntimeError('expected exactly one independently reopened text area')
        result['reopened_ax_matches']=areas[0].get('value')==expected
        result['status']='passed' if result['disk_matches'] and result['reopened_ax_matches'] else 'failed'
    except Exception as exc:result['error']=f'{type(exc).__name__}: {exc}'
    return result


class NativeDocumentEnvironment:
    """Trusted setup/checker/cleanup operations for one dedicated TextEdit file."""
    def __init__(self,document,output):
        self.document=Path(document);self.output=Path(output)
        self.adapter=NativeAXAdapter(trace_path=self.output/'ax-trace.jsonl')
        self.events=[]

    def record(self,actor,operation,result):
        entry={'actor':actor,'operation':operation,'result':result}
        self.events.append(entry);append_json(self.output/'runtime-tools.jsonl',entry)
        return result

    async def setup(self):
        import asyncio
        import subprocess
        subprocess.run(['open','-a','TextEdit',str(self.document.resolve())],check=True,timeout=10)
        self.record('setup','open',{'success':True,'document':str(self.document.resolve())})
        await asyncio.sleep(.3)
        return await self.observe('setup')

    async def observe(self,actor):
        import asyncio
        scoped=ScopedNativeAdapter(self.adapter,'com.apple.TextEdit',self.document.name,document_path=self.document)
        for _ in range(30):
            result=await scoped.initial()
            if result.get('success'):return self.record(actor,'observe',result)
            if result.get('error') not in {'ScopeUnavailable'}:
                self.record(actor,'observe',result)
                raise RuntimeError(json.dumps(result))
            await asyncio.sleep(.1)
        self.record(actor,'observe',result)
        raise RuntimeError('dedicated document not uniquely available')

    async def close(self,actor):
        import asyncio
        observation=(await self.observe(actor))['observation']
        def unique(predicate):
            targets=[t for t in observation['targets'] if predicate(t)]
            if len(targets)!=1:raise RuntimeError('close control not uniquely observed')
            return targets[0]
        menu=unique(lambda t:t['role']=='AXMenuBarItem')
        result=self.record(actor,'open_document_menu',await self.adapter.act(observation['observation_id'],'press',menu['target_ref']))
        if not result.get('success'):raise RuntimeError(json.dumps(result))
        observation=result['observation']
        target=unique(lambda t:str(t.get('command','')).lower()=='w')
        result=self.record(actor,'close',await self.adapter.act(observation['observation_id'],'press',target['target_ref']))
        if result.get('action_applied') is not True:raise RuntimeError(json.dumps(result))
        for _ in range(30):
            identified=await self.adapter.windows('com.apple.TextEdit')
            if not identified.get('success'):
                self.record(actor,'close_probe',identified)
                raise RuntimeError(json.dumps(identified))
            if not any(w['title']==self.document.name for w in identified['windows']):
                return self.record(actor,'close_probe',{'success':True,'window_disappeared':True})
            await asyncio.sleep(.1)
        raise RuntimeError('dedicated window remained after close; may have unsaved edits')

    async def reread(self):
        import asyncio
        import subprocess
        await self.close('checker')
        subprocess.run(['open','-a','TextEdit',str(self.document.resolve())],check=True,timeout=10)
        self.record('checker','reopen',{'success':True})
        await asyncio.sleep(.3)
        return await self.observe('checker')

    async def cleanup(self):
        return await self.close('cleanup')


from core.evolution.agent_provider import KageChainProvider,run_sync


class NativeChainProvider(KageChainProvider):
    """Reusable generate_step provider for EvolutionRunner's budget/journal kernel."""
    RESERVATION_INPUT_CAP=1_000_000
    RESERVATION_OUTPUT_CAP=3_000

    def __init__(self,model_provider,task_def,*,environment_factory=NativeDocumentEnvironment,**kwargs):
        kwargs.setdefault('max_model_calls',10)
        super().__init__(model_provider,**kwargs)
        self.task_def=json.loads(json.dumps(task_def));self.environment_factory=environment_factory

    def _experiment_soul(self):return NATIVE_SOUL

    def cache_identity(self):
        return {**super().cache_identity(),'native_task':self.task_def,'max_loop_steps':8,'max_actions':16,'timeout_s':480}

    def metadata(self):
        return {**super().metadata(),'tool_registry':'ToolRegistry(dedicated native document only)',
                'agentic_loop_max_steps':8,'max_native_actions':16,'timeout_semantics':'cooperative inline deadline',
                'completion_checker':'trusted disk and close/reopen AX reread; no model claims'}

    def generate_step(self,task_def,step,history,workspace_dir):
        if task_def.get('task_id')!=self.task_def['task_id']:raise ValueError('native task identity mismatch')
        self.calls+=1
        output=run_sync(lambda:self._run(Path(workspace_dir)))
        self.call_log.append({'task_id':task_def['task_id'],'step':step})
        return output

    async def _run(self,workspace):
        start=time.monotonic()
        name=self.task_def['document_name']
        document=resolve_in_workspace(workspace,name)
        fixtures=self.task_def.get('initial_files',{})
        if name not in fixtures or not isinstance(fixtures[name],str):
            raise ValueError('dedicated document requires an initial text fixture')
        if not document.is_file() or document.read_text(encoding='utf-8')!=fixtures[name]:
            raise ValueError('dedicated document must match its prepared initial fixture')
        environment=self.environment_factory(document,workspace)
        report={'model_requests':0,'agent_actions':0,'usage':{'api_calls':0},'tool_results':[]}
        try:
            await environment.setup()
            chain=NativeModelChain(self._model.inner,environment.adapter,'com.apple.TextEdit',document.name,workspace,
                                   max_requests=self.max_model_calls,timeout_s=max(0,480-(time.monotonic()-start)),document_path=document)
            report=await chain.run(self.task_def['instruction'])
            checked=await check_native_completion(document,self.task_def['expected'],environment.reread)
            checked['agent_save_applied']=report.get('agent_save_applied',False)
            if checked['status']=='passed' and not checked['agent_save_applied']:
                checked['status']='failed'
                checked['reason']='no agent-issued app Save was applied'
            write_json(workspace/'completion.json',checked)
            # Closing a failed unsaved document can present a destructive prompt;
            # preserve that state and evidence instead of answering it.
            if checked['status'] in {'passed','failed'}:
                try:write_json(workspace/'cleanup.json',await environment.cleanup())
                except Exception as exc:write_json(workspace/'cleanup.json',{'success':False,'error':str(exc)})
        except Exception as exc:
            checked={'status':'unknown','error':f'{type(exc).__name__}: {exc}'}
            write_json(workspace/'completion.json',checked)
        chain_info={k:v for k,v in report.items() if k!='tool_results'}
        loop=report.get('loop',{})
        chain_info.update({'stop_reason':loop.get('stop_reason','initialization_error'),
                           'model_calls':report['model_requests'],'tool_calls':len(report['tool_results']),
                           'chain_steps':loop.get('steps',0)})
        chain_info['completion']=checked;chain_info['elapsed_s']=time.monotonic()-start
        return {'action':{'name':'finish'},'usage':report['usage'],'chain':chain_info,'tool_results':report['tool_results']}


class NativeEvaluator:
    @staticmethod
    def score(task_def,workspace_dir):
        try:checked=json.loads((Path(workspace_dir)/'completion.json').read_text())
        except (OSError,ValueError):return 0.0
        return 1.0 if checked.get('status')=='passed' and checked.get('disk_matches') is True and checked.get('reopened_ax_matches') is True else 0.0
