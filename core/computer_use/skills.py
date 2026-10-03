"""Page-scoped, declarative browser workflows (manifest v2)."""
import hashlib
import json
from pathlib import Path
import re
import uuid

from jsonschema import Draft202012Validator,ValidationError
from core.tool_registry import ToolDefinition


def descriptor_digest(descriptor):
    data={'version':2,'kind':'browser_workflow',**{key:descriptor[key] for key in
          ('skill_id','description','parameters','workflow')}}
    return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def _validate_workflow(workflow):
    if not isinstance(workflow,list) or not 1<=len(workflow)<=16:
        raise ValueError('workflow requires 1..16 steps')
    for step in workflow:
        if not isinstance(step,dict): raise ValueError('invalid workflow step')
        op=step.get('op')
        allowed={'ensure_checked':{'op','label_param','checked_param'},
                 'click':{'op','label_param'},
                 'fill':{'op','label_param','value_param'},
                 'for_each':{'op','items_param','step'}}
        if op not in allowed or set(step)-allowed[op]: raise ValueError('unsupported workflow step')
        if op=='for_each':
            inner=step.get('step')
            if (not isinstance(inner,dict) or inner.get('op')!='ensure_checked'
                    or set(inner)!={'op','label_item','checked_item'}):
                raise ValueError('for_each supports one nonnested ensure_checked step')
            if not isinstance(step.get('items_param'),str): raise ValueError('invalid items_param')
        elif not isinstance(step.get('label_param'),str):
            raise ValueError('missing label_param')
        if op=='ensure_checked' and not isinstance(step.get('checked_param'),str):
            raise ValueError('missing checked_param')
        if op=='fill' and not isinstance(step.get('value_param'),str):
            raise ValueError('missing value_param')


class BrowserPrimitiveQuota:
    """Shared browser-tool limit for raw and nested skill calls in one live Page."""
    def __init__(self,limit=16):
        self.limit=limit
        self.used=0

    def wrap(self,handler):
        async def bounded(**kwargs):
            if self.used>=self.limit:
                return json.dumps({'success':False,'error':'PrimitiveQuotaExceeded',
                                   'message':f'browser primitive limit {self.limit} reached','outcome':'rejected'})
            self.used+=1
            return await handler(**kwargs)
        return bounded


class BrowserSkillCatalog:
    def __init__(self,entries): self._entries=entries

    @property
    def digests(self): return {skill_id:entry['digest'] for skill_id,entry in self._entries.items()}

    @classmethod
    def from_bundle(cls,path):
        manifest=json.loads((Path(path)/'manifest.json').read_text())
        if manifest.get('version')!=2 or manifest.get('kind')!='browser_workflow' or not isinstance(manifest.get('skills'),list):
            raise ValueError('unsupported browser workflow manifest')
        entries={}
        for item in manifest['skills']:
            if not isinstance(item,dict): raise ValueError('invalid skill descriptor')
            skill_id=item.get('skill_id')
            if not isinstance(skill_id,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}',skill_id) or skill_id in entries:
                raise ValueError('invalid or duplicate skill_id')
            if not isinstance(item.get('description'),str) or not item['description'].strip():
                raise ValueError('missing skill description')
            schema=item.get('parameters')
            if not isinstance(schema,dict) or schema.get('type')!='object': raise ValueError('skill parameters must be object schema')
            Draft202012Validator.check_schema(schema)
            _validate_workflow(item.get('workflow'))
            expected=descriptor_digest(item)
            if item.get('digest')!=expected: raise ValueError(f'skill digest mismatch: {skill_id}')
            entries[skill_id]=json.loads(json.dumps(item))
        return cls(entries)

    def search(self,query,limit=5):
        # Queries describe tasks, including values a reusable skill deliberately
        # does not hardcode. Rank partial word overlap instead of requiring every
        # task-specific word to occur in the descriptor. This is lexical recall,
        # not semantic/embedding retrieval.
        words=lambda text:set(re.findall(r'[^\W_]+',str(text).casefold()))
        terms=words(query)
        matches=[]
        for skill_id,item in sorted(self._entries.items()):
            score=2*len(terms & words(skill_id))+len(terms & words(item['description']))
            if not terms or score:
                matches.append((score,skill_id,{key:item[key] for key in ('skill_id','description','parameters','digest')}))
        matches.sort(key=lambda row:(-row[0],row[1]))
        return {'success':True,'skills':[row[2] for row in matches[:max(1,min(10,limit))]]}

    async def call(self,skill_id,digest,arguments,adapter,executor,quota,parent_call_id):
        item=self._entries.get(skill_id)
        if item is None: return {'success':False,'error':'UnknownSkill','outcome':'rejected'}
        if digest!=item['digest']: return {'success':False,'error':'DigestMismatch','outcome':'rejected'}
        try: Draft202012Validator(item['parameters']).validate(arguments)
        except ValidationError as exc:
            return {'success':False,'error':'InvalidArgument','message':exc.message,'outcome':'rejected'}
        if not isinstance(arguments,dict):
            return {'success':False,'error':'InvalidArgument','message':'arguments must be object','outcome':'rejected'}
        steps=[]
        latest=None
        async def observe():
            result=await executor.execute('browser_observe',{})
            try: payload=json.loads(result.result)
            except (TypeError,ValueError): payload={}
            return result,payload
        result,payload=await observe()
        if not result.success:
            return {'success':False,'outcome':'not_applied','error':result.error_type or 'ObserveFailed',
                    'message':result.error_message,'steps':steps,'observation':payload.get('observation')}
        latest=payload.get('observation')
        if not isinstance(latest,dict):
            return {'success':False,'outcome':'not_applied','error':'ObserveFailed',
                    'message':'browser observation unavailable','steps':steps}
        expanded=[]
        for step in item['workflow']:
            if step['op']=='for_each':
                values=arguments.get(step['items_param'])
                if not isinstance(values,list) or len(values)>8:
                    return {'success':False,'outcome':'not_applied','error':'InvalidArgument','message':'for_each requires at most 8 items',
                            'steps':steps,'observation':latest}
                inner=step['step']
                for value in values:
                    if not isinstance(value,dict):
                        return {'success':False,'outcome':'not_applied','error':'InvalidArgument','message':'invalid item',
                                'steps':steps,'observation':latest}
                    expanded.append(('ensure_checked',value.get(inner['label_item']),value.get(inner['checked_item'])))
            else:
                expanded.append((step['op'],arguments.get(step['label_param']),
                                 arguments.get(step.get('checked_param') or step.get('value_param'))))
        if len(expanded)>16:
            return {'success':False,'outcome':'not_applied','error':'PrimitiveQuotaExceeded',
                    'message':'workflow exceeds 16 expanded steps','steps':steps,'observation':latest}
        for op,label,value in expanded:
            if not isinstance(label,str) or not label:
                return {'success':False,'outcome':'not_applied','error':'InvalidArgument','message':'missing semantic label',
                        'steps':steps,'observation':latest}
            for attempt in range(2):
                matches=[t for t in latest.get('targets',[]) if t['label']==label]
                if len(matches)!=1:
                    return {'success':False,'outcome':'not_applied','error':'AmbiguousTarget' if matches else 'NodeNotFound',
                            'message':f'{label}: expected exactly one visible target','steps':steps,'observation':latest}
                target=matches[0]
                if op=='ensure_checked':
                    if target.get('input_type')!='checkbox' or not isinstance(value,bool):
                        return {'success':False,'outcome':'not_applied','error':'InvalidArgument','message':'expected checkbox and bool',
                                'steps':steps,'observation':latest}
                    if bool(target.get('checked',False))==value:
                        steps.append({'op':op,'label':label,'outcome':'unchanged'})
                        break
                    action='click'
                elif op=='fill':
                    if not isinstance(value,str) or 'fill' not in target.get('operations',[]):
                        return {'success':False,'outcome':'not_applied','error':'InvalidArgument','message':'expected fillable field and string',
                                'steps':steps,'observation':latest}
                    action='fill'
                else: action='click'
                args={'observation_id':latest['observation_id'],'operation':action,'target_ref':target['target_ref']}
                if action=='fill':args['value']=value
                result=await executor.execute('browser_act',args)
                try: payload=json.loads(result.result)
                except (TypeError,ValueError): payload={}
                fresh=payload.get('observation')
                if isinstance(fresh,dict): latest=fresh
                elif result.success or result.outcome in {'tool_error','error'}:
                    # A click may have happened before observation failed. The
                    # previous DOM must not be advertised as current state.
                    latest=None
                steps.append({'op':op,'label':label,'outcome':result.outcome,'parent_call_id':parent_call_id,
                              'observation_id':latest.get('observation_id') if isinstance(latest,dict) else None})
                if result.success and latest is None:
                    return {'success':False,'outcome':'not_applied','error':'ObservationMissing',
                            'message':'action result has no fresh observation; observe before continuing',
                            'action_applied':None,'steps':steps,'observation':None}
                if result.success: break
                stale_safe=(payload.get('error')=='StaleObservation' and isinstance(fresh,dict)
                            and payload.get('action_applied') is not True and
                            ('no action applied' in str(payload.get('message')) or
                             'observe again before acting' in str(payload.get('message'))))
                if attempt==0 and stale_safe: continue
                return {'success':False,'outcome':'not_applied','error':result.error_type or 'BrowserActionFailed',
                        'message':result.error_message,'action_applied':payload.get('action_applied'),
                        'steps':steps,'observation':latest}
        return {'success':True,'outcome':'unchanged' if all(s['outcome']=='unchanged' for s in steps) else 'ok',
                'skill_id':skill_id,'digest':digest,'parent_call_id':parent_call_id,
                'steps':steps,'observation':latest,'primitive_calls':quota.used}

    def register_tools(self,registry,adapter,executor,workspace,quota):
        if registry.has_tool('skill_search') or registry.has_tool('skill_call'):
            raise ValueError('browser skill tool name collision')
        def search(query,limit=5): return json.dumps(self.search(query,limit),ensure_ascii=False)
        async def call(skill_id,digest,arguments):
            parent_call_id=uuid.uuid4().hex
            executor.skill_context={'skill_id':skill_id,'digest':digest,'parent_call_id':parent_call_id}
            try:
                return json.dumps(await self.call(skill_id,digest,arguments,adapter,executor,quota,parent_call_id),ensure_ascii=False)
            finally:
                executor.skill_context=None
        registry.register(ToolDefinition('skill_search','Discover browser workflow skills, schemas and digests.',
            {'type':'object','properties':{'query':{'type':'string'},'limit':{'type':'integer','minimum':1,'maximum':10}},'required':['query']},search))
        registry.register(ToolDefinition('skill_call','Run a browser workflow on this live page using its exact digest.',
            {'type':'object','properties':{'skill_id':{'type':'string'},'digest':{'type':'string'},
             'arguments':{'type':'object'}},'required':['skill_id','digest','arguments']},call))
