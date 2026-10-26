from types import SimpleNamespace
from unittest.mock import Mock
import pytest

@pytest.fixture
def client(monkeypatch):
    from starlette.testclient import TestClient
    from hermes_cli import web_server, web_server_gateway
    from hermes_cli.web_routers import ops
    import gateway.status
    monkeypatch.setattr(web_server_gateway, "multiplexed_profile_refusal", lambda *_: None)
    monkeypatch.setattr(ops, "_gateway_service_status", lambda *_: {"supported": True, "installed": False, "kind": "systemd", "scope": "user"})
    monkeypatch.setattr(gateway.status, "is_gateway_running", lambda **_: False)
    spawn = Mock(return_value=SimpleNamespace(pid=321))
    monkeypatch.setattr(ops, "_spawn_hermes_action", spawn)
    c = TestClient(web_server.app)
    c.headers[web_server._SESSION_HEADER_NAME] = web_server._SESSION_TOKEN
    return c, spawn

def test_service_install_requires_explicit_action_and_starts_on_login(client):
    c, spawn = client
    assert c.get('/api/gateway/service').json()['installed'] is False
    spawn.assert_not_called()
    response=c.post('/api/gateway/service/install')
    assert response.status_code==200
    argv,name=spawn.call_args.args
    assert argv[-4:]==['gateway','install','--start-now','--start-on-login']
    assert name=='gateway-service-install'

def test_service_install_rejects_running_gateway_before_mutating(client,monkeypatch):
    import gateway.status
    c,spawn=client
    monkeypatch.setattr(gateway.status,'is_gateway_running',lambda **_: True)
    assert c.post('/api/gateway/service/install').status_code==409
    spawn.assert_not_called()

def test_service_install_rejects_system_scope_and_foreign_profiles(client,monkeypatch):
    from hermes_cli.web_routers import ops
    c,spawn=client
    monkeypatch.setattr(ops,'_gateway_service_status',lambda *_:{'supported':True,'installed':True,'scope':'system'})
    assert c.post('/api/gateway/service/install').status_code==409
    spawn.assert_not_called()

def test_service_routes_require_dashboard_auth(client):
    c,spawn=client
    from hermes_cli import web_server
    c.headers.pop(web_server._SESSION_HEADER_NAME)
    assert c.post('/api/gateway/service/install').status_code in (401,403)
    spawn.assert_not_called()

def test_service_removal_uses_existing_scoped_uninstaller(client):
    c,spawn=client
    assert c.post('/api/gateway/service/uninstall').status_code==200
    assert spawn.call_args.args[0][-2:]==['gateway','uninstall']

def test_dashboard_action_uses_selected_runtime_directory(monkeypatch,tmp_path):
    from hermes_cli import web_server_gateway as mod,product_runtime
    home=tmp_path/'home';current=tmp_path/'new-runtime';current.mkdir()
    monkeypatch.setattr(mod,'_ACTION_LOG_DIR',tmp_path/'logs')
    monkeypatch.setattr(mod,'_dashboard_spawn_executable',lambda:'/new-runtime/venv/bin/python')
    monkeypatch.setattr(mod,'_profile_action_environment',lambda *_:{'HERMES_HOME':str(home)})
    monkeypatch.setattr(mod,'_action_targets_system_gateway',lambda *_:False)
    monkeypatch.setattr(product_runtime,'enabled',lambda:True)
    monkeypatch.setattr(product_runtime,'code_root',lambda *_:current)
    spawn=Mock(return_value=SimpleNamespace(pid=99))
    monkeypatch.setattr(mod.subprocess,'Popen',spawn)
    for name in ('_ACTION_PROCS','_ACTION_COMMANDS','_ACTION_RESULTS','_ACTION_IDS'):monkeypatch.setattr(mod,name,{})
    mod._spawn_hermes_action(['gateway','start'],'gateway-start')
    assert spawn.call_args.kwargs['cwd']==str(current)

def test_service_virtualenv_comes_from_selected_desktop_runtime(monkeypatch,tmp_path):
    from hermes_cli import gateway,product_runtime
    selected=tmp_path/'releases/current/venv'
    monkeypatch.setattr(product_runtime,'enabled',lambda:True)
    monkeypatch.setattr(product_runtime,'executable',lambda *_:str(selected/'bin/python'))
    assert gateway._service_venv_dir()==str(selected)
