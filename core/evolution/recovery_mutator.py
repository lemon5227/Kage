"""Recovery code proposals reuse E1 billing, repairs, immutable bundles and journal."""
import hashlib
import json

from core.evolution.bundle import RecoveryPolicy, validate_recovery_source
from core.evolution.mutator import Mutator, _visible_feedback
from core.evolution.skills import SkillCatalog


class RecoveryMutator(Mutator):
    target = 'recovery'

    def _validate_request(self, messages):
        size = len(json.dumps(messages, ensure_ascii=False).encode('utf-8'))
        if size > 12_000:
            raise ValueError('recovery teacher request exceeds 12000 bytes')

    def _validate_parent(self, source):
        super()._validate_parent(source)
        RecoveryPolicy.from_bundle(source)

    def _messages(self, source, manifest, feedback):
        policy = RecoveryPolicy.from_bundle(source)
        catalog = SkillCatalog.from_bundle(source)
        return [{'role':'system', 'content': (
            'Modify the agent recovery policy SOURCE CODE from an observed dev failure. '
            'Return ONLY JSON with hypothesis and code. Standard-library Python only. '
            'Define exactly recover(error, history, checkpoints)->dict. '
            'The policy is called every time the model stops calling tools, including ordinary successful finishes. '
            'error contains reason, trigger (finish_attempt or finish_after_tool_error), goal, final_text, '
            'written_files, last_tool_success, tool_errors and available_skills (runtime descriptors including IDs/digests/schemas). '
            'Return stop whenever the goal is already satisfied or no available skill applies to the goal; '
            'return {"action":"request_help","reason":...} when the task needs a capability no skill provides. '
            'history contains actual tool rows {name, arguments, result, success, outcome}; result is a JSON string. '
            'The module runs in scratch space, not the task directory. Only return {"action":"stop"}, request_help, or '
            '{"action":"switch_tool","tool_call":{"name":"skill_call","arguments":{"skill_id":...,'
            '"digest":...,"arguments":{...}}}}. The original executor applies the returned action. '
            'Use observed read_file path/content to infer target path and function name, and match a reusable '
            'available skill. Read runtime IDs/digests, do not hardcode example filenames, function names, '
            'IDs, hidden answers or job values. Do not change skills. Treat candidate improvement as unverified.'
        )}, {'role':'user','content':json.dumps({
            'baseline_recovery_source':policy.source.decode(),
            'available_skills':catalog.search('', limit=3)['skills'],
            'failure':_visible_feedback({key: feedback[key] for key in
                        ('task_id','instruction','failure_reason','trace') if key in feedback})
        }, ensure_ascii=False)}]

    def _apply_proposal(self, stage, manifest, proposal):
        code = proposal['code']
        validate_recovery_source(code)
        digest = hashlib.sha256(code.encode()).hexdigest()
        filename = 'recovery-' + digest + '.py'
        (stage / filename).write_text(code)
        updated = {**manifest, 'modules': {**manifest.get('modules', {}),
                   'recovery': {'entrypoint': filename + ':recover', 'digest': digest}}}
        (stage / 'manifest.json').write_text(json.dumps(updated, sort_keys=True, allow_nan=False))
        self._validate_parent(stage)
