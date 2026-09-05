#!/usr/bin/env python3
"""Export exact course source and hash-locked public wheels without credentials."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import urllib.parse
import urllib.request


class InputError(ValueError):
    pass


def git(repo: Path, *args: str) -> bytes:
    return subprocess.check_output(['git', '-C', str(repo), *args])


def load_lock(path: Path) -> dict:
    lock = json.loads(path.read_text())
    if lock.get('schemaVersion') != 1 or lock.get('pythonVersion') != '3.12':
        raise InputError('expected the reviewed Python 3.12 lock schema')
    if not re.fullmatch(r'docker.io/library/python@sha256:[0-9a-f]{64}', lock.get('baseImage', '')):
        raise InputError('base must be the official Python image pinned by digest')
    names, files = set(), set()
    expected = {'setuptools': 'build', 'wheel': 'build', 'packaging': 'build',
                'psycopg': 'runtime', 'psycopg-binary': 'runtime', 'typing-extensions': 'runtime'}
    for row in lock.get('wheels', []):
        name, filename = row.get('name'), row.get('file', '')
        if name not in expected or row.get('role') != expected[name] or name in names:
            raise InputError('wheel roles must match the complete reviewed dependency set')
        if not re.fullmatch(r'[A-Za-z0-9_.+-]+\.whl', filename) or filename in files:
            raise InputError('wheel filenames must be unique plain basenames')
        url = urllib.parse.urlsplit(row.get('url', ''))
        if (url.scheme != 'https' or url.netloc != 'files.pythonhosted.org' or
                url.query or url.fragment or PurePosixPath(url.path).name != filename):
            raise InputError('wheel URL must name the exact public PyPI file without credentials')
        if not re.fullmatch(r'[0-9a-f]{64}', row.get('sha256', '')):
            raise InputError('wheel hash must be SHA-256')
        names.add(name)
        files.add(filename)
    if names != set(expected):
        raise InputError('dependency lock is incomplete')
    return lock


def export_source(repo: Path, commit: str, output: Path) -> dict:
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise InputError('source must be a full lowercase commit SHA')
    if git(repo, 'rev-parse', 'HEAD').decode().strip() != commit:
        raise InputError('source checkout does not match the requested commit')
    if git(repo, 'status', '--porcelain', '--untracked-files=all'):
        raise InputError('source checkout must be clean')
    subprocess.run(['git', '-C', str(repo), 'merge-base', '--is-ancestor', commit,
                    'refs/remotes/origin/main'], check=True)
    # git archive avoids BuildKit's .git transport behaviour. No checkout config,
    # deploy key, history, or untracked file is sent to a Docker build.
    snapshot = git(repo, 'archive', '--format=tar', commit)
    with tarfile.open(fileobj=io.BytesIO(snapshot)) as archive:
        members = archive.getmembers()
        if any(m.name.split('/')[0] in {'build', 'dist'} or
               any(p.endswith('.egg-info') for p in PurePosixPath(m.name).parts)
               for m in members):
            raise InputError('source commit tracks stale packaging output')
        hashes = {}
        for member in members:
            name = member.name
            if name != 'pyproject.toml' and not name.startswith('codingworkspace/'):
                continue
            path = PurePosixPath(name)
            if path.is_absolute() or '..' in path.parts or '\\' in name:
                raise InputError('source path is unsafe')
            if member.isdir():
                continue
            if not member.isfile() or member.size > 32 * 1024 * 1024:
                raise InputError('source must contain bounded regular package files')
            if '__pycache__' in path.parts or name.endswith(('.pyc', '.pyo')):
                raise InputError('source commit tracks bytecode')
            content = archive.extractfile(member).read()
            target = output / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            hashes[name] = hashlib.sha256(content).hexdigest()
    if not {'pyproject.toml', 'codingworkspace/__init__.py', 'codingworkspace/RELEASE_SERIAL'} <= hashes.keys():
        raise InputError('source archive is missing the application package')
    return {'schemaVersion': 1, 'commit': commit, 'files': hashes}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise InputError('wheel downloads must not redirect')


def download_wheels(lock: dict, output: Path) -> None:
    opener = urllib.request.build_opener(NoRedirect)
    output.mkdir()
    for row in lock['wheels']:
        with opener.open(row['url'], timeout=30) as response:
            data = response.read(64 * 1024 * 1024 + 1)
        if len(data) > 64 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != row['sha256']:
            raise InputError('downloaded wheel does not match its bounded hash lock')
        (output / row['file']).write_bytes(data)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('repository', type=Path)
    parser.add_argument('commit')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    lock = load_lock(root / 'runtime-lock.json')
    args.output.mkdir()  # A reused context could retain stale or secret files.
    receipt = export_source(args.repository, args.commit, args.output / 'source')
    (args.output / 'source-receipt.json').write_text(json.dumps(receipt, sort_keys=True) + '\n')
    download_wheels(lock, args.output / 'wheelhouse')
    for role in ('build', 'runtime'):
        (args.output / f'{role}.lock').write_text(''.join(
            f"/inputs/wheelhouse/{r['file']} --hash=sha256:{r['sha256']}\n"
            for r in lock['wheels'] if r['role'] == role))
    print(f"Prepared exact source {args.commit} and {len(lock['wheels'])} verified wheels")


if __name__ == '__main__':
    main()
