# web/ — source of the CodeMirror 6 editor bundle

This directory is **build-time only**. `python -m horizon` never invokes Node: it loads the
committed artifact `src/horizon/resources/horizon-editor.bundle.js` as a plain static file,
exactly like `mermaid.min.js` and `highlight.min.js`.

## Rebuilding

```bash
cd web
npm install
npm run build
```

Output: `src/horizon/resources/horizon-editor.bundle.js` (~702 KB minified).
Commit that file alongside your `src/editor.js` change — the Python side has no fallback.

`npm run build:dev` writes an unminified build with an inline sourcemap to the same path,
for local debugging. **Do not commit that output.**

## Constraints — read before changing the build

**`--format=iife` is mandatory, not a style preference.** The editor page is created with
`QWebEnginePage.setHtml(html, baseUrl)` where `baseUrl` is a `file://` directory URL. Classic
`<script src="file://…">` tags work in that context (the preview page already loads mermaid and
four highlight.js files this way), but ES modules are subject to module CORS against an opaque
origin and are blocked. Switching to `--format=esm` yields a blank editor and a console error.

**`--target=chrome110`** is a conservative floor for the Chromium inside PySide6's QtWebEngine.
Dropping the target lets esbuild assume `esnext`, which can emit syntax older Qt patch releases
reject.

**Do not add `@codemirror/language-data`.** Its `LanguageDescription`s load grammars through
dynamic `import()`, which esbuild cannot code-split in IIFE format — it would inline every
grammar it knows and roughly triple the bundle. Fenced-code sublanguages are instead listed
explicitly in the `codeLanguages` array at the top of `src/editor.js`; add imports there.

## Contract with the Python side

`src/horizon/widgets/webeditor.py` owns the other half. The bundle exposes `window.HorizonEditor`
(`setText`, `readDoc`, `setReadOnly`, `setFontSize`, `setPlaceholder`, `focusEditor`, plus the
toolbar commands) and talks back through the `bridge` object registered on the QWebChannel
(`push_text`, `mark_dirty`, `editor_blurred`, `editor_ready`, `store_image`, `set_font_size`,
`shortcut`, `image_upload_started/finished`).

Two invariants worth preserving if you touch this:

- **The generation counter.** `setText` bumps it; `push_text` carries it back and Python drops
  any push whose generation is stale. This is what replaces Qt's `blockSignals` and what stops
  a programmatic load (opening a historical version) from looking like a user edit.
- **`blur` pushes synchronously before signalling.** QWebChannel preserves call order, so
  Python's mirror is exact by the time its `editing_finished` handler runs.
