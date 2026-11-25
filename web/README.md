# web/ — source of the note editor bundles

This directory is **build-time only**. `python -m horizon` never invokes Node: it loads the
committed artifacts under `src/horizon/resources/` as plain static files, exactly like
`mermaid.min.js` and `highlight.min.js`.

| Source | Output | Editor |
|---|---|---|
| `src/editor.js` | `horizon-editor.bundle.js` (~702 KB) | CodeMirror 6, markdown notes |
| `src/wysiwyg.js` | `horizon-wysiwyg.bundle.js` (~1 MB) + `horizon-wysiwyg.bundle.css` (~266 KB) | CKEditor 5, WYSIWYG (HTML) notes |
| `src/mindmap.js` (+ `src/nodestyle.js`) | `horizon-mindmap.bundle.js` (~160 KB) + `horizon-mindmap.bundle.css` (~20 KB) | Mind Elixir, mind maps (Diagrams module) |

## Rebuilding

```bash
cd web
npm install
npm run build
```

`npm run build` builds every bundle; `npm run build:markdown`, `npm run build:wysiwyg` and
`npm run build:mindmap` build one. Commit the output alongside your source change — the Python side has no fallback.

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

**Mind Elixir, marked, DOMPurify and SnapDOM are pinned to exact versions** too; bumping one
means updating `THIRD-PARTY-NOTICES.md`. Mind Elixir 6 has no image export of its own: SnapDOM
captures the map's DOM instead.

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
`open_diagram`, `open_attachment`, `save_attachment` for the WYSIWYG editor, whose
`HorizonEditor` also has `insertDiagram`, `refreshDiagram`, `setCaretAt`, `insertBlocks` and
`setLinkTitle`).

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
- **Dropped files, e-mails and URLs are Python's.** `_WebEditorBase` intercepts those drops
  before Chromium; the page only places the caret (`setCaretAt`, in both bundles) and inserts
  what Python archived — `HorizonAttachment` widgets (`insertBlocks`) in CKEditor, markdown
  links (`insertBlock`, then `replaceFirst` for a fetched page title) in CodeMirror. See
  docs/architecture.md, "Dropped content in notes".
- **The page never navigates.** Ctrl+click on a link in the text, or a click on the link in
  CKEditor's balloon, is sent to Python through `open_link`.

## Mind map editor (`mindmap.js`)

`src/horizon/widgets/mindelixir.py` (`MindElixirEditor`) owns the other half. The page exposes
`window.HorizonMindmap` (`load(data, generation, rootTopic)`, `exportImage(fmt, requestId)`,
`readDoc()`) and calls `bridge.get_initial_state`, `push_data(json, generation)` (debounced
300 ms after each Mind Elixir operation; a stale generation is dropped), `editor_ready(generation)`
and `export_done(requestId, dataUri)`. An empty document starts a new map whose root topic is the
diagram title, pushed at once. The map always follows Horizon's light or dark theme.

- **Topics are Markdown.** Mind Elixir's `markdown` option renders topics, arrow and summary
  labels with marked (GFM, line breaks kept), sanitised by DOMPurify; the stored `topic` stays
  the Markdown source. Links get `target="_blank"`, and a click on any link in the page is
  sent to Python through `open_link` (http, https and mailto only), so the page never navigates.
- **Node style bar** (`src/nodestyle.js`). While nodes are selected, a bar above the map sets
  their font size, text colour, background, border width and border colour (`nodeObj.style`:
  `fontSize`, `color`, `background`, `borderWidth`, `borderColor`, plus `borderStyle: solid`
  when either border key is set) through `reshapeNode`, an undoable operation pushed like any
  edit. Colours come from a shared popover (16 colours, "Auto", a free colour picker).
  `reshapeNode` merges the previous style under the new one, so "Auto" stores the key as `""`
  rather than deleting it. `linkDiv` paints first-level topics' borders in their branch colour
  on every redraw; the bar wraps it on each instance to put a chosen border colour back.
- **Renderings are DOM captures.** SnapDOM captures `mind.nodes` (topics, branches, arrows,
  summaries) as an SVG with the HTML in a `<foreignObject>` and the fonts embedded; its
  `viewBox` is then cropped to the content plus 16 px, since `mind.nodes` carries the editor's
  wide `--map-padding`. The PNG thumbnail is that SVG drawn on a canvas. The selection is
  cleared first, so its outline is not in the picture.
