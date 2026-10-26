#!/usr/bin/env python3
"""Start dashboard's real bundled terminal UI + Python child and verify the effective Luna prompt."""
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import time
from unittest.mock import patch

ROOT = Path(os.environ.get('LUNA_TEST_CODE_ROOT') or Path(__file__).resolve().parent.parent)
sys.path[:0] = [str(ROOT), str(ROOT / 'luna/lib')]
MARKER = 'LUNA_DASHBOARD_PERSONA_FIXTURE'
RESULT = 'LUNA_DASHBOARD_CONTEXT_OK'
INPUT_PROMPT = 'luna-fixture>'

class Provider(BaseHTTPRequestHandler):
    requests = []
    people_check = False
    def log_message(self, *args): pass
    def do_GET(self):
        data = json.dumps({'object': 'list', 'data': [{'id': 'dashboard-fixture', 'object': 'model'}]}).encode()
        self.send_response(200);self.send_header('Content-Length', str(len(data)));self.end_headers();self.wfile.write(data)
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
        system = '\n'.join(str(row.get('content', '')) for row in body.get('messages', []) if row.get('role') in {'system', 'developer'})
        people_reference = any('PEOPLE.md' in str(row.get('content', '')) and 'Fixture Friend' in str(row.get('content', '')) for row in body.get('messages', []) if row.get('role') == 'user')
        tool_names = {row.get('function', {}).get('name') for row in body.get('tools', [])}
        people_tool = 'people' in tool_names or ('tool_call' in tool_names and any('people' in row.get('function', {}).get('description', '') for row in body.get('tools', [])))
        correct = MARKER in system and 'You run in Luna' in system and 'You are Hermes Agent' not in system
        type(self).requests.append({'persona': MARKER in system, 'luna_runtime': 'You run in Luna' in system, 'hermes_identity': 'You are Hermes Agent' in system, 'path':self.path, 'roles':[row.get('role') for row in body.get('messages',[])], 'system_head':system[:100], 'people_reference':people_reference, 'people_tool':people_tool, 'people_in_system':'Fixture Friend' in system})
        answer = RESULT if correct else 'WRONG_RUNTIME_CONTEXT'
        base = {'id': 'fixture', 'created': 0, 'model': body.get('model', 'dashboard-fixture')}
        tool_call = None
        if type(self).people_check:
            completed = any(row.get('role') == 'tool' and '"ok": true' in str(row.get('content', '')) for row in body.get('messages', []))
            if people_tool and people_reference and not completed:
                arguments = {'action':'upsert','user_id':'u_fixture','aliases':['Fixture Alias'],'role':'local test friend'}
                name = 'people' if 'people' in tool_names else 'tool_call'
                if name == 'tool_call':
                    arguments = {'calls':[{'name':'people','arguments':arguments}]}
                tool_call = {'id':'people-fixture-call','type':'function','function':{'name':name,'arguments':json.dumps(arguments)}}
            elif not completed:
                answer = 'WRONG_PEOPLE_CONTEXT'
        if body.get('stream'):
            delta = {'role':'assistant', 'tool_calls':[{'index':0, **tool_call}]} if tool_call else {'role':'assistant','content':answer}
            chunks = [{**base, 'object': 'chat.completion.chunk', 'choices': [{'index': 0, 'delta': delta, 'finish_reason': None}]}, {**base, 'object': 'chat.completion.chunk', 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'tool_calls' if tool_call else 'stop'}], 'usage': {'prompt_tokens': 20, 'completion_tokens': 5, 'total_tokens': 25}}]
            data = ''.join('data: '+json.dumps(chunk)+'\n\n' for chunk in chunks).encode() + b'data: [DONE]\n\n'
        else:
            message = {'role':'assistant','content':None,'tool_calls':[tool_call]} if tool_call else {'role':'assistant','content':answer}
            data = json.dumps({**base, 'object': 'chat.completion', 'choices': [{'index': 0, 'message': message, 'finish_reason': 'tool_calls' if tool_call else 'stop'}], 'usage': {'prompt_tokens': 20, 'completion_tokens': 5, 'total_tokens': 25}}).encode()
        self.send_response(200);self.send_header('Content-Type', 'text/event-stream' if body.get('stream') else 'application/json');self.send_header('Content-Length', str(len(data)));self.end_headers();self.wfile.write(data)


def verify(home=None, *, people_check=False):
    import yaml
    from hermes_cli.pty_bridge import PtyBridge
    from hermes_cli.web_server_chat import _resolve_chat_argv
    from hermes_cli import config
    server = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    Provider.requests = []
    Provider.people_check = people_check
    clean = {key: value for key, value in os.environ.items() if not key.startswith(('HERMES_', 'LUNA_', 'OPENAI_', 'OPENROUTER_', 'HONCHO_', 'ANTHROPIC_')) and not key.endswith(('_KEY','_TOKEN','_SECRET','_PASSWORD'))}
    with tempfile.TemporaryDirectory(prefix='luna-dashboard-chat-') as temporary, patch.dict(os.environ, clean, clear=True):
        target = Path(home) if home else Path(temporary)
        target.mkdir(parents=True, exist_ok=True)
        os.environ.update(HERMES_HOME=str(target), LUNA_HOME=str(target), HERMES_PYTHON='/usr/bin/python3', HERMES_PYTHON_SRC_ROOT='/tmp', HERMES_TUI_DIR='/tmp', HERMES_SKIP_NODE_BOOTSTRAP='1')
        workspace = target / 'workspace';workspace.mkdir(exist_ok=True)
        data = {'model': {'provider':'custom','default':'dashboard-fixture','base_url':f'http://127.0.0.1:{server.server_port}/v1','api_key':'synthetic-fixture-key','api_mode':'chat_completions'}, 'luna': {'ambient': {'enabled': False}}, 'memory': {'provider':'', 'memory_enabled':False, 'user_profile_enabled':False}, 'terminal': {'cwd':str(workspace)}, 'display': {'skin':'default'}, 'platform_toolsets': {'cli':[]}, 'fallback_providers':[], 'plugins': {'enabled':[]}}
        if people_check:
            data['platform_toolsets']['cli'] = ['people']
            from luna_core import db
            from luna_core.identity import IdentityRegistry
            conn = db.connect(target / 'luna-state.db'); db.init_db(conn)
            IdentityRegistry(conn).upsert_auto('telegram', 'u_fixture', display_name='Fixture Friend')
            conn.close()
        # This helper runs only in scratch homes, including the release smoke's disposable install.
        # Wait for a fixture-owned composer marker, not decorative startup copy.
        # The embedded dashboard intentionally omits the standalone CLI banner.
        data['display']['skin'] = 'fixture-input'
        skins = target / 'skins'; skins.mkdir(exist_ok=True)
        (skins / 'fixture-input.yaml').write_text(yaml.safe_dump({
            'name': 'fixture-input', 'branding': {'prompt_symbol': INPUT_PROMPT},
        }))
        (target / 'config.yaml').write_text(yaml.safe_dump(data))
        (target / 'SOUL.md').write_text('# Nova\n\n'+MARKER+'\n')
        argv, cwd, env = _resolve_chat_argv()
        assert Path(env['HERMES_PYTHON_SRC_ROOT']).resolve() != Path('/tmp')
        assert env['HERMES_PYTHON'] != '/usr/bin/python3'
        assert env['HERMES_HOME'] == str(target) == env['LUNA_HOME']
        assert env['HERMES_CWD'] == str(workspace)
        bridge = PtyBridge.spawn(argv, cwd=cwd, env=env, cols=120, rows=40)
        output = b''
        submitted = False
        try:
            began = time.monotonic()
            deadline = began + 90
            while time.monotonic() < deadline:
                chunk = bridge.read(0.2)
                if chunk is None: break
                output += chunk
                plain = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', output.decode(errors='replace'))
                if not submitted and INPUT_PROMPT in plain and time.monotonic() - began > 5:
                    time.sleep(0.3)
                    asyncio.run(bridge.write(b'Reply with the dashboard check result.'))
                    time.sleep(0.3)
                    asyncio.run(bridge.write(b'\r'))
                    submitted = True
                if RESULT in plain and Provider.requests: break
            Path('/tmp/luna-dashboard-chat-pty.log').write_bytes(output)
            report = {'bundled_tui': 'tui_dist' in ' '.join(argv), 'selected_home': env['HERMES_HOME'] == str(target), 'source_pinned': env['HERMES_PYTHON_SRC_ROOT'] == str(ROOT), 'input_submitted': submitted, 'persona_in_inference': any(row['persona'] for row in Provider.requests), 'luna_runtime_in_inference': any(row['luna_runtime'] for row in Provider.requests), 'no_hermes_identity': bool(Provider.requests) and all(not row['hermes_identity'] for row in Provider.requests), 'rendered_response': RESULT in plain, 'local_requests': len(Provider.requests)}
            agent_log = target / 'logs/agent.log'
            report['no_unrelated_sdk_install'] = not agent_log.exists() or 'Lazy-installing' not in agent_log.read_text(errors='replace')
            if people_check:
                report['people_reference_in_user_context'] = any(row['people_reference'] for row in Provider.requests)
                report['people_tool_available'] = any(row['people_tool'] for row in Provider.requests)
                report['people_absent_from_system_prompt'] = all(not row['people_in_system'] for row in Provider.requests)
                report['model_updated_people_file'] = (target / 'PEOPLE.md').exists() and 'Fixture Alias' in (target / 'PEOPLE.md').read_text()
            Path('/tmp/luna-dashboard-chat-requests.json').write_text(json.dumps(Provider.requests, indent=2))
            if not all(report[key] for key in report if key != 'local_requests'):
                debug = []
                for log in (target / 'logs').glob('*.log'):
                    debug.append(log.name + '\n' + log.read_text(errors='replace')[-12000:])
                Path('/tmp/luna-dashboard-chat-debug.log').write_text('\n'.join(debug))
                raise RuntimeError(json.dumps(report))
            return report
        finally:
            bridge.close()
            server.shutdown();server.server_close()

if __name__ == '__main__': print(json.dumps(verify(), indent=2))
