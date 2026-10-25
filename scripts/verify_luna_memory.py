#!/usr/bin/env python3
"""Real isolated Honcho/Postgres/Redis path with deterministic local model fixtures; no keys."""
import argparse
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / 'luna/lib')]
MARKER = 'synthetic-luna-memory-colour-cobalt'
REQUESTS = {'chat': 0, 'embedding': 0}

class ModelFixture(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_GET(self):
        encoded = json.dumps(REQUESTS).encode()
        self.send_response(200);self.send_header('Content-Length', str(len(encoded)));self.end_headers();self.wfile.write(encoded)
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', '0'))))
        if self.path.endswith('/embeddings'):
            REQUESTS['embedding'] += 1
            values = body.get('input')
            values = values if isinstance(values, list) else [values]
            result = {'object': 'list', 'model': body.get('model'), 'data': [{'object': 'embedding', 'index': index, 'embedding': [1.0] + [0.0] * 1535} for index, _ in enumerate(values)], 'usage': {'prompt_tokens': 8, 'total_tokens': 8}}
        else:
            REQUESTS['chat'] += 1
            markers = re.findall(r'luna-check-[0-9a-f]{16}', json.dumps(body))
            observed = markers[-1] if markers else MARKER
            result = {'id': 'local-fixture', 'object': 'chat.completion', 'created': 0, 'model': body.get('model'), 'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': json.dumps({'explicit': [{'content': f'The synthetic user likes {observed}.'}]})}, 'finish_reason': 'stop'}], 'usage': {'prompt_tokens': 32, 'completion_tokens': 16, 'total_tokens': 48}}
        encoded = json.dumps(result).encode()
        self.send_response(200);self.send_header('Content-Type', 'application/json');self.send_header('Content-Length', str(len(encoded)));self.end_headers();self.wfile.write(encoded)


def unused_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0));return sock.getsockname()[1]


def main():
    from luna_cli import onboarding
    from luna_core import data_ops, readiness
    from luna_core.honcho import HonchoStore, connection_settings
    import yaml
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('/tmp/luna-memory-integration.json'))
    args = parser.parse_args()
    clean = {key: value for key, value in os.environ.items() if not key.startswith(('LUNA_', 'HERMES_', 'OPENAI_', 'OPENROUTER_', 'HONCHO_')) and not key.endswith(('_KEY', '_TOKEN', '_SECRET', '_PASSWORD'))}
    report = {'health': False, 'write_read_search_derivation': False, 'backup': False, 'private_network_maintenance': False, 'restart_recall': False}
    server = ThreadingHTTPServer(('0.0.0.0', 0), ModelFixture)
    worker = threading.Thread(target=server.serve_forever, daemon=True);worker.start()
    with tempfile.TemporaryDirectory(prefix='luna-memory-integration-') as temporary, patch.dict(os.environ, clean, clear=True):
        home = Path(temporary)
        os.environ.update(HERMES_HOME=str(home), LUNA_HOME=str(home), LUNA_MEMORY_API_KEY='synthetic-fixture-key', NO_PROXY='localhost,127.0.0.1', no_proxy='localhost,127.0.0.1')
        stack = home / 'honcho';shutil.copytree(ROOT / 'luna/honcho', stack)
        compose = yaml.safe_load((stack / 'docker-compose.yml').read_text())
        compose['services']['models'] = {'image': 'python:3.11-slim', 'entrypoint': ['python', '/fixture.py', '--fixture-server'], 'volumes': [str(Path(__file__).resolve()) + ':/fixture.py:ro']}
        (stack / 'docker-compose.yml').write_text(yaml.safe_dump(compose, sort_keys=False))
        model_url = 'http://models:8001/v1' 
        config = {'memory': {'provider': 'luna-memory'}, 'honcho': {'baseUrl': f'http://127.0.0.1:{unused_port()}', 'workspace': 'luna-fixture'}, 'luna': {'memory_stack': {'base_url': model_url, 'model': 'gpt-4o-mini', 'embedding_base_url': model_url, 'embedding_model': 'text-embedding-3-small', 'embedding_dimensions': 1536}}}
        (home / 'config.yaml').write_text(yaml.safe_dump(config))
        (home / 'SOUL.md').write_text('# Synthetic fixture\n')
        onboarding._seed_honcho_env(stack)
        command = data_ops.compose_command(stack)
        try:
            print('Starting an isolated managed memory stack', flush=True)
            up = onboarding.honcho_up(timeout=180)
            if not up['ok']:
                raise RuntimeError(up['detail'] + ' ' + up.get('output', ''))
            report['health'] = True
            print('Checking write/read/search/derivation and cleanup', flush=True)
            check = readiness.verify_memory()
            report['checks'] = check
            report['write_read_search_derivation'] = check['ok']
            store = HonchoStore(**connection_settings());client = store.client()
            peer = client.peer('synthetic-peer');session = client.session('synthetic-room', peers=['synthetic-peer'])
            session.add_messages([peer.message(MARKER)])
            time.sleep(3)
            print('Checking managed pg_dump and private-network pruning', flush=True)
            backup = data_ops.backup();report['backup'] = backup['bytes'] > 0
            import importlib.util
            spec = importlib.util.spec_from_file_location('fixture_pruner', ROOT / 'luna/tools/prune_data.py')
            pruner = importlib.util.module_from_spec(spec);spec.loader.exec_module(pruner)
            pruned = pruner.prune_honcho(data=config, days=1, batch_size=100)
            report['private_network_maintenance'] = not pruned['failed']
            print('Restarting only the isolated API and checking durable recall', flush=True)
            subprocess.run([*command, 'restart', 'api'], check=True, stdout=subprocess.DEVNULL)
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline and not onboarding._probe_health(config['honcho']['baseUrl']): time.sleep(1)
            report['restart_recall'] = any(MARKER in str(getattr(message, 'content', '')) for message in client.session('synthetic-room').messages())
        finally:
            log = subprocess.run([*command, 'logs', '--no-color', '--tail', '80'], capture_output=True, text=True)
            args.output.with_suffix('.log').write_text(log.stdout + log.stderr)
            counted = subprocess.run([*command, 'exec', '-T', 'models', 'python', '-c', "import urllib.request; print(urllib.request.urlopen('http://localhost:8001/counts').read().decode())"], capture_output=True, text=True)
            if counted.returncode == 0: REQUESTS.update(json.loads(counted.stdout))
            subprocess.run([*command, 'down', '--volumes', '--remove-orphans'], capture_output=True, timeout=60)
    server.shutdown();server.server_close()
    report['local_model_requests'] = REQUESTS
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return 0 if all(report[key] for key in ('health', 'write_read_search_derivation', 'backup', 'private_network_maintenance', 'restart_recall')) else 1

if __name__ == '__main__':
    if sys.argv[1:] == ['--fixture-server']:
        ThreadingHTTPServer(('0.0.0.0', 8001), ModelFixture).serve_forever()
    else:
        raise SystemExit(main())
