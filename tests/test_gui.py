import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from sportscode_extract.gui import App, handler
from http.server import ThreadingHTTPServer


@pytest.fixture
def served(tmp_path):
    app = App(tmp_path / 'exports')
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler(app))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield app, f'http://127.0.0.1:{server.server_address[1]}'
    server.shutdown()


def call(url, path, body=None, token=None):
    request = urllib.request.Request(url + path, data=None if body is None else json.dumps(body).encode(),
                                     headers={'X-Token': token or '', 'Content-Type': 'application/json'})
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read())


def test_page_icon_and_token(served):
    app, url = served
    page = urllib.request.urlopen(url + '/').read().decode()
    assert app.token in page and 'Sportscode Extract' in page
    assert urllib.request.urlopen(url + '/icon.png').read().startswith(b'\x89PNG')
    with pytest.raises(urllib.error.HTTPError) as error:
        call(url, '/api/status')
    assert error.value.code == 403
    assert call(url, '/api/run', {'playlist': '/nope'}, app.token)['error'].startswith('Choose an existing')


def test_extract_through_api(served, package_factory, ffmpeg, ffprobe, monkeypatch):
    monkeypatch.setenv('SPORTSCODE_FFMPEG', ffmpeg)
    monkeypatch.setenv('SPORTSCODE_FFPROBE', ffprobe)
    app, url = served
    package = package_factory()
    assert call(url, '/api/run', {'playlist': str(package), 'target': 'focus'}, app.token) == {'ok': True}
    for _ in range(120):
        status = call(url, '/api/status', token=app.token)
        if status['state'] == 'done':
            break
        time.sleep(.5)
    assert status['code'] == 0, status
    assert status['clips'] == 1 and status['omitted'] == 0 and status['output_exists']
    assert status['output'].endswith(' (Focus)')


def test_dest_subfolder_and_remembered(tmp_path, package_factory, ffmpeg, ffprobe, monkeypatch):
    monkeypatch.setenv('SPORTSCODE_FFMPEG', ffmpeg)
    monkeypatch.setenv('SPORTSCODE_FFPROBE', ffprobe)
    settings = tmp_path / 'settings.json'
    app = App(tmp_path / 'default', settings)
    package = package_factory()
    with pytest.raises(ValueError, match='full folder path'):
        app.start(str(package), 'angles', False, False, 'relative/dir')
    dest = tmp_path / 'chosen' / 'new'
    app.start(str(package), 'angles', False, False, str(dest))
    while app.status()['state'] == 'running':
        time.sleep(.2)
    status = app.status()
    assert status['code'] == 0, status
    assert status['output'] == str(dest / package.stem) and (dest / package.stem / 'manifest.json').is_file()
    assert App(tmp_path / 'default', settings).status()['dest'] == str(dest)
