"""Versioned recovery source, executed by the existing sandbox in scratch space."""
import ast
import hashlib
import json
from pathlib import Path
import tempfile

from core.evolution.sandbox import ProcessSkillRunner

ADAPTER = b'''\n\ndef run(arguments, context):
    return recover(arguments["error"], arguments["history"], arguments["checkpoints"])
'''


def validate_recovery_source(source):
    tree = ast.parse(source)
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'recover']
    if len(functions) != 1:
        raise ValueError('source must define exactly one recover(error, history, checkpoints)')
    args = functions[0].args
    if [a.arg for a in args.args] != ['error', 'history', 'checkpoints'] or args.posonlyargs or args.kwonlyargs or args.vararg or args.kwarg or args.defaults:
        raise ValueError('recover signature must be (error, history, checkpoints)')


class RecoveryPolicy:
    def __init__(self, path, source, digest, runner, skills):
        self.path, self.source, self.digest = path, source, digest
        self.runner, self.skills, self.events = runner, skills, []

    @classmethod
    def from_bundle(cls, bundle, runner=None, skill_catalog=None):
        root = Path(bundle).resolve()
        manifest = json.loads((root / 'manifest.json').read_text())
        if manifest.get('version') != 1:
            raise ValueError('unsupported bundle version')
        module = manifest['modules']['recovery']
        filename, function = module['entrypoint'].split(':')
        path = (root / filename).resolve()
        if not path.is_relative_to(root) or path.suffix != '.py' or function != 'recover':
            raise ValueError('invalid recovery entrypoint')
        source = path.read_bytes()
        digest = hashlib.sha256(source).hexdigest()
        if module.get('digest') != digest:
            raise ValueError('recovery source digest mismatch')
        validate_recovery_source(source)
        descriptors = skill_catalog.search('', limit=3)['skills'] if skill_catalog else []
        skills = [{**item, 'description': item['description'][:200]} for item in descriptors]
        return cls(path, source, digest, runner or ProcessSkillRunner(), skills)

    def identity(self):
        return {'module_path': str(self.path), 'module_sha256': self.digest,
                'adapter_sha256': hashlib.sha256(ADAPTER).hexdigest(),
                'executed_source_sha256': hashlib.sha256(self.source + ADAPTER).hexdigest(),
                'runner': type(self.runner).__name__, 'timeout_s': self.runner.timeout_s,
                'max_output_bytes': self.runner.max_output_bytes,
                'image_id': getattr(self.runner, 'image_id', None),
                'skills': self.skills}

    def recover(self, error, history, checkpoints):
        if hashlib.sha256(self.path.read_bytes()).hexdigest() != self.digest:
            raise ValueError('recovery source digest changed before execution')
        request = {'error': {**error, 'available_skills': self.skills}, 'history': history, 'checkpoints': checkpoints}
        # Generated policy code returns a decision only. The actual task directory
        # is not mounted; the AgenticLoop/ToolExecutor executes any accepted action.
        with tempfile.TemporaryDirectory(prefix='kage-recovery-') as scratch:
            result = self.runner.run(self.source + ADAPTER, 'run', request, Path(scratch))
        event = {**self.identity(), 'worker_source_path': '/runtime/skill.py' if hasattr(self.runner, 'image_id') else 'temporary/skill.py',
                 'input': request, 'result': result}
        self.events.append(event)
        return result
