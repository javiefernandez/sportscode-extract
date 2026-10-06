"""Minimal local web front end: choose one playlist, extract it, show the result."""
import argparse
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import time
import webbrowser

ICON = Path(__file__).with_name('static') / 'icon.png'
IDLE_EXIT = 120  # seconds without a page poll (and no running job) before the server exits

PAGE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sportscode Extract</title>
<link rel="icon" href="/icon.png">
<style>
:root { --bg:#f4f5f7; --card:#fff; --ink:#1b1f24; --muted:#5f6b7a; --line:#dde1e6; --accent:#1f3a68; --ok:#1d7a46; --warn:#a15c00; --bad:#b42318; }
@media (prefers-color-scheme: dark) { :root { --bg:#121417; --card:#1c1f24; --ink:#e8eaed; --muted:#9aa4b1; --line:#2e333a; --accent:#7fa6e6; --ok:#4cc38a; --warn:#f0a43a; --bad:#f2786d; } }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink); font:15px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
main { max-width:620px; margin:40px auto; padding:0 16px; }
header { display:flex; align-items:center; gap:16px; margin-bottom:20px; }
header img { width:72px; height:72px; border-radius:50%; object-fit:cover; background:var(--card); border:2px solid var(--line); }
h1 { font-size:22px; margin:0; }
header p { margin:2px 0 0; color:var(--muted); }
.card { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:20px; }
label.title { display:block; font-weight:600; margin:0 0 6px; }
.row { display:flex; gap:8px; margin-bottom:18px; }
input[type=text] { flex:1; min-width:0; padding:9px 10px; border:1px solid var(--line); border-radius:8px; background:var(--bg); color:var(--ink); font:inherit; }
button { font:inherit; border-radius:8px; border:1px solid var(--line); background:var(--bg); color:var(--ink); padding:9px 14px; cursor:pointer; }
button:disabled { opacity:.5; cursor:default; }
.seg { display:inline-flex; border:1px solid var(--line); border-radius:8px; overflow:hidden; margin-bottom:18px; }
.seg button { border:0; border-radius:0; }
.seg button.on { background:var(--accent); color:#fff; }
.opts { display:flex; flex-wrap:wrap; gap:18px; margin-bottom:20px; color:var(--muted); }
#go { width:100%; background:var(--accent); border-color:var(--accent); color:#fff; font-weight:600; padding:12px; }
#out { margin-top:16px; display:none; padding:14px; border-radius:10px; border:1px solid var(--line); background:var(--bg); }
#out h2 { font-size:16px; margin:0 0 6px; }
#out.ok h2 { color:var(--ok); } #out.warn h2 { color:var(--warn); } #out.bad h2 { color:var(--bad); }
#out ul { margin:6px 0; padding-left:18px; color:var(--muted); }
#out code, #preview code { word-break:break-all; }
#preview { margin:-6px 0 14px; }
.small { font-size:13px; color:var(--muted); }
</style></head>
<body><main>
<header><img src="/icon.png" alt=""><div><h1>Sportscode Extract</h1><p>Playlist → MP4 + XML timeline</p></div></header>
<div class="card">
  <label class="title" for="path">Playlist (.SCPlaylist)</label>
  <div class="row"><input type="text" id="path" placeholder="/path/to/Playlist.SCPlaylist" spellcheck="false"><button id="pick">Choose…</button></div>
  <label class="title" for="dest">Save to</label>
  <div class="row"><input type="text" id="dest" spellcheck="false"><button id="pickdest">Choose…</button></div>
  <label class="title">Target application</label>
  <div class="seg"><button data-t="angles" class="on">Angles</button><button data-t="focus">Catapult Focus</button></div>
  <div class="opts">
    <label><input type="checkbox" id="force"> Overwrite existing export</label>
    <label><input type="checkbox" id="partial"> Allow partial (skip unusable clips)</label>
  </div>
  <p class="small" id="preview"></p>
  <button id="go">Extract</button>
  <div id="out"></div>
</div>
</main>
<script>
const TOKEN = '__TOKEN__';
let target = 'angles';
const $ = id => document.getElementById(id);
const api = (path, body) => fetch(path, {method: body ? 'POST' : 'GET', headers: {'X-Token': TOKEN, 'Content-Type': 'application/json'}, body: body && JSON.stringify(body)}).then(r => r.json());
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function preview() {
  const name = $('path').value.trim().replace(/\/+$/, '').split('/').pop().replace(/\.scplaylist$/i, '');
  const dest = $('dest').value.trim().replace(/\/+$/, '');
  $('preview').innerHTML = name && dest ? `Export folder: <code>${esc(dest + '/' + name + (target === 'focus' ? ' (Focus)' : ''))}</code>` : '';
}
document.querySelectorAll('.seg button').forEach(b => b.onclick = () => {
  target = b.dataset.t; document.querySelectorAll('.seg button').forEach(x => x.classList.toggle('on', x === b)); preview();
});
$('path').oninput = $('dest').oninput = preview;
$('pick').onclick = async () => { const r = await api('/api/pick', {kind: 'playlist'}); if (r.path) { $('path').value = r.path; preview(); } };
$('pickdest').onclick = async () => { const r = await api('/api/pick', {kind: 'folder'}); if (r.path) { $('dest').value = r.path; preview(); } };
$('go').onclick = async () => {
  const r = await api('/api/run', {playlist: $('path').value.trim(), dest: $('dest').value.trim(), target, force: $('force').checked, allow_partial: $('partial').checked});
  if (r.error) return show('bad', 'Could not start', esc(r.error));
  poll();
};
function show(kind, title, html) { const o = $('out'); o.className = kind; o.style.display = 'block'; o.innerHTML = `<h2>${title}</h2>${html}`; }
async function poll() {
  const s = await api('/api/status');
  if (!$('dest').value) { $('dest').value = s.dest; preview(); }
  $('pick').hidden = $('pickdest').hidden = !s.can_pick;
  $('go').disabled = $('pick').disabled = $('pickdest').disabled = s.state === 'running';
  if (s.state === 'running') { show('', 'Working…', `<span class="small">${esc(s.playlist)} — ${s.elapsed}s elapsed. Rendering can take several minutes.</span>`); }
  else if (s.state === 'done') {
    const kind = s.code === 0 ? 'ok' : s.code === 2 ? 'warn' : 'bad';
    const title = s.code === 0 ? 'Export complete' : s.code === 2 ? 'Export partial — some clips skipped' : 'Export failed';
    let html = s.output_exists ? `<p><code>${esc(s.output)}</code></p><button id="open">Open folder</button>` : '';
    if (s.clips != null) html = `<p>${s.clips} clips in playlist${s.omitted ? `, ${s.omitted} skipped` : ''}.</p>` + html;
    if (s.issues && s.issues.length) html += '<ul>' + s.issues.map(([m, n]) => `<li>${n} × ${esc(m)}</li>`).join('') + '</ul>';
    if (s.error) html += `<p>${esc(s.error)}</p>`;
    if (s.code === 1 && /allow-partial/.test(s.error || '')) html += '<p class="small">Tick “Allow partial” to export the usable clips anyway.</p>';
    if (s.code === 1 && /already exists/.test(s.error || '')) html += '<p class="small">Tick “Overwrite existing export” to replace it.</p>';
    show(kind, title, html);
    if ($('open')) $('open').onclick = () => api('/api/open', {});
  }
  setTimeout(poll, s.state === 'running' ? 1000 : 5000);
}
poll();
</script></body></html>'''


class App:
    def __init__(self, exports, settings=None):
        self.dest = exports
        self.settings = settings
        try:
            self.dest = Path(json.loads(settings.read_text())['dest'])
        except (AttributeError, OSError, ValueError, KeyError, TypeError):
            pass  # no or unreadable settings: keep the default
        self.token = secrets.token_urlsafe(16)
        self.job = {'state': 'idle'}
        self.lock = threading.Lock()
        self.last_seen = time.time()

    def start(self, playlist, target, force, allow_partial, dest=None):
        source = Path(playlist).expanduser()
        if source.suffix.lower() != '.scplaylist' or not source.is_dir():
            raise ValueError('Choose an existing .SCPlaylist package')
        if target not in ('angles', 'focus'):
            raise ValueError('Unknown target')
        dest = Path(dest).expanduser() if dest else self.dest
        if not dest.is_absolute():
            raise ValueError('Choose a full folder path to save to')
        # Each export gets its own subfolder named after the playlist.
        output = dest / (source.stem + (' (Focus)' if target == 'focus' else ''))
        command = [sys.executable, '-m', 'sportscode_extract', 'extract', str(source), '--output', str(output), '--target', target]
        command += ['--force'] * bool(force) + ['--allow-partial'] * bool(allow_partial)
        with self.lock:
            if self.job['state'] == 'running':
                raise ValueError('An extraction is already running')
            try:
                dest.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise ValueError(f'Cannot create {dest}: {exc.strerror}')
            self.remember(dest)
            self.job = {'state': 'running', 'playlist': source.name, 'output': str(output), 'started': time.time()}
        threading.Thread(target=self.run, args=(command,), daemon=True).start()

    def run(self, command):
        result = subprocess.run(command, capture_output=True, text=True)
        error = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else ''
        job = {'code': result.returncode, 'error': error.removeprefix('sportscode-extract: ')}
        try:
            report = json.loads(result.stdout)
            job['clips'] = report['counts']['media_clips']
            job['omitted'] = len(report.get('omitted_clip_ids', []))
            job['issues'] = Counter(i['message'] for i in report['issues']).most_common(8)
        except (ValueError, KeyError, TypeError):
            pass
        with self.lock:
            self.job.update(job, state='done')

    def remember(self, dest):
        self.dest = dest
        if self.settings:
            try:
                self.settings.write_text(json.dumps({'dest': str(dest)}))
            except OSError:
                pass

    def status(self):
        with self.lock:
            job = dict(self.job)
        if job['state'] == 'running':
            job['elapsed'] = int(time.time() - job['started'])
        job['output_exists'] = bool(job.get('output')) and Path(job['output']).is_dir()
        job['dest'] = str(self.dest)
        job['can_pick'] = sys.platform == 'darwin'
        return job


# .SCPlaylist is a package (a file) where Sportscode is installed and a plain folder elsewhere,
# so the panel must accept both; AppleScript's choose file/choose folder each accept only one.
# osascript is a background process, so its panel opens behind the browser unless it first
# becomes a regular (foreground) app and activates itself.
PICKER = '''ObjC.import('AppKit');
$.NSApplication.sharedApplication.setActivationPolicy($.NSApplicationActivationPolicyRegular);
$.NSApplication.sharedApplication.activateIgnoringOtherApps(true);
var p = $.NSOpenPanel.openPanel;
p.canChooseFiles = FILES; p.canChooseDirectories = true; p.canCreateDirectories = !FILES; p.allowsMultipleSelection = false;
p.message = 'MESSAGE';
p.runModal == $.NSModalResponseOK ? p.URLs.objectAtIndex(0).path.js : '';'''


def pick(kind):
    if sys.platform != 'darwin':
        return None
    playlist = kind == 'playlist'
    script = PICKER.replace('FILES', 'true' if playlist else 'false').replace(
        'MESSAGE', 'Choose a .SCPlaylist package' if playlist else 'Choose where to save exports')
    result = subprocess.run(['osascript', '-l', 'JavaScript', '-e', script], capture_output=True, text=True)
    return result.stdout.strip() or None


def handler(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, body, content_type='application/json', status=200):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)

        def authorized(self):
            # A per-launch token keeps other web pages from driving this local server.
            if self.headers.get('X-Token') != app.token:
                self.send({'error': 'forbidden'}, status=403)
                return False
            app.last_seen = time.time()
            return True

        def do_GET(self):
            if self.path == '/':
                self.send(PAGE.replace('__TOKEN__', app.token).encode(), 'text/html; charset=utf-8')
            elif self.path == '/icon.png':
                self.send(ICON.read_bytes(), 'image/png')
            elif self.path == '/api/status' and self.authorized():
                self.send(app.status())
            elif not self.path.startswith('/api/'):
                self.send({'error': 'not found'}, status=404)

        def do_POST(self):
            if not self.authorized():
                return
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
            if self.path == '/api/pick':
                self.send({'path': pick(body.get('kind'))})
            elif self.path == '/api/run':
                try:
                    app.start(body.get('playlist', ''), body.get('target', 'angles'), body.get('force'),
                              body.get('allow_partial'), body.get('dest'))
                    self.send({'ok': True})
                except ValueError as exc:
                    self.send({'error': str(exc)})
            elif self.path == '/api/open':
                output = app.status().get('output')
                if output and Path(output).is_dir():
                    subprocess.run(['open', output] if sys.platform == 'darwin' else ['xdg-open', output])
                self.send({'ok': True})
            else:
                self.send({'error': 'not found'}, status=404)
    return Handler


def main(argv=None):
    p = argparse.ArgumentParser(prog='sportscode-extract-gui')
    p.add_argument('--exports', type=Path, default=Path.cwd() / 'local_exports')
    p.add_argument('--no-browser', action='store_true')
    args = p.parse_args(argv)
    args.exports.mkdir(parents=True, exist_ok=True)
    app = App(args.exports.resolve(), Path.home() / '.sportscode-extract-gui.json')
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler(app))
    url = f'http://127.0.0.1:{server.server_address[1]}/'
    print(f'Sportscode Extract running at {url} (closes {IDLE_EXIT}s after the page is closed)', flush=True)

    def idle_watch():
        while True:
            time.sleep(5)
            if app.status()['state'] != 'running' and time.time() - app.last_seen > IDLE_EXIT:
                server.shutdown()
                return
    threading.Thread(target=idle_watch, daemon=True).start()
    if not args.no_browser:
        webbrowser.open(url)
    server.serve_forever()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
