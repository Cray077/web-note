# Development Status

## Current State

The application is **functional and actively developed** for local/self-hosted use.

- **Git status:** Repository is initialized on branch `master`, with **no commits yet** (`app.py`, `requirements.txt`, `.gitignore`, `static/` are currently untracked alongside this new `docs/` folder and `AGENTS.md`).
- **Local dev data:** A gitignored `data/` folder exists locally with 6 test notes in `data/notes.db` (WAL mode).

## Implemented Features (Verified in Source)

| Feature Area | Status | Primary Code Location |
| --- | --- | --- |
| Flask + SQLite WAL backend & atomic UTF-8 `.md` writes | Implemented | `app.py:1-275` |
| Note CRUD (`GET /api/notes`, `POST /api/notes`, `GET /api/notes/<id>`, `PUT /api/notes/<id>`) | Implemented | `app.py:141-242` |
| `.zip` export named after database `filename` (`<filename>.md`) | Implemented | `app.py:110-128`, `245-271` |
| Left sidebar (newest-first list, client-side search, `+ New Note`, `Export`) | Implemented | `static/index.html:700-709`, `1217-1284` |
| Multi-tab bar (`×` close, middle-click close, `+` new note, per-tab `CodeMirror.Doc`, `localStorage` persistence) | Implemented | `static/index.html:713-716`, `1351-1627` |
| Responsive layout + `Hide/Show sidebar`, `Hide/Show editor`, `Hide/Show preview` (`Preview`/`Edit` on `< 900px`) | Implemented | `static/index.html:718-722`, `1155-1180`, `2533-2561` |
| CodeMirror 5 Markdown editor (line numbers, wrapping, smart lists, Tab indent, auto-close brackets, `Ctrl/Cmd+B/I/K`, URL paste) | Implemented | `static/index.html:983-1119` |
| Live Markdown preview (`marked` + `DOMPurify` XSS sanitization) | Implemented | `static/index.html:789-805`, `959-979` |
| Editable live preview (`contenteditable="true"`) + two-way `Turndown` sync | Implemented | `static/index.html:807-956`, `1121-1153`, `2310-2487` |
| `/` slash command menu in both CodeMirror and live preview (12 commands incl. Image) | Implemented | `static/index.html:1005-1054`, `1648-1930` |
| Interactive tables (`+` add row/column, per-column types: Text, Number, Currency, Checkbox, Date, Tab/Enter cell nav) | Implemented | `static/index.html:1932-2325`, `2433-2486` |
| Debounced autosave (`800ms`), serialized in-flight saves, `pagehide` unload flush | Implemented | `static/index.html:1286-1350`, `1634-1645` |

## Known Limitations & Technical Debt

1. **Monolithic frontend file:** `static/index.html` is currently **2,599 lines (~82 KB)** combining CSS, HTML, and all JavaScript subsystems in a single file. While intentional for zero-build simplicity, further feature growth will make maintenance harder without splitting into separate static `.css` / `.js` files.
2. **No committed automated test suite:** Backend/asset verification was run via temporary ad-hoc scripts outside the repo; there is no `tests/` directory or CI workflow in the repository yet.
3. **Deprecated `document.execCommand()` API:** Preview editing uses `document.execCommand()` (`bold`, `italic`, `createLink`, `insertText`, `insertLineBreak`, `indent`, `outdent` at `static/index.html:2343`, `2421-2485`). Although still supported by Chromium, Firefox, and Safari, it is formally deprecated and exhibits minor cross-browser differences in `contenteditable` DOM structure.
4. **Raw HTML normalization on preview edits:** Notes containing raw inline HTML (e.g., `<p align="center"><b>...</b></p>`) render fine from CodeMirror, but editing on the live preview side converts the entire document through `Turndown`, normalizing raw HTML into standard Markdown.
5. **Empty typed table columns & currency locale:**
   - Column types (`number`, `currency`, `checkbox`, `date`) are inferred from cell values and `--:` alignment on reload (`inferColumnType()`, `static/index.html:2017-2042`). An empty `currency` or `date` column with no rows filled yet cannot be distinguished from `number` (`--:`) or `text` after a full page reload (checkbox columns persist immediately because empty rows write `[ ]`).
   - Currency formatting is hardcoded to `en-US` / `USD` (`$`, `static/index.html:1940-1943`).
6. **`pagehide` `keepalive` payload limit:** `flushOnUnload()` (`static/index.html:1634-1645`) uses `fetch(..., { keepalive: true })`, which browsers cap at **64 KB** per request. Notes larger than ~64 KB edited right before closing the tab may fail to flush during `pagehide` (normal 800 ms autosaves are unaffected up to the 5 MB limit).
7. **No rename or delete note endpoints:** Closing a tab removes it from the tab bar only; notes cannot be renamed or deleted through the UI or API.
8. **No built-in authentication or multi-client conflict resolution:** Concurrent edits to the same note from two browser tabs/devices use last-write-wins with no ETag/version check.
9. **Stored `notes.path` on directory relocation:** `notes.path` stores the absolute path at creation time (`app.py:169`), whereas reads/writes resolve via `note_file_path(note_id)`. Moving `NOTES_DIR` keeps the app working, but old rows retain stale `path` strings.

## Uncertainties & Areas Requiring Investigation

- **Cross-browser verification:** End-to-end automated browser testing was not executed in this environment (Chrome DevTools MCP was unavailable); live-preview `contenteditable`, slash menu caret positioning, `Enter` inside `<pre>`, and table `Tab`/`Enter` navigation have been verified manually by the user in Chromium but have not been systematically tested in Firefox, Safari, or mobile touch browsers (iOS Safari / Android Chrome).
- **Large note performance in editable preview:** Notes above `200 KB` switch to `500 ms` preview debounce, but full-document `Turndown` conversion (`previewToMarkdown(previewEl)`) + `cm.replaceRange` on every edit in a multi-megabyte note has not been benchmarked.
- **Production deployment artifacts:** No `systemd` unit file or `Caddyfile` is included in the repository yet (only deployment instructions in `docs/DEVELOPMENT_SETUP.md`).
