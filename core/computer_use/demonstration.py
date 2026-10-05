"""Capture committed DOM edits on one owned Page without executing actions."""
import asyncio
import json
from pathlib import Path
import time
import uuid

from core.computer_use.browser import SNAPSHOT, revision
from core.computer_use.task_environment import atomic_json


# Sampling happens synchronously in the Page. Only immutable captured snapshots
# cross the binding; Python never reads a later DOM to reconstruct an earlier edit.
_CAPTURE = r'''({snapshot, binding, surface, source}) => {
  const sampleBase = eval('(' + snapshot + ')');
  const formIds = new WeakMap(); let nextForm = 1;
  const visible = el => {const r=el.getBoundingClientRect(),s=getComputedStyle(el);
    return !!r.width && !!r.height && s.visibility!=='hidden' && s.display!=='none';};
  const label = el => (el.getAttribute('aria-label') ||
    (el.labels && Array.from(el.labels).map(l=>l.innerText).join(' ')) ||
    el.innerText || el.getAttribute('placeholder') || el.name || el.tagName.toLowerCase()).trim();
  const sample = () => {
    const s=sampleBase();
    s.demonstration_forms=Array.from(document.forms).filter(visible).map(form=>{
      if(!formIds.has(form))formIds.set(form,'f'+nextForm++);
      return {form_ref:formIds.get(form), controls:Array.from(form.elements).filter(visible).map(el=>({
        target_ref:window.__kageDom.ids.get(el)||null, label:label(el), tag:el.tagName.toLowerCase(),
        input_type:el.type||null, value:String(el.value||''), checked:!!el.checked,
        disabled:!!el.disabled, read_only:!!el.readOnly}))};
    });
    return {observation_id:Date.now().toString(36)+Math.random().toString(36).slice(2),surface_id:surface,source:'dom',...s};
  };
  const state={active:true,seq:0,pending:null,chain:Promise.resolve(),error:null,last:sample(),beforeEdit:null,beforeClick:null,
    deadline:Date.now()+900000,limitExceeded:false};
  const send = row => {
    const delivery=window[binding](row).catch(error=>{state.error=String(error);});
    state.chain=state.chain.then(()=>delivery);
  };
  const emit = (event,original,before,after,target,trusted,inputs=[]) => {
    const arguments={observation_id:before.observation_id,operation:event==='change'?'fill':'click',target_ref:target.target_ref};
    if(event==='change')arguments.value=target.value;
    const row={seq:++state.seq,time:Date.now()/1000,event,original_event:original,
      before,after,target,isTrusted:trusted,source,arguments,input_samples:inputs};
    send(row);state.last=after;
    if(state.seq>64){state.active=false;state.limitExceeded=true;}
  };
  const commit = () => {
    const pending=state.pending;if(!pending)return;state.pending=null;
    emit('change',pending.original,pending.before,pending.after,pending.target,pending.trusted,pending.inputs);
  };
  const expire = () => {
    if(!state.active)return;
    commit();state.active=false;state.limitExceeded=true;
    for(const event of ['beforeinput','pointerdown','keydown','input','change','click'])document.removeEventListener(event,handler,true);
  };
  const handler = e => {
    if(!state.active)return;
    if(Date.now()>=state.deadline){expire();return;}
    const el=e.target.closest('input,textarea,button,[role="button"],[contenteditable="true"]');if(!el)return;
    const fresh=sample(),target=fresh.targets.find(t=>t.target_ref===window.__kageDom.ids.get(el));if(!target)return;
    if(e.type==='beforeinput'){state.beforeEdit={target_ref:target.target_ref,observation:fresh};return;}
    if(e.type==='pointerdown'||(e.type==='keydown' && (e.key===' '||e.key==='Enter'))){
      state.beforeClick={target_ref:target.target_ref,observation:fresh};return;
    }
    if((e.type==='input'||e.type==='change') && target.operations.includes('fill')) {
      if(state.pending && state.pending.target.target_ref!==target.target_ref)commit();
      const before=state.beforeEdit && state.beforeEdit.target_ref===target.target_ref ?
        state.beforeEdit.observation : state.pending?state.pending.after:state.last;
      state.beforeEdit=null;
      const prior=before.targets.find(t=>t.target_ref===target.target_ref);
      if(!state.pending && prior && prior.value===target.value)return;
      if(!state.pending)state.pending={before,after:fresh,target,trusted:e.isTrusted,original:e.type,inputs:[]};
      const pending=state.pending;
      pending.inputs.push({time:Date.now()/1000,event:e.type,isTrusted:e.isTrusted,before,after:fresh});
      pending.after=fresh;pending.target=target;pending.trusted=e.isTrusted;
      send({kind:'input_sample',time:Date.now()/1000,event:e.type,isTrusted:e.isTrusted,source,before,after:fresh,target});
      if(e.type==='change')commit();
    } else if(e.type==='click') {
      commit();if(!state.active)return;
      if(target.input_type==='checkbox' || target.tag==='button' || target.input_type==='submit' || target.role==='button') {
        const before=state.beforeClick && state.beforeClick.target_ref===target.target_ref ?
          state.beforeClick.observation : state.last;
        state.beforeClick=null;
        // Checkbox click listeners run after native pre-activation toggles checked.
        // Use the captured previous DOM, including unmodified control values.
        emit('click','click',before,fresh,target,e.isTrusted);
      }
    }
  };
  for(const event of ['beforeinput','pointerdown','keydown','input','change','click'])document.addEventListener(event,handler,true);
  const timer=setTimeout(expire,900000);
  state.stop=async()=>{if(Date.now()>=state.deadline)expire();commit();state.active=false;clearTimeout(timer);
    for(const event of ['beforeinput','pointerdown','keydown','input','change','click'])document.removeEventListener(event,handler,true);
    await state.chain;return {seq:state.seq,error:state.error,limitExceeded:state.limitExceeded,final:sample()};};
  window.__kageDemonstration=state;return state.last;
}'''


def demonstration_tasks():
    """Fresh trusted task definitions; callers cannot mutate later sessions."""
    path = Path(__file__).resolve().parents[2] / 'eval/computer-use/browser-demonstration-dev.json'
    return {task['task_id']: task for task in json.loads(path.read_text())['tasks']}


class BrowserDemonstrationRecorder:
    def __init__(self, page, workspace, *, source_kind):
        if source_kind not in {'automation', 'human_declared'}:
            raise ValueError('source_kind must be automation or human_declared')
        self.page, self.workspace, self.source_kind = page, Path(workspace), source_kind
        self.surface_id = 'browser:' + uuid.uuid4().hex
        self.binding = '__kageDemonstration_' + uuid.uuid4().hex
        self.event_count = 0
        self.summary = None
        self.started = False
        self.capture_error = None
        self.started_at = None

    def _append(self, name, row):
        with (self.workspace / name).open('a') as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')

    def _observation(self, observation):
        # Match BrowserAdapter's authoritative full snapshot/revision semantics.
        snapshot = {k: v for k, v in observation.items()
                    if k not in {'observation_id', 'surface_id', 'source', 'revision'}}
        return {**observation, 'revision': revision(snapshot)}

    def _receive(self, source, row):
        if source['page'] != self.page or source['frame'] != self.page.main_frame:
            raise ValueError('demonstration event from unowned frame')
        row['before'] = self._observation(row['before'])
        row['after'] = self._observation(row['after'])
        if row.get('kind') == 'input_sample':
            try:
                self._append('demonstration-inputs.jsonl', row)
            except OSError as exc:
                self.capture_error = f'{type(exc).__name__}: {exc}'
                raise
            return
        self.event_count = row['seq']
        actor = 'automation' if self.source_kind == 'automation' else 'human'
        result = {'success': True, 'action_applied': True, 'observation': row['after']}
        try:
            self._append('demonstration-events.jsonl', row)
            self._append('actor-tools.jsonl', {'name': 'browser_act', 'arguments': row['arguments'],
                         'actor': actor, 'result': json.dumps(result, ensure_ascii=False),
                         'outcome': 'ok', 'success': True, 'seq': row['seq']})
            self._append('browser.jsonl', {'phase': 'execute', 'elapsed_ms': 0,
                         'action': row['arguments'], 'result': result, 'seq': row['seq']})
            self._append('trace.jsonl', {'event': 'demonstration_action', 'actor': actor,
                         'seq': row['seq'], 'action': row['arguments'], 'result': result})
        except OSError as exc:
            self.capture_error = f'{type(exc).__name__}: {exc}'
            raise

    async def start(self):
        if self.started:
            raise ValueError('demonstration already started')
        self.workspace.mkdir(parents=True, exist_ok=True)
        names = ('initial-observation.json', 'final-observation.json', 'demonstration-summary.json',
                 'demonstration-events.jsonl', 'actor-tools.jsonl', 'browser.jsonl', 'trace.jsonl',
                 'demonstration-inputs.jsonl')
        if any((self.workspace / name).exists() for name in names):
            raise ValueError('demonstration workspace already contains evidence')
        for name in names[3:]:
            (self.workspace / name).touch()
        await self.page.expose_binding(self.binding, self._receive)
        initial = await self.page.evaluate(_CAPTURE, {'snapshot': SNAPSHOT, 'binding': self.binding,
                      'surface': self.surface_id, 'source': self.source_kind})
        self.started, self.started_at = True, time.monotonic()
        initial = self._observation(initial)
        atomic_json(self.workspace / 'initial-observation.json', initial)
        self._append('browser.jsonl', {'phase': 'observe', 'elapsed_ms': 0, 'observation': initial})
        self._append('trace.jsonl', {'event': 'demonstration_started', 'source': self.source_kind})
        return initial

    async def stop(self):
        if self.summary is not None:
            return self.summary
        if not self.started:
            raise ValueError('demonstration not started')
        error, final = None, None
        try:
            captured = await asyncio.wait_for(self.page.evaluate('() => window.__kageDemonstration.stop()'), 5)
            final = self._observation(captured['final'])
            if captured['error'] or self.capture_error:
                error = 'CaptureFlushFailed'
            elif captured['seq'] != self.event_count:
                error = 'CaptureFlushFailed'
            elif captured['limitExceeded'] or self.event_count > 64:
                error = 'CaptureLimitExceeded'
            elif time.monotonic() - self.started_at > 900:
                error = 'CaptureLimitExceeded'
        except Exception as exc:
            error = 'CapturePageClosed' if self.page.is_closed() else 'CaptureFlushFailed'
            self.capture_error = f'{type(exc).__name__}: {exc}'
        self.summary = {'success': error is None, 'error': error, 'event_count': self.event_count,
                        'source_kind': self.source_kind, 'final_observation': final,
                        'capture_error': self.capture_error}
        try:
            if final is not None:
                atomic_json(self.workspace / 'final-observation.json', final)
                self._append('browser.jsonl', {'phase': 'observe', 'elapsed_ms': 0, 'observation': final})
            atomic_json(self.workspace / 'demonstration-summary.json', self.summary)
            self._append('trace.jsonl', {'event': 'demonstration_stopped', 'success': self.summary['success'],
                         'error': error, 'event_count': self.event_count})
        except OSError as exc:
            self.summary.update(success=False, error='CaptureFlushFailed', capture_error=str(exc))
        return self.summary
