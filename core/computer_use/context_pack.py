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


def pack_browser_messages(messages,workspace):
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
    for index,initial,prefix,payload,obs in observed[:-1]:
        reference=_archive(obs,workspace)
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
    def __init__(self,model,workspace):
        self.model,self.workspace=model,Path(workspace)

    def generate(self,messages,**kwargs):
        packed,stats=pack_browser_messages(messages,self.workspace)
        with (self.workspace/'teacher-context-pack.jsonl').open('a') as stream:
            stream.write(json.dumps(stats)+'\n')
        return self.model.generate(messages=packed,**kwargs)
