# web/ — source of the note editor bundles

This directory is **build-time only**. `python -m horizon` never invokes Node: it loads the
committed artifacts under `src/horizon/resources/` as plain static files, exactly like
`mermaid.min.js` and `highlight.min.js`.

| Source | Output | Editor |
|---|---|---|
| `src/editor.js` | `horizon-editor.bundle.js` (~702 KB) | CodeMirror 6, markdown notes |
| `src/wysiwyg.js` | `horizon-wysiwyg.bundle.js` (~1 MB) + `horizon-wysiwyg.bundle.css` (~266 KB) | CKEditor 5, WYSIWYG (HTML) notes |

## Rebuilding

```bash
cd web
npm install
npm run build
```

`npm run build` builds both bundles; `npm run build:markdown` and `npm run build:wysiwyg`
build one. Commit the output alongside your source change — the Python side has no fallback.

`npm run build:dev` writes unminified builds with inline sourcemaps to the same paths, for
local debugging. **Do not commit that output.**

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

**CKEditor 5 is pinned to an exact version and used under the GPL** (`licenseKey: 'GPL'`).
Bumping it means updating the version in `THIRD-PARTY-NOTICES.md`. Only the plugins listed in
`src/wysiwyg.js` are bundled; esbuild tree-shakes the rest of the `ckeditor5` package.

## Contract with the Python side

`src/horizon/widgets/webeditor.py` owns the other half (`WebMarkdownEditor` and
`WebHtmlEditor`, on a shared `_WebEditorBase`). Both bundles expose `window.HorizonEditor`
(`setText`, `readDoc`, `setReadOnly`, `setFontSize`, `setPlaceholder`, `focusEditor`, plus the
markdown toolbar commands in `editor.js`) and talk back through the `bridge` object registered
on the QWebChannel (`push_text`, `mark_dirty`, `editor_blurred`, `editor_ready`, `store_image`,
`set_font_size`, `shortcut`, `image_upload_started/finished`, and `open_link`, `pick_diagram`,
`open_diagram` for the WYSIWYG editor, whose `HorizonEditor` also has `insertDiagram` and
`refreshDiagram`).

Invariants worth preserving if you touch this:

- **The generation counter.** `setText` bumps it; `push_text` carries it back and Python drops
  any push whose generation is stale. This is what replaces Qt's `blockSignals` and what stops
  a programmatic load (opening a historical version) from looking like a user edit.
- **`blur` pushes synchronously before signalling.** QWebChannel preserves call order, so
  Python's mirror is exact by the time its `editing_finished` handler runs.

WYSIWYG specifics:

- **CKEditor starts asynchronously.** `window.HorizonEditor` only exists once it has; the page
  then pulls `get_initial_state()` a second time so that a note loaded meanwhile is not lost.
  `call_js()` is guarded and lands nowhere before that — the bridge carries the state.
- **The mirror is pushed on a pause, not per keystroke.** CKEditor's `getData()` serialises
  the whole document on the main thread (~100 ms on a long note); pushing it after every
  keystroke froze typing. The page pushes after 1.5 s of inactivity, in an idle callback;
  blur, Ctrl+S and `flush()` (`readDoc`) still read the document at once.
- **`setText(html, gen, normalize)`.** With `normalize`, the page pushes CKEditor's own
  serialisation straight back. Used only after a markdown → HTML conversion, whose stored HTML
  comes from `QTextDocument`; on an ordinary load it would look like an edit.
- **Images are references, not data.** Pasted images go to `ImageRepository` through
  `store_image`; the document keeps `<img src="horizon-image://<id>">`, served by the
  `_ImageSchemeHandler` installed on the editor profile. The scheme is registered in
  `__main__` (`register_schemes`) before `QApplication` exists, with the `LocalScheme` flag so
  the `file://` page may load it.
- **draw.io diagrams are references too.** The `HorizonDiagram` plugin stores
  `<figure class="horizon-diagram" data-diagram-id="<id>">` and renders it as a widget showing
  `horizon-diagram://<id>`, served by `_DiagramSchemeHandler`. The editing view adds a
  `?v=<page nonce>.<revision>` cache buster that `refreshDiagram` bumps; the data view does not,
  so a refresh is never an edit. See docs/architecture.md, "Diagrams in WYSIWYG notes".
- **The page never navigates.** Ctrl+click on a link in the text, or a click on the link in
  CKEditor's balloon, is sent to Python through `open_link`.
