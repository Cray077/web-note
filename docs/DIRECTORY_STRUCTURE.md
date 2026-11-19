# Directory Structure

## Repository Tree

```text
web-npp/
├── AGENTS.md                                  # AI coding agent entry point
├── app.py                                     # Single-file Flask backend & SQLite setup (275 lines)
├── requirements.txt                           # Python dependencies (flask, gunicorn)
├── .gitignore                                 # Ignores .venv/, data/, SQLite files, caches, backups
├── docs/                                      # Persistent project documentation for AI & developers
│   ├── PROJECT_OVERVIEW.md
│   ├── ARCHITECTURE.md
│   ├── DIRECTORY_STRUCTURE.md
│   ├── DATABASE_SCHEMA.md
│   ├── API_REFERENCE.md
│   ├── COMPONENTS.md
│   ├── CODING_CONVENTIONS.md
│   ├── DEVELOPMENT_SETUP.md
│   ├── DEVELOPMENT_STATUS.md
│   └── ROADMAP.md
├── static/
│   ├── index.html                             # Complete frontend SPA: HTML, CSS, vanilla JS (2,599 lines)
│   └── vendor/                                # Pinned third-party libraries (served locally, no CDN)
│       ├── marked.min.js                      # marked v18.2.1 (UMD build, 52.9 KB)
│       ├── purify.min.js                      # DOMPurify v3.4.18 (UMD build, 29.3 KB)
│       ├── turndown.min.js                    # turndown v7.2.5 (browser build, 26.9 KB)
│       ├── turndown-plugin-gfm.min.js         # turndown-plugin-gfm v1.0.2 (4.2 KB)
│       └── codemirror/                        # CodeMirror v5.65.16 (subset of core + mode + addons)
│           ├── lib/
│           │   ├── codemirror.css             # Core editor layout & default Markdown token colors
│           │   └── codemirror.js              # Core CodeMirror 5 editor engine
│           ├── mode/
│           │   ├── xml/xml.js                 # Required dependency of Markdown mode
│           │   ├── meta.js                    # Mode metadata (required before markdown.js)
│           │   └── markdown/markdown.js       # Markdown syntax mode
│           └── addon/
│               ├── edit/
│               │   ├── continuelist.js        # Markdown list & quote continuation on Enter
│               │   └── closebrackets.js       # Selective bracket/backtick auto-closing
│               └── hint/
│                   ├── show-hint.css          # Popup hint menu base styles
│                   └── show-hint.js           # CodeMirror '/' slash command popup engine
├── .venv/                                     # (Gitignored) Local Python virtual environment
└── data/                                      # (Gitignored) Local dev storage when NOTES_DIR=./data
    ├── notes.db                               # SQLite metadata database (+ -wal / -shm when active)
    └── <id>.md                                # Individual UTF-8 Markdown note files
```

## Main Entry Points

- **Backend WSGI / CLI entry point:** `app.py`
  - WSGI callable for Gunicorn: `app:app` (`app.py:15`)
  - Local dev server block: `if __name__ == "__main__": app.run(...)` (`app.py:274-275`)
- **Frontend entry point:** `static/index.html`
  - Served at `GET /` via `send_from_directory(app.static_folder, "index.html")` (`app.py:136-138`)
  - Self-bootstraps via `init()` at `static/index.html:2595`

## Static Asset Load Order (`static/index.html`)

Flask automatically serves everything under `static/` at `/static/...`. `static/index.html` loads local assets in a strict dependency order:

1. **Stylesheets (`<head>`, `static/index.html:7-8`):**
   - `/static/vendor/codemirror/lib/codemirror.css`
   - `/static/vendor/codemirror/addon/hint/show-hint.css`
   - Followed by the inline `<style>` block (`static/index.html:9-696`) so app overrides take precedence.
2. **Scripts (`<body>`, `static/index.html:734-744`):**
   1. `/static/vendor/marked.min.js` → exposes `window.marked`
   2. `/static/vendor/purify.min.js` → exposes `window.DOMPurify`
   3. `/static/vendor/turndown.min.js` → exposes `window.TurndownService`
   4. `/static/vendor/turndown-plugin-gfm.min.js` → exposes `window.turndownPluginGfm`
   5. `/static/vendor/codemirror/lib/codemirror.js` → exposes `window.CodeMirror`
   6. `/static/vendor/codemirror/mode/xml/xml.js` *(must load before `markdown.js`)*
   7. `/static/vendor/codemirror/mode/meta.js` *(must load before `markdown.js`)*
   8. `/static/vendor/codemirror/mode/markdown/markdown.js`
   9. `/static/vendor/codemirror/addon/edit/continuelist.js`
   10. `/static/vendor/codemirror/addon/edit/closebrackets.js`
   11. `/static/vendor/codemirror/addon/hint/show-hint.js`
   12. Inline application `<script>` (`static/index.html:745-2597`)

## Runtime Directories (Gitignored)

- **`data/` (development) or `/var/notes/` (production default):** Created automatically by `init_db()` (`app.py:39`) on first DB access. Holds `notes.db`, optional SQLite WAL sidecar files (`notes.db-wal`, `notes.db-shm`), temporary atomic write files (`.*.tmp`, removed immediately after `os.replace`), and `<id>.md` files.
- **`.venv/`:** Local Python virtual environment excluded via `.gitignore`.
