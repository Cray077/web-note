# Development Setup & Deployment

## Prerequisites

- **Python 3.10+** (developed and tested on Python `3.14.10`; `app.py` uses PEP 604 `X | Y` type unions).
- **No Node.js or build tools required.** All frontend dependencies are pre-vendored under `static/vendor/`.

## Environment Variables

| Variable | Default | Used in | Purpose |
| --- | --- | --- | --- |
| `NOTES_DIR` | `/var/notes` | `app.py:16` | Directory storing `notes.db` and `<id>.md` files (created automatically if missing and writable) |
| `PORT` | `8000` | `app.py:275` | Listening port when running `python app.py` directly (ignored by Gunicorn, which uses `-b`) |

## Local Development

### Windows (PowerShell)

> Note: `gunicorn` is Unix-only (requires `fcntl`), so install `flask` and `flask-sock` directly and use Flask's built-in threaded dev server locally on Windows.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install flask flask-sock
$env:NOTES_DIR = ".\data"
$env:PORT = "8000"
.venv\Scripts\python app.py
```

Open `http://127.0.0.1:8000` in your browser. Hard-refresh (`Ctrl+Shift+R`) after editing `static/index.html` to bypass browser caching of static assets.

### Linux / macOS

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
NOTES_DIR=./data PORT=8000 .venv/bin/python app.py
```

Or run locally under Gunicorn (use `-w 1` so all WebSocket clients share one process for live broadcasts):

```bash
NOTES_DIR=./data .venv/bin/gunicorn -w 1 -k gthread --threads 64 -b 127.0.0.1:8000 app:app
```

## Production Deployment (Linux VPS)

Designed for a lightweight 1 core / 1 GB RAM VPS behind Caddy:

1. **Create and own the data directory:**
   ```bash
   sudo mkdir -p /var/notes && sudo chown <app-user> /var/notes
   ```
2. **Install dependencies in a virtual environment:**
   ```bash
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```
3. **Run via Gunicorn (managed by a `systemd` service, single worker with threads so live WebSocket broadcasts reach all connected clients):**
   ```bash
   .venv/bin/gunicorn -w 1 -k gthread --threads 64 -b 127.0.0.1:8000 app:app
   ```
   `init_db()` runs lazily on the first DB request (thread-safe) and configures SQLite WAL mode automatically.
4. **Reverse proxy & access control (Caddy):**
   - Proxy `127.0.0.1:8000` over HTTPS with `reverse_proxy 127.0.0.1:8000` (Caddy automatically proxies WebSocket upgrades).
   - Because the app has **no built-in authentication**, restrict access at the network layer (Caddy `basic_auth`, Tailscale/VPN, or firewall rules) if exposed publicly.
5. **Backups:**
   - Periodically archive `/var/notes/` (e.g., nightly `tar` or `rsync`). Because SQLite uses WAL mode, if backing up `notes.db` while live, prefer `sqlite3 /var/notes/notes.db ".backup '/path/to/notes.db'"` or copy `notes.db`, `notes.db-wal`, and `notes.db-shm` together.

## Verification & Smoke Testing

There is currently no test runner committed in the repository. To run a quick verification against Flask's test client without touching `./data/`:

```powershell
.venv\Scripts\python -B -c "
import tempfile, app as a
with tempfile.TemporaryDirectory() as d:
    a.app.config['NOTES_DIR'] = d
    a.app.config['TESTING'] = True
    c = a.app.test_client()
    assert c.get('/').status_code == 200
    r = c.post('/api/notes', json={'filename': 'Smoke Test'})
    assert r.status_code == 201
    nid = r.get_json()['id']
    assert c.put(f'/api/notes/{nid}', json={'content': '# Hello'}).status_code == 200
    assert c.get(f'/api/notes/{nid}').get_json()['content'] == '# Hello'
    assert c.get('/api/export').status_code == 200
    print('Smoke test OK')
"
```

When changing frontend behavior (`static/index.html`), also verify interactively in a browser:
- Edit in CodeMirror (smart lists, brackets, shortcuts, `/` menu) and verify live preview updates cleanly.
- Edit directly in preview (paragraphs, `Enter` inside fenced code blocks, checkboxes, `/` commands, `/table` `+` row/column and column types) and verify clean Markdown appears in CodeMirror and persists across reload.
- Verify XSS safety by testing `<script>alert(1)</script>` and `<img src=x onerror=alert(1)>` in a note.
