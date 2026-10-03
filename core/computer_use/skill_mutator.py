"""Use the E1 mutation journal and budget for browser-workflow proposals."""
import json

from core.computer_use.skills import BrowserSkillCatalog,descriptor_digest
from core.evolution.mutator import Mutator


def _compact_observation(observation):
    if not isinstance(observation,dict): return None
    return {key:observation[key] for key in ('observation_id','source','title','text') if key in observation} | {
        'targets':[{key:target[key] for key in ('target_ref','label','input_type','checked','value','operations','name')
                    if key in target} for target in observation.get('targets',[])]}


class BrowserWorkflowMutator(Mutator):
    target='workflow'

    def _messages(self,source,manifest,feedback):
        visible={'task_id':feedback['task_id'],'family':feedback['family'],
                 'instruction':feedback['instruction'],'source_kind':feedback['source_kind'],
                 'verification':feedback['verification'],
                 'initial_observation':_compact_observation(feedback['initial_observation']),
                 'actions':[{'actor':row['actor'],'tool':row['tool'],'arguments':row['arguments'],
                             'outcome':row['outcome'],'error':row['error'],'message':row['message'],
                             'observation':_compact_observation(row['observation'])}
                            for row in feedback['actions']],
                 'source_hashes':feedback['source_hashes']}
        messages=[{'role':'system','content':(
            'Propose ONE reusable browser workflow from observed actions. Return only a JSON object '
            'with hypothesis, skill_id, description, parameters (JSON Schema object), and workflow. '
            'Allowed workflow steps: {op:"for_each",items_param:"settings",step:{op:"ensure_checked",label_item:"label",checked_item:"checked"}}, '
            '{op:"ensure_checked",label_param,checked_param}, {op:"fill",label_param,value_param}, '
            '{op:"click",label_param}. No coordinates, node IDs, URL ports, fixed answer values, Python or JS. '
            'Use arguments for labels and desired values; workflow must call the save button. '
            'The teacher may have only saved an already edited page: use all actors, preserving provenance. '
            'The hypothesis is unverified until paired evaluation.')},
            {'role':'user','content':json.dumps({'parent_manifest':manifest,'demonstration':visible},ensure_ascii=False,separators=(',',':'))}]
        self._validate_request(messages)
        return messages

    def _validate_request(self,messages):
        if len(json.dumps(messages,ensure_ascii=False,separators=(',',':')).encode())>11000:
            raise ValueError('browser optimizer input exceeds 11KB message cap')

    def _validate_parent(self,source):
        BrowserSkillCatalog.from_bundle(source)

    def _apply_proposal(self,stage,manifest,proposal):
        descriptor={key:proposal[key] for key in ('skill_id','description','parameters','workflow')}
        descriptor['digest']=descriptor_digest(descriptor)
        updated={**manifest,'skills':[item for item in manifest['skills']
                                       if item['skill_id']!=descriptor['skill_id']]+[descriptor]}
        (stage/'manifest.json').write_text(json.dumps(updated,ensure_ascii=False,sort_keys=True,allow_nan=False))
        BrowserSkillCatalog.from_bundle(stage)
