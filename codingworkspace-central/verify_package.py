#!/usr/bin/env python3
"""Reject source/wheel drift, including the D12 stale build/lib regression."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys


def verify(receipt: dict, site: Path) -> None:
    expected = {name: digest for name, digest in receipt['files'].items()
                if name.startswith('codingworkspace/')}
    actual = {p.relative_to(site).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in (site / 'codingworkspace').rglob('*') if p.is_file()
              and '__pycache__' not in p.parts and p.suffix not in {'.pyc', '.pyo'}}
    if actual != expected:
        raise ValueError('installed package differs from the exact source receipt')


if __name__ == '__main__':
    import codingworkspace
    receipt = json.loads(Path(sys.argv[1]).read_text())
    assert receipt['commit'] == sys.argv[2], 'build argument and source receipt differ'
    site = Path(codingworkspace.__file__).resolve().parent.parent
    assert 'site-packages' in site.parts, 'import resolved outside the installed package'
    verify(receipt, site)
    assert importlib.metadata.version('codingworkspace') == codingworkspace.__version__
    print('Exact installed source verified:', receipt['commit'], codingworkspace.__version__)
