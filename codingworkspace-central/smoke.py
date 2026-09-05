"""Run via stdin in the exact image with no network or runtime credentials."""
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

import psycopg
import codingworkspace
from codingworkspace.collaboration_service import CollaborationConfigurationError, load_audience_token_verifier
from codingworkspace.central_media_service import load_media_worker_verifier

assert os.getuid() == 10001
assert sys.version_info[:2] == (3, 12)
assert psycopg.pq.__impl__ == 'binary'
assert importlib.metadata.version('codingworkspace') == codingworkspace.__version__
for name in ('git', 'ssh', 'gh', 'opencode', 'jupyter', 'jupyterhub'):
    assert shutil.which(name) is None, name
assert not os.access('/opt/codingworkspace', os.W_OK)
assert not os.access(Path(codingworkspace.__file__), os.W_OK)
assert not Path('/inputs').exists()
eps = {e.name: e.value for e in importlib.metadata.distribution('codingworkspace').entry_points}
assert eps['codingworkspace-central-media'] == 'codingworkspace.central_media_service:main'
assert eps['codingworkspace-collaboration'] == 'codingworkspace.collaboration_service:main'
for factory, settings in (
    (load_audience_token_verifier, SimpleNamespace(verifier_factory='')),
    (load_media_worker_verifier, SimpleNamespace(worker_verifier_factory='', allow_static_development_worker_verifier=False)),
):
    try:
        factory(settings)
    except CollaborationConfigurationError:
        pass
    else:
        raise AssertionError('missing verifier did not fail closed')
receipt = json.loads(Path('/opt/codingworkspace/source-receipt.json').read_text())
assert receipt['commit'] == sys.argv[1]
print(json.dumps({'kind': 'CentralMediaReviewSmoke', 'commit': receipt['commit'],
                  'version': codingworkspace.__version__, 'status': 'passed',
                  'studentActivation': 'blocked-pending-reviewed-verifier'}))
