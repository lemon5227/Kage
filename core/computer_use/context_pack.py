"""Keep current DOM intact; archive stale snapshots without removing actions/errors."""
import copy
import hashlib
import json
from pathlib import Path
from core.model_provider import ModelProvider

INITIAL='Initial browser observation supplied by runtime:\n'


def _archive(value,workspace):
    raw=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
    digest=hashlib.sha256(raw).hexdigest()
    relative=Path('context-evidence')/(digest+'.json')
    path=workspace/relative
    path.parent.mkdir(parents=True,exist_ok=True)
    if not path.exists(): path.write_bytes(raw)
    elif path.read_bytes()!=raw: raise ValueError('context evidence hash collision or corrupted file')
    return {'path':str(relative),'sha256':digest}


def _lines(obs):
    return [line.strip() for line in str(obs.get('text') or '').splitlines() if line.strip()]


def pack_browser_messages(messages,workspace,keep_text=False):
    """keep_text (C4 round 2): an archived page keeps the text lines the latest page no longer shows (capped), so
    details the student expanded earlier (hotel ratings) survive packing; round 1 lost them (web_catalog 7 -> 4/18)."""
    workspace=Path(workspace)
    packed=copy.deepcopy(messages)
    source=_archive(messages,workspace)
    observed=[]
    for index,message in enumerate(packed):
        content=message.get('content')
        if not isinstance(content,str): continue
        initial=message.get('role')=='user' and INITIAL in content
        browser_tool=message.get('role')=='tool' and content.startswith(('[Tool: browser_','[Tool Error: browser_',
                                                                          '[Tool: skill_call]','[Tool Error: skill_call]'))
        if not (initial or browser_tool): continue
        try:
            prefix,raw=content.rsplit(INITIAL,1) if initial else (content[:content.index('{')],content[content.index('{'):])
            payload=json.loads(raw)
            obs=payload if initial else payload.get('observation')
            if not isinstance(obs,dict) or obs.get('source')!='dom' or not obs.get('observation_id') or 'targets' not in obs: continue
        except (ValueError,AttributeError): continue
        observed.append((index,initial,prefix,payload,obs))
    latest=set(_lines(observed[-1][4])) if observed else set()
    for index,initial,prefix,payload,obs in observed[:-1]:
        reference=_archive(obs,workspace)
        if keep_text:
            gone=[line for line in dict.fromkeys(_lines(obs)) if line not in latest]
            text='\n'.join(gone)[:1200]
            if text: reference={**reference,'text_no_longer_shown':text}
        if initial:
            content=prefix+'Archived initial browser observation (use latest full DOM):\n'+json.dumps(reference,separators=(',',':'))
        else:
            payload.pop('observation')
            payload['observation_archived']=reference
            content=prefix+json.dumps(payload,ensure_ascii=False,separators=(',',':'))
        packed[index]['content']=content
    stats={'source_path':source['path'],'source_sha256':source['sha256'],
           'archived_observations':max(0,len(observed)-1),
           'before_message_bytes':len(json.dumps(messages).encode()),
           'after_message_bytes':len(json.dumps(packed).encode())}
    return packed,stats


class BrowserContextProvider(ModelProvider):
    def __init__(self,model,workspace,*,trace_name='teacher-context-pack.jsonl',keep_text=False):
        self.model,self.workspace=model,Path(workspace)
        self.trace_name=trace_name
        self.keep_text=keep_text

    def generate(self,messages,**kwargs):
        packed,stats=pack_browser_messages(messages,self.workspace,keep_text=self.keep_text)
        with (self.workspace/self.trace_name).open('a') as stream:
            stream.write(json.dumps(stats)+'\n')
        return self.model.generate(messages=packed,**kwargs)
