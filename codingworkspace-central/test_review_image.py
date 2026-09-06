import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import prepare_context as prepare
from verify_package import verify


ROOT = Path(__file__).resolve().parent


class ReviewImageTests(unittest.TestCase):
    def test_lock_is_complete_and_hash_pinned(self):
        self.assertEqual(len(prepare.load_lock(ROOT / 'runtime-lock.json')['wheels']), 6)

    def test_lock_rejects_redirect_sources_and_missing_dependencies(self):
        original = json.loads((ROOT / 'runtime-lock.json').read_text())
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'lock.json'
            for change in ('url', 'missing', 'hash', 'duplicate', 'base'):
                lock = json.loads(json.dumps(original))
                if change == 'url': lock['wheels'][0]['url'] = 'https://example.org/tool.whl'
                if change == 'missing': lock['wheels'].pop()
                if change == 'hash': lock['wheels'][0]['sha256'] = 'not-a-hash'
                if change == 'duplicate': lock['wheels'].append(lock['wheels'][0])
                if change == 'base': lock['baseImage'] = 'python:latest'
                p.write_text(json.dumps(lock))
                with self.subTest(change=change), self.assertRaises(prepare.InputError):
                    prepare.load_lock(p)

    def repo(self, path):
        def git(*args):
            return subprocess.check_output(['git', '-C', str(path), *args], stderr=subprocess.DEVNULL).decode().strip()
        git('init', '-b', 'main')
        for name, text in {'codingworkspace/__init__.py': '__version__="1.0.1"\n',
                           'codingworkspace/RELEASE_SERIAL': '1\n', 'pyproject.toml': '[project]\n',
                           'private-admin-notes.txt': 'must not be exported\n'}.items():
            p = path / name; p.parent.mkdir(exist_ok=True); p.write_text(text)
        git('add', '.')
        git('-c', 'user.name=Test', '-c', 'user.email=test@local', 'commit', '-m', 'fixture')
        git('update-ref', 'refs/remotes/origin/main', 'HEAD')
        return git

    def test_exact_export_excludes_checkout_config_and_unrelated_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / 'repo'; repo.mkdir(); git = self.repo(repo)
            out = Path(tmp) / 'export'
            receipt = prepare.export_source(repo, git('rev-parse', 'HEAD'), out)
            self.assertEqual(set(receipt['files']), {'pyproject.toml', 'codingworkspace/__init__.py', 'codingworkspace/RELEASE_SERIAL'})
            self.assertFalse((out / '.git').exists())
            self.assertFalse((out / 'private-admin-notes.txt').exists())

    def test_source_rejects_dirty_side_branch_and_stale_packaging(self):
        for kind in ('dirty', 'side-branch', 'build', 'symlink'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                repo = Path(tmp) / 'repo'; repo.mkdir(); git = self.repo(repo)
                if kind == 'build':
                    (repo / 'build').mkdir(); (repo / 'build/stale.py').write_text('stale')
                elif kind == 'symlink': (repo / 'codingworkspace/escape.py').symlink_to('/etc/passwd')
                else: (repo / 'extra').write_text('changed')
                if kind != 'dirty':
                    git('add', '.')
                    git('-c', 'user.name=Test', '-c', 'user.email=test@local', 'commit', '-m', 'change')
                    if kind != 'side-branch': git('update-ref', 'refs/remotes/origin/main', 'HEAD')
                with self.assertRaises((prepare.InputError, subprocess.CalledProcessError)):
                    prepare.export_source(repo, git('rev-parse', 'HEAD'), Path(tmp) / 'out')

    def test_installed_package_rejects_changed_missing_and_extra_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp); pkg = site / 'codingworkspace'; pkg.mkdir()
            init = pkg / '__init__.py'; init.write_bytes(b'original')
            receipt = {'files': {'codingworkspace/__init__.py': hashlib.sha256(b'original').hexdigest()}}
            verify(receipt, site)
            init.write_bytes(b'stale')
            with self.assertRaises(ValueError): verify(receipt, site)
            init.unlink()
            with self.assertRaises(ValueError): verify(receipt, site)
            init.write_bytes(b'original'); (pkg / 'extra.py').write_text('extra')
            with self.assertRaises(ValueError): verify(receipt, site)

    def test_download_rejects_changed_wheel(self):
        row = prepare.load_lock(ROOT / 'runtime-lock.json')['wheels'][0]
        from io import BytesIO
        class Opener:
            def open(self, *args, **kwargs): return BytesIO(b'wrong bytes')
        with tempfile.TemporaryDirectory() as tmp, patch.object(prepare.urllib.request, 'build_opener', return_value=Opener()):
            with self.assertRaises(prepare.InputError):
                prepare.download_wheels({'wheels': [row]}, Path(tmp) / 'wheels')

    def test_workflow_has_no_automatic_private_build_or_promotion(self):
        # No YAML dependency on fork runners: check the fixed trust boundary.
        text = (ROOT.parent / '.github/workflows/build-cw-central.yml').read_text()
        for required in ("github.event_name == 'workflow_dispatch' &&", "github.repository == 'ubc/jupyter-images' &&",
                         "github.ref == 'refs/heads/main'", 'environment: codingworkspace-central-publication',
                         'main-only-independent-review-no-admin-bypass-v1', 'inputs.publish == true',
                         'verify_cw_candidate.py', '--provenance=mode=max', '--sbom=true',
                         'scan-local-image.sh', 'blocked-pending-reviewed-verifier'):
            self.assertIn(required, text)
        validate = text.split('  build:')[0]
        self.assertNotIn('secrets.', validate)
        self.assertNotIn('id-token: write', validate)
        for forbidden in ('pull_request_target', ':latest', ':preview', 'create-repository', 'kubectl', 'helm upgrade'):
            self.assertNotIn(forbidden, text)
        self.assertNotIn('codingworkspace-central/Dockerfile', text.replace('codingworkspace-central/Dockerfile.review', ''))
        self.assertFalse((ROOT / 'Dockerfile').exists(), 'ordinary-image discovery must not include this private image')


if __name__ == '__main__':
    unittest.main()
