"""Opt-in read-only live list probe. Never invokes any account mutation or refresh."""
import argparse
import hashlib
import importlib.util
from pathlib import Path
import re
from unittest.mock import patch

from hermes_constants import set_hermes_home_override, reset_hermes_home_override

parser = argparse.ArgumentParser()
parser.add_argument('--home', required=True, type=Path)
args = parser.parse_args()
home = args.home.resolve()
auth_file = home / 'auth.json'
before = hashlib.sha256(auth_file.read_bytes()).digest()
spec = importlib.util.spec_from_file_location('codex_accounts_probe', Path(__file__).resolve().parents[1] / '__init__.py')
plugin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plugin)
scope = set_hermes_home_override(home)
try:
    with patch('hermes_cli.auth._save_auth_store', side_effect=AssertionError('live probe attempted write')), \
            patch('agent.credential_pool.load_pool', side_effect=AssertionError('live probe attempted mutating load')):
        result = plugin.AccountsCommand(home)('list', session_key='read-only-verification', platform='cli')
    # Do not store or print real labels, IDs, emails or token material in verification logs.
    rows = result.splitlines()
    for row in rows:
        if re.match(r'^\d+\. ', row):
            print(row.split('. ', 1)[0] + '. [identity omitted]')
        elif row.startswith('   '):
            print(row)
        elif row.startswith('Codex accounts') or row.startswith('No persisted'):
            print(row)
        else:
            raise RuntimeError('Probe did not return a list')
finally:
    reset_hermes_home_override(scope)
    unchanged = before == hashlib.sha256(auth_file.read_bytes()).digest()
    print('auth.json byte-identical:', unchanged)
    if not unchanged:
        raise RuntimeError('Auth changed during live probe; possibly concurrent runtime refresh; investigate')
