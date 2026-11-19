# Roadmap

This roadmap separates explicitly deferred/optional items noted during project scoping from technical maintenance items observed in the current codebase. None of the items below are implemented yet.

## Optional Future Features (Explicitly Noted as Possible Later)

These items were explicitly deferred as optional in the project briefs and remain unimplemented unless requested:

- **Rename note:** One extra backend route (e.g., `PATCH /api/notes/<id>` updating `notes.filename` without touching `<id>.md`) and a UI trigger.
- **Delete note:** One extra backend route (e.g., `DELETE /api/notes/<id>` removing the DB row and unlinking `<id>.md`) with a confirmation prompt, plus closing any open tab for that note.
- **Cross-note autocomplete & note-to-note links:** Wikilinks or `/` completion referencing other note titles in the database.

## Technical Maintenance & Hardening Candidates

Grounded in verified findings from `docs/DEVELOPMENT_STATUS.md` (only to be pursued when prioritized):

1. **Automated test suite:** Commit a lightweight `pytest` / `unittest` suite covering `app.py` (CRUD, atomic writes, path traversal, 5 MB `413` limit, ZIP export sanitization/deduplication) and browser E2E checks (CodeMirror editing, live-preview round-trip, slash commands, typed tables, XSS sanitization).
2. **Modularize frontend static files (still zero-build):** If `static/index.html` (currently 2,599 lines) continues to grow, split CSS and JS into plain static files under `static/` (`app.css`, `editor.js`, `preview.js`, `tables.js`) loaded via `<link>` / `<script>` without introducing a bundler.
3. **Cross-browser & mobile testing:** Verify `contenteditable` preview editing, `insertLineBreak` inside `<pre>`, `/table` column controls, and `Ctrl/Cmd+B/I/K` shortcut handling across Firefox, Safari, and mobile browsers.
4. **Unload flush fallback for > 64 KB notes:** Warn via `beforeunload` when `dirty` and `cm.getValue().length` exceeds the browser `keepalive` ~64 KB cap.
5. **Production ops templates:** Optionally add example `systemd` unit and `Caddyfile` templates (with `basic_auth` / reverse proxy) once VPS deployment is finalized.
6. **Table ergonomics:** Optionally add remove-row / remove-column controls or configurable currency symbol/locale if table usage expands.

## Explicit Non-Goals (Out of Scope by Design)

Unless project requirements change, do **not** add:
- Build pipelines, bundlers, or SPA frameworks (React, Vue, Vite, Webpack, CodeMirror 6).
- External CDN script/stylesheet links.
- User accounts / built-in authentication (handle at Caddy/VPN/firewall layer).
- Folders, tags, sharing, or note version history.
- Syntax-highlighted code blocks in preview, vim keybindings, themes, settings panels, or formatting toolbars.
