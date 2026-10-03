"""Browser optimizer proposals use the existing budget, journal and immutable bundle."""
import json
from pathlib import Path

from core.computer_use.skill_mutator import BrowserWorkflowMutator
from core.computer_use.skills import BrowserSkillCatalog
from core.evolution.budget import BudgetConfig,BudgetTracker
from core.evolution.contracts import Candidate
from core.evolution.journal import Journal
from core.evolution.mutator import bundle_digest
from core.model_provider import ModelResponse


class ProposalModel:
    def __init__(self,proposal): self.proposal,self.calls=proposal,0
    def generate(self,**kwargs):
        self.calls+=1
        wire=json.dumps(kwargs['messages'])
        assert 'HIDDEN_CHECKER' not in wire and 'scoring_criteria' not in wire
        return ModelResponse(text=json.dumps(self.proposal),usage={'input_tokens':300,'output_tokens':100})


def test_browser_mutator_proposes_v2_bundle_and_restart_is_free(tmp_path):
    parent_dir=tmp_path/'parent';parent_dir.mkdir()
    (parent_dir/'manifest.json').write_text('{"version":2,"kind":"browser_workflow","skills":[]}')
    parent=Candidate('empty',(),'workflow',str(parent_dir),bundle_digest(parent_dir))
    feedback={'task_id':'preferences_dev','family':'preferences','instruction':'Enable Email and save',
              'source_kind':'mixed_student_teacher','verification':'legacy_final_verified',
              'initial_observation':{'source':'dom','targets':[{'target_ref':'e1','label':'Email','checked':False}]},
              'actions':[{'actor':'student','tool':'browser_act','arguments':{'operation':'click','target_ref':'e1'},
                          'outcome':'ok','error':None,'message':None,'observation':None}],
              'source_hashes':{'actor-tools.jsonl':'abc'}}
    proposal={'hypothesis':'A generic checkbox rule should avoid toggling already correct inputs.',
              'skill_id':'set_checkbox','description':'Set one checkbox and save',
              'parameters':{'type':'object','properties':{'label':{'type':'string'},'checked':{'type':'boolean'},
                                                   'save_label':{'type':'string'}},
                            'required':['label','checked','save_label'],'additionalProperties':False},
              'workflow':[{'op':'ensure_checked','label_param':'label','checked_param':'checked'},
                          {'op':'click','label_param':'save_label'}]}
    model=ProposalModel(proposal)
    budget=BudgetTracker(BudgetConfig(max_api_calls=3),tmp_path/'budget.sqlite')
    journal=Journal(tmp_path/'journal.sqlite')
    mutator=BrowserWorkflowMutator(model,budget,journal,tmp_path/'mutation')
    child=mutator.propose(parent,feedback)
    assert child.target=='workflow' and child.parent_ids==(parent.candidate_id,)
    assert BrowserSkillCatalog.from_bundle(child.bundle_path).digests['set_checkbox']
    assert model.calls==1 and budget.total_api_calls==1
    again=BrowserWorkflowMutator(model,budget,journal,tmp_path/'mutation').propose(parent,feedback)
    assert again==child and model.calls==1 and budget.total_api_calls==1
