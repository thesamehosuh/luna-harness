"""Release chat runtime download integrity and interruption recovery."""
import hashlib
import importlib.util
import io
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[2] / 'deploy/node_runtime.py'
spec = importlib.util.spec_from_file_location('luna_node_runtime_fixture', PATH)
node = importlib.util.module_from_spec(spec)
spec.loader.exec_module(node)


def test_interrupted_download_resumes_and_verified_cache_needs_no_network(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path))
    monkeypatch.setattr(node.time, 'sleep', lambda *_: None)
    payload = b'public archive bytes'
    target = {'filename': 'node-fixture.tar.gz', 'sha256': hashlib.sha256(payload).hexdigest()}
    requests = []
    class Response(io.BytesIO):
        def __init__(self, data, *, status=200, headers=None):
            super().__init__(data)
            self.status, self.headers = status, headers or {}
    def download(request, **kwargs):
        requests.append(request)
        if len(requests) == 1:
            return Response(payload[:6], headers={'Content-Length': str(len(payload))})
        assert request.get_header('Range') == 'bytes=6-'
        return Response(payload[6:], status=206, headers={'Content-Range': f'bytes 6-{len(payload)-1}/{len(payload)}'})
    monkeypatch.setattr(node.urllib.request, 'urlopen', download)
    archive = node._archive('https://fixture.invalid/node.tar.gz', target)
    assert archive.read_bytes() == payload
    monkeypatch.setattr(node.urllib.request, 'urlopen', lambda *a, **k: pytest.fail('Verified cache should be reused'))
    assert node._archive('https://fixture.invalid/node.tar.gz', target) == archive


def test_bad_download_is_never_published(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path))
    response = io.BytesIO(b'tampered')
    response.status, response.headers = 200, {}
    monkeypatch.setattr(node.urllib.request, 'urlopen', lambda *a, **k: response)
    with pytest.raises(ValueError, match='checksum'):
        node._archive('https://fixture.invalid/node.tar.gz', {'filename': 'fixture.tar.gz', 'sha256': '0'*64})
    assert not (tmp_path / 'luna/node/fixture.tar.gz').exists()
