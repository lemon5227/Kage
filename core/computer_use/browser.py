"""A page-scoped DOM adapter; model actions refer to observed node identities."""
import asyncio
import hashlib
import json
from pathlib import Path
import time
import uuid

from core.tool_registry import ToolDefinition

SNAPSHOT = r'''() => {
  const k = window.__kageDom || (window.__kageDom = {
    documentId: Date.now().toString(36) + Math.random().toString(36).slice(2), ids: new WeakMap(), next: 1, nodes: new Map()
  });
  k.nodes.clear();
  const targets = [];
  const elements = Array.from(document.querySelectorAll('button, a[href], input, textarea, [role="button"], [contenteditable="true"]'));
  const inViewport = el => {
    const r = el.getBoundingClientRect();
    return r.bottom > 0 && r.right > 0 && r.top < innerHeight && r.left < innerWidth;
  };
  elements.sort((a,b)=>Number(inViewport(b))-Number(inViewport(a)));
  let total = 0;
  for (const el of elements) {
    const box = el.getBoundingClientRect(), style = getComputedStyle(el);
    if (!box.width || !box.height || style.visibility === 'hidden' || style.display === 'none') continue;
    total++;
    if (targets.length >= 80) continue;
    let id = k.ids.get(el);
    if (!id) { id = 'e' + k.next++; k.ids.set(el, id); }
    k.nodes.set(id, el);
    const editable = !el.readOnly && (el.tagName === 'TEXTAREA' || el.isContentEditable ||
      (el.tagName === 'INPUT' && ['text','email','search','tel','url','password','number'].includes(el.type)));
    const label = el.getAttribute('aria-label') || (el.labels && Array.from(el.labels).map(l=>l.innerText).join(' ')) ||
      el.innerText || el.getAttribute('placeholder') || el.getAttribute('name') || el.tagName.toLowerCase();
    targets.push({target_ref:id, label:label.trim().slice(0,200), tag:el.tagName.toLowerCase(),
      operations:el.disabled ? [] : editable ? ['fill','click'] : ['click'],
      value:el.type === 'password' ? '' : String(el.value || '').slice(0,500),
      checked:!!el.checked, disabled:!!el.disabled,
      href:el.href || null, input_type:el.type || null, name:el.name || null,
      form_action:el.formAction || null, target:el.target || null,
      form_method:el.formMethod || null, form_target:el.formTarget || null,
      form_enctype:el.formEnctype || null,
      form:el.form ? {action:el.form.action,method:el.form.method,target:el.form.target,enctype:el.form.enctype} : null,
      role:el.getAttribute('role'), aria_expanded:el.getAttribute('aria-expanded'),
      bounds:[box.x,box.y,box.width,box.height].map(v=>Math.round(v))});
  }
  return {document_id:k.documentId, url:location.href, title:document.title,
    text:(document.body ? document.body.innerText : '').slice(0,5000), targets,
    truncated:total > 80 || (document.body && document.body.innerText.length > 5000),
    scroll:[Math.round(scrollX),Math.round(scrollY)], viewport:[innerWidth,innerHeight]};
}'''


def revision(snapshot):
    return hashlib.sha256(json.dumps(snapshot,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


TARGET_DEFAULTS = {
    'checked': False, 'disabled': False, 'href': None, 'input_type': None,
    'name': None, 'form_action': None, 'target': None, 'form_method': None,
    'form_target': None, 'form_enctype': None, 'form': None,
    'role': None, 'aria_expanded': None,
}


class BrowserAdapter:
    """One owned Page, one current observation; no global browser or selector API."""
    def __init__(self, page, trace_path=None, *, compact_observations=False, compact_format='compact-v1'):
        if compact_format not in {'compact-v1', 'compact-v2'}:
            raise ValueError('unsupported compact observation format')
        self.page = page
        self.surface_id = 'browser:' + uuid.uuid4().hex
        self.trace_path = Path(trace_path) if trace_path else None
        self.current = None
        self.compact_observations = compact_observations
        self.compact_format = compact_format
        self._lock = asyncio.Lock()

    def _model_observation(self):
        if not self.compact_observations:
            return self.current
        # Projection only: full snapshots remain authoritative for guards and
        # trace evidence. Never drop an actual value, destination or geometry.
        targets = [{key: value for key, value in target.items()
                    if key not in TARGET_DEFAULTS or value != TARGET_DEFAULTS[key]
                    or (self.compact_format == 'compact-v2' and key == 'checked'
                        and target.get('input_type') in {'checkbox', 'radio'})}
                   for target in self.current['targets']]
        return {**self.current, 'targets': targets, 'observation_format': self.compact_format}

    def _record(self, phase, start, **data):
        row = {'phase':phase,'elapsed_ms':round((time.monotonic()-start)*1000,3),**data}
        if self.trace_path:
            self.trace_path.parent.mkdir(parents=True,exist_ok=True)
            with self.trace_path.open('a') as stream:
                stream.write(json.dumps(row,ensure_ascii=False)+'\n')

    async def _observe(self):
        start=time.monotonic()
        snapshot=await self.page.evaluate(SNAPSHOT)
        self.current={'observation_id':uuid.uuid4().hex,'surface_id':self.surface_id,
                      'revision':revision(snapshot),'source':'dom',**snapshot}
        self._record('observe',start,observation=self.current)
        return self._model_observation()

    async def observe(self):
        async with self._lock:
            return await self._observe()

    async def _error(self, code, message, outcome='rejected'):
        payload={'success':False,'error':code,'message':message,'outcome':outcome}
        try:
            payload['observation']=await self._observe()
        except Exception as exc:
            payload['observation_error']=f'{type(exc).__name__}: {exc}'
        return payload

    async def open(self,url):
        async with self._lock:
            start=time.monotonic()
            try:
                if not isinstance(url,str) or not url.startswith(('http://','https://')):
                    result=await self._error('InvalidArgument','url must be HTTP or HTTPS')
                else:
                    await self.page.goto(url,wait_until='domcontentloaded',timeout=10000)
                    result={'success':True,'observation':await self._observe()}
            except Exception as exc:
                result=await self._error('BrowserError',f'{type(exc).__name__}: {exc}','tool_error')
            self._record('open',start,url=url,result=result)
            return result

    async def act(self,observation_id,operation,target_ref=None,value=None,amount=500,timeout_ms=2000):
        async with self._lock:
            start=time.monotonic()
            handle=None
            try:
                if operation not in {'click','fill','scroll','wait'}:
                    result=await self._error('InvalidArgument','unknown browser operation')
                elif not isinstance(timeout_ms,int) or isinstance(timeout_ms,bool) or not 1 <= timeout_ms <= 10000:
                    result=await self._error('InvalidArgument','timeout_ms must be 1..10000')
                elif not self.current or observation_id != self.current['observation_id']:
                    result=await self._error('StaleObservation','observe again before acting')
                else:
                    fresh=await self.page.evaluate(SNAPSHOT)
                    # Waiting only reads state and must tolerate the asynchronous
                    # changes it is waiting for. Mutating actions require freshness.
                    if operation != 'wait' and revision(fresh) != self.current['revision']:
                        result=await self._error('StaleObservation','DOM or node identity changed; no action applied')
                    elif operation in {'click','fill'}:
                        target=next((t for t in fresh['targets'] if t['target_ref']==target_ref),None)
                        if target is None or operation not in target['operations'] or (operation=='fill' and not isinstance(value,str)):
                            result=await self._error('InvalidArgument','target or value is incompatible with operation')
                        else:
                            handle=await self.page.evaluate_handle('(id)=>window.__kageDom.nodes.get(id)',target_ref)
                            element=handle.as_element()
                            if element is None or not await element.evaluate('(el)=>el.isConnected'):
                                result=await self._error('StaleObservation','observed node detached; no action applied')
                            else:
                                if operation=='fill': await element.fill(value,timeout=timeout_ms)
                                else: await element.click(timeout=timeout_ms)
                                result={'success':True,'observation':await self._observe()}
                    elif operation=='scroll':
                        if not isinstance(amount,int) or isinstance(amount,bool) or not -2000 <= amount <= 2000:
                            result=await self._error('InvalidArgument','scroll amount must be -2000..2000')
                        else:
                            await self.page.evaluate('(amount)=>window.scrollBy(0,amount)',amount)
                            result={'success':True,'observation':await self._observe()}
                    elif not isinstance(value,str) or not value:
                        result=await self._error('InvalidArgument','wait requires nonempty visible text')
                    else:
                        await self.page.wait_for_function('(text)=>document.body && document.body.innerText.includes(text)',arg=value,timeout=timeout_ms)
                        result={'success':True,'observation':await self._observe()}
            except Exception as exc:
                timeout=type(exc).__name__=='TimeoutError'
                result=await self._error('BrowserTimeout' if timeout else 'BrowserError',f'{type(exc).__name__}: {exc}','tool_error')
                result['action_applied'] = None if operation in {'click','fill'} else False
            finally:
                if handle:
                    try: await handle.dispose()
                    except Exception: pass  # navigation may already have disposed the handle
            self._record('wait' if operation=='wait' else 'execute',start,
                action={'observation_id':observation_id,'operation':operation,'target_ref':target_ref,'value':value,'amount':amount},result=result)
            return result

    def register_tools(self,registry,quota=None):
        format_hint = (' Compact-v1 omits false checked; v2 keeps checkbox/radio checked. Both omit false disabled and nulls.'
                       if self.compact_observations else '')
        def serialize(payload):
            return json.dumps(payload, ensure_ascii=False,
                              separators=(',', ':') if self.compact_observations else None)
        async def browser_observe():
            return serialize({'success':True,'observation':await self.observe()})
        async def browser_open(url):
            return serialize(await self.open(url))
        async def browser_act(observation_id,operation,target_ref=None,value=None,amount=500,timeout_ms=2000):
            return serialize(await self.act(observation_id,operation,target_ref,value,amount,timeout_ms))
        if quota is not None:
            browser_observe=quota.wrap(browser_observe)
            browser_open=quota.wrap(browser_open)
            browser_act=quota.wrap(browser_act)
        registry.register(ToolDefinition('browser_observe','Observe current DOM text and actionable node references.' + format_hint,
            {'type':'object','properties':{}},browser_observe))
        registry.register(ToolDefinition('browser_open','Navigate this browser session to an HTTP(S) URL and observe.' + format_hint,
            {'type':'object','properties':{'url':{'type':'string'}},'required':['url']},browser_open))
        registry.register(ToolDefinition('browser_act','Act on current observed nodes, or scroll/wait; returns a fresh observation.' + format_hint,
            {'type':'object','properties':{'observation_id':{'type':'string'},'operation':{'type':'string','enum':['click','fill','scroll','wait']},
             'target_ref':{'type':'string'},'value':{'type':'string'},'amount':{'type':'integer','minimum':-2000,'maximum':2000},
             'timeout_ms':{'type':'integer','minimum':1,'maximum':10000}},'required':['observation_id','operation']},browser_act))
