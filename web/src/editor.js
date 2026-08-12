// Horizon markdown editor — CodeMirror 6 inside a QWebEngineView.
//
// Talks to Python over QWebChannel. The Python side (widgets/webeditor.py) keeps a
// mirror of the document so that `text()` stays synchronous; this file is responsible
// for keeping that mirror fresh and for never letting a programmatic `setText` echo
// back as if it were a user edit.
//
// Bundled by esbuild in IIFE format — see web/README.md for why ESM would break.

import { EditorState, Compartment, Prec, Annotation } from "@codemirror/state";
import {
  EditorView, keymap, drawSelection, dropCursor, rectangularSelection,
  crosshairCursor, highlightActiveLine, highlightActiveLineGutter,
  highlightSpecialChars, placeholder as cmPlaceholder,
} from "@codemirror/view";
import { defaultKeymap, history, historyKeymap, indentWithTab } from "@codemirror/commands";
import {
  syntaxHighlighting, HighlightStyle, bracketMatching, indentOnInput,
  foldGutter, foldKeymap, LanguageDescription,
} from "@codemirror/language";
import { closeBrackets, closeBracketsKeymap } from "@codemirror/autocomplete";
import { search, searchKeymap, highlightSelectionMatches } from "@codemirror/search";
import { markdown } from "@codemirror/lang-markdown";
import { tags as t } from "@lezer/highlight";

// ── Fenced-code sublanguages ────────────────────────────────────────────────
// A curated list rather than @codemirror/language-data: the latter loads grammars
// through dynamic import(), which esbuild cannot code-split in IIFE format, so it
// would inline every grammar it knows (~2 MB). These mirror the languages the app
// already vendors highlight.js modes for, plus the obvious web/data formats.
import { python } from "@codemirror/lang-python";
import { javascript } from "@codemirror/lang-javascript";
import { json } from "@codemirror/lang-json";
import { sql } from "@codemirror/lang-sql";
import { html } from "@codemirror/lang-html";
import { css } from "@codemirror/lang-css";
import { yaml } from "@codemirror/lang-yaml";
import { xml } from "@codemirror/lang-xml";
import { StreamLanguage } from "@codemirror/language";
import { powerShell } from "@codemirror/legacy-modes/mode/powershell";
import { shell } from "@codemirror/legacy-modes/mode/shell";
import { csharp } from "@codemirror/legacy-modes/mode/clike";
import { dockerFile } from "@codemirror/legacy-modes/mode/dockerfile";

const codeLanguages = [
  LanguageDescription.of({ name: "python", alias: ["py"], load: async () => python() }),
  LanguageDescription.of({ name: "javascript", alias: ["js", "ts", "typescript", "jsx", "tsx"], load: async () => javascript() }),
  LanguageDescription.of({ name: "json", load: async () => json() }),
  LanguageDescription.of({ name: "sql", load: async () => sql() }),
  LanguageDescription.of({ name: "html", alias: ["htm"], load: async () => html() }),
  LanguageDescription.of({ name: "css", load: async () => css() }),
  LanguageDescription.of({ name: "yaml", alias: ["yml"], load: async () => yaml() }),
  LanguageDescription.of({ name: "xml", load: async () => xml() }),
  LanguageDescription.of({ name: "powershell", alias: ["ps1", "pwsh"], load: async () => StreamLanguage.define(powerShell) }),
  LanguageDescription.of({ name: "shell", alias: ["sh", "bash"], load: async () => StreamLanguage.define(shell) }),
  LanguageDescription.of({ name: "csharp", alias: ["cs", "c#"], load: async () => StreamLanguage.define(csharp) }),
  LanguageDescription.of({ name: "dockerfile", alias: ["docker"], load: async () => StreamLanguage.define(dockerFile) }),
];

// ── Theme ───────────────────────────────────────────────────────────────────
// Colours come from CSS custom properties emitted by theme.to_css_variables()
// into the page's <style>, so nothing is hardcoded here.

const CHROME_THEME = EditorView.theme({
  "&": {
    backgroundColor: "var(--hz-input-bg)",
    color: "var(--hz-text)",
    height: "100%",
  },
  ".cm-content": {
    fontFamily: "'JetBrains Mono', monospace",
    caretColor: "var(--hz-accent-color)",
    padding: "8px 0",
  },
  ".cm-scroller": { fontFamily: "'JetBrains Mono', monospace", overflow: "auto" },
  "&.cm-focused": { outline: "none" },
  ".cm-cursor, .cm-dropCursor": { borderLeftColor: "var(--hz-accent-color)", borderLeftWidth: "2px" },
  // The focused rule needs CodeMirror's own selector shape to win on specificity:
  // its default theme ships "&light.cm-focused > .cm-scroller > .cm-selectionLayer
  // .cm-selectionBackground", which outranks a plain "&.cm-focused .cm-selectionBackground"
  // and would otherwise override this colour for as long as the editor has focus.
  ".cm-selectionBackground, .cm-content ::selection": {
    backgroundColor: "var(--hz-editor-selection-bg)",
  },
  "&.cm-focused > .cm-scroller > .cm-selectionLayer .cm-selectionBackground": {
    backgroundColor: "var(--hz-editor-selection-bg)",
  },
  // Must stay translucent: highlightActiveLine decorates the line regardless of
  // whether the selection is empty, and the line background paints above the
  // selection layer — an opaque colour here hides the selection entirely.
  ".cm-activeLine": { backgroundColor: "var(--hz-editor-active-line-bg)" },
  ".cm-gutters": {
    backgroundColor: "var(--hz-surface-alt-bg)",
    color: "var(--hz-editor-syntax-muted)",
    border: "none",
    borderRight: "1px solid var(--hz-border)",
  },
  ".cm-activeLineGutter": { backgroundColor: "var(--hz-button-hover)" },
  ".cm-foldPlaceholder": {
    backgroundColor: "var(--hz-button-bg)",
    border: "1px solid var(--hz-border)",
    color: "var(--hz-editor-syntax-muted)",
  },
  ".cm-selectionMatch": { backgroundColor: "var(--hz-list-selected-bg)" },
  ".cm-searchMatch": {
    backgroundColor: "var(--hz-list-selected-bg)",
    outline: "1px solid var(--hz-accent-color)",
  },
  ".cm-searchMatch.cm-searchMatch-selected": { backgroundColor: "var(--hz-accent-color)33" },
  ".cm-panels": {
    backgroundColor: "var(--hz-surface-alt-bg)",
    color: "var(--hz-text)",
    border: "1px solid var(--hz-border)",
  },
  ".cm-panels input, .cm-panels button": {
    backgroundColor: "var(--hz-input-bg)",
    color: "var(--hz-text)",
    border: "1px solid var(--hz-border)",
    borderRadius: "3px",
    padding: "2px 6px",
  },
  ".cm-placeholder": { color: "var(--hz-editor-syntax-muted)", fontStyle: "italic" },
}, { dark: false });

const SYNTAX_STYLE = HighlightStyle.define([
  { tag: t.heading1, color: "var(--hz-accent-color)", fontWeight: "bold", fontSize: "1.5em" },
  { tag: t.heading2, color: "var(--hz-accent-color)", fontWeight: "bold", fontSize: "1.3em" },
  { tag: t.heading3, color: "var(--hz-accent-color)", fontWeight: "bold", fontSize: "1.15em" },
  { tag: [t.heading4, t.heading5, t.heading6], color: "var(--hz-accent-color)", fontWeight: "bold" },
  { tag: t.strong, fontWeight: "bold" },
  { tag: t.emphasis, fontStyle: "italic" },
  { tag: t.strikethrough, textDecoration: "line-through" },
  { tag: [t.link, t.url], color: "var(--hz-preview-link)", textDecoration: "underline" },
  { tag: t.monospace, fontFamily: "'JetBrains Mono', monospace", backgroundColor: "var(--hz-preview-code-bg)" },
  { tag: t.quote, color: "var(--hz-preview-blockquote-text)", fontStyle: "italic" },
  { tag: t.list, color: "var(--hz-accent-color)" },
  // The literal syntax markers: #, -, **, ``, > …
  { tag: t.processingInstruction, color: "var(--hz-editor-syntax-muted)" },
  { tag: t.contentSeparator, color: "var(--hz-editor-syntax-muted)" },
  // Inside fenced code blocks
  { tag: t.keyword, color: "#8250df" },
  { tag: [t.string, t.special(t.string)], color: "#0a7d33" },
  { tag: [t.number, t.bool, t.null], color: "#0550ae" },
  { tag: t.comment, color: "var(--hz-editor-syntax-muted)", fontStyle: "italic" },
  { tag: [t.function(t.variableName), t.labelName], color: "#8250df" },
  { tag: [t.typeName, t.className], color: "#953800" },
  { tag: t.operator, color: "var(--hz-editor-syntax-muted)" },
]);

// ── Runtime state ───────────────────────────────────────────────────────────

const DEFAULT_FONT_SIZE = 13;
const MIN_FONT_SIZE = 8;
const MAX_FONT_SIZE = 40;
const PUSH_DEBOUNCE_MS = 120;

const fontSizeComp = new Compartment();
const readOnlyComp = new Compartment();
const placeholderComp = new Compartment();

// Marks transactions that originate from Python, so the update listener does not
// echo them back as user edits.
const fromPython = Annotation.define();

let view = null;
let bridge = null;
let generation = 0;
let fontSize = DEFAULT_FONT_SIZE;
let pushTimer = null;
let dirtySinceLastPush = false;

// Insertion points awaiting an async round trip (image paste). Each is mapped
// through every intervening change so the token lands where the user pasted.
const pendingAnchors = [];

function fontTheme(px) {
  return EditorView.theme({
    "&": { fontSize: px + "px" },
    ".cm-gutters": { fontSize: px + "px" },
  });
}

function pushNow() {
  if (pushTimer !== null) {
    clearTimeout(pushTimer);
    pushTimer = null;
  }
  if (!bridge || !view) return;
  bridge.push_text(view.state.doc.toString(), generation);
  dirtySinceLastPush = false;
}

function schedulePush() {
  if (pushTimer !== null) clearTimeout(pushTimer);
  pushTimer = setTimeout(pushNow, PUSH_DEBOUNCE_MS);
}

function onDocChanged(update) {
  // Map any anchors waiting on an async insert.
  for (const anchor of pendingAnchors) {
    anchor.pos = update.changes.mapPos(anchor.pos);
  }
  if (update.transactions.some((tr) => tr.annotation(fromPython))) return;
  // Tell Python immediately that JS holds unpushed state, so its flush() knows
  // whether it needs to spin an event loop at all.
  if (!dirtySinceLastPush && bridge) {
    dirtySinceLastPush = true;
    bridge.mark_dirty();
  }
  schedulePush();
}

function setFontSize(px) {
  px = Math.max(MIN_FONT_SIZE, Math.min(MAX_FONT_SIZE, Math.round(px)));
  if (px === fontSize) return;
  fontSize = px;
  view.dispatch({ effects: fontSizeComp.reconfigure(fontTheme(px)) });
  if (bridge) bridge.set_font_size_from_js(px);
}

function stepFontSize(delta) {
  setFontSize(fontSize + delta);
}

// ── Toolbar commands (ports of the old QTextCursor handlers) ────────────────

const HEADING_PREFIX_RE = /^#{1,6} +/;

function currentLines() {
  const { state } = view;
  const from = state.selection.main.from;
  const to = state.selection.main.to;
  const first = state.doc.lineAt(from).number;
  const last = state.doc.lineAt(to).number;
  const out = [];
  for (let n = first; n <= last; n++) out.push(state.doc.line(n));
  return out;
}

function setHeading(level) {
  const line = view.state.doc.lineAt(view.state.selection.main.head);
  const stripped = line.text.replace(HEADING_PREFIX_RE, "");
  const insert = "#".repeat(level) + " " + stripped;
  view.dispatch({
    changes: { from: line.from, to: line.to, insert },
    selection: { anchor: line.from + insert.length },
  });
  view.focus();
}

function toggleBulletList() {
  const lines = currentLines();
  const nonEmpty = lines.filter((l) => l.text.trim().length > 0);
  if (nonEmpty.length === 0) {
    view.focus();
    return;
  }
  const allBulleted = nonEmpty.every((l) => l.text.startsWith("- "));
  const changes = nonEmpty.map((l) =>
    allBulleted
      ? { from: l.from, to: l.from + 2, insert: "" }
      : { from: l.from, insert: "- " }
  );
  // One transaction => one undo step, matching beginEditBlock/endEditBlock.
  view.dispatch({ changes });
  view.focus();
}

function wrapSelection(prefix, suffix, padIfAtLineEnd) {
  const { state } = view;
  const range = state.selection.main;
  const line = state.doc.lineAt(range.to);
  const atLineEnd = range.to === line.to;
  const pad = padIfAtLineEnd && atLineEnd ? " " : "";

  if (range.empty) {
    const insert = prefix + suffix + pad;
    view.dispatch({
      changes: { from: range.from, insert },
      selection: { anchor: range.from + prefix.length },
    });
  } else {
    const text = state.sliceDoc(range.from, range.to);
    const insert = prefix + text + suffix + pad;
    view.dispatch({
      changes: { from: range.from, to: range.to, insert },
      // Re-select the inner text, excluding the markers.
      selection: { anchor: range.from + prefix.length, head: range.from + prefix.length + text.length },
    });
  }
  view.focus();
}

function insertBlock(text) {
  const { state } = view;
  const pos = state.selection.main.head;
  const line = state.doc.lineAt(pos);
  const needsLeadingNl = pos !== line.from;
  const insert = (needsLeadingNl ? "\n" : "") + text + "\n";
  view.dispatch({
    changes: { from: pos, to: state.selection.main.to, insert },
    selection: { anchor: pos + insert.length },
  });
  view.focus();
}

function insertInline(text) {
  const { state } = view;
  const range = state.selection.main;
  view.dispatch({
    changes: { from: range.from, to: range.to, insert: text },
    selection: { anchor: range.from + text.length },
  });
  view.focus();
}

// ── Image paste ─────────────────────────────────────────────────────────────

function handlePaste(event) {
  const items = Array.from((event.clipboardData && event.clipboardData.items) || []);
  const imageItem = items.find((i) => i.kind === "file" && i.type.startsWith("image/"));
  if (!imageItem) return false; // let CodeMirror handle text/html normally

  event.preventDefault();
  const blob = imageItem.getAsFile();
  if (!blob || !bridge) return true;

  // Anchor the insertion point now; onDocChanged keeps it correct if the user
  // types while the round trip is in flight.
  const anchor = { pos: view.state.selection.main.head };
  pendingAnchors.push(anchor);

  const release = () => {
    const idx = pendingAnchors.indexOf(anchor);
    if (idx >= 0) pendingAnchors.splice(idx, 1);
  };

  bridge.image_upload_started();
  const reader = new FileReader();
  reader.onerror = () => {
    release();
    bridge.image_upload_finished(false);
    console.warn("Horizon: could not read pasted image");
  };
  reader.onload = () => {
    bridge.store_image(String(reader.result), (imageId) => {
      const pos = anchor.pos;
      release();
      if (imageId > 0) {
        const token = "![](horizon-image://" + imageId + ")";
        view.dispatch({
          changes: { from: pos, insert: token },
          selection: { anchor: pos + token.length },
        });
        bridge.image_upload_finished(true);
      } else {
        bridge.image_upload_finished(false);
        console.warn("Horizon: image store failed");
      }
      view.focus();
    });
  };
  reader.readAsDataURL(blob);
  return true;
}

// ── Setup ───────────────────────────────────────────────────────────────────

function buildExtensions() {
  return [
    highlightSpecialChars(),
    history(),
    drawSelection(),
    dropCursor(),
    EditorState.allowMultipleSelections.of(true),
    indentOnInput(),
    bracketMatching(),
    closeBrackets(),
    search({ top: true }),
    highlightSelectionMatches(),
    highlightActiveLine(),
    highlightActiveLineGutter(),
    foldGutter(),
    rectangularSelection(),
    crosshairCursor(),
    EditorView.lineWrapping,
    markdown({ codeLanguages }),
    syntaxHighlighting(SYNTAX_STYLE),
    CHROME_THEME,
    fontSizeComp.of(fontTheme(fontSize)),
    readOnlyComp.of([]),
    placeholderComp.of([]),
    Prec.highest(
      keymap.of([
        { key: "Mod-=", run: () => (stepFontSize(1), true) },
        { key: "Mod-+", run: () => (stepFontSize(1), true) },
        { key: "Mod-Shift-=", run: () => (stepFontSize(1), true) },
        { key: "Mod--", run: () => (stepFontSize(-1), true) },
        { key: "Mod-0", run: () => (setFontSize(DEFAULT_FONT_SIZE), true) },
        {
          key: "Mod-s",
          run: () => {
            pushNow();
            if (bridge) bridge.shortcut("save");
            return true;
          },
        },
      ])
    ),
    keymap.of([
      ...closeBracketsKeymap,
      ...defaultKeymap,
      ...historyKeymap,
      // Windows delivers AltGr as Ctrl+Alt. On an AZERTY layout AltGr+5 types "["
      // and AltGr+° types "]", which matched foldAll/unfoldAll and swallowed the
      // character. Fold stays reachable via Ctrl-Shift-[ / ] and the fold gutter.
      ...foldKeymap.filter((b) => b.key !== "Ctrl-Alt-[" && b.key !== "Ctrl-Alt-]"),
      ...searchKeymap,
      indentWithTab,
    ]),
    EditorView.updateListener.of((update) => {
      if (update.docChanged) onDocChanged(update);
    }),
    EditorView.domEventHandlers({
      paste: (event) => handlePaste(event),
      blur: () => {
        // Push synchronously before telling Python focus was lost: QWebChannel
        // preserves call order, so the mirror is exact by the time Python's
        // editing_finished handler runs.
        pushNow();
        if (bridge) bridge.editor_blurred();
        return false;
      },
      wheel: (event) => {
        if (!event.ctrlKey) return false;
        event.preventDefault();
        stepFontSize(event.deltaY < 0 ? 1 : -1);
        return true;
      },
    }),
  ];
}

function preventFileDrops() {
  // Dropping a file on a QWebEngineView navigates the page to it, destroying the
  // editor. CodeMirror handles text drops itself; file drops fall through here.
  const stop = (e) => {
    if (e.dataTransfer && Array.from(e.dataTransfer.types || []).includes("Files")) {
      e.preventDefault();
      e.stopPropagation();
    }
  };
  window.addEventListener("dragover", stop, true);
  window.addEventListener("drop", stop, true);
}

function init() {
  view = new EditorView({
    state: EditorState.create({ doc: "", extensions: buildExtensions() }),
    parent: document.getElementById("editor"),
  });

  preventFileDrops();

  window.HorizonEditor = {
    setText(text, gen) {
      generation = gen;
      if (pushTimer !== null) {
        clearTimeout(pushTimer);
        pushTimer = null;
      }
      dirtySinceLastPush = false;
      pendingAnchors.length = 0;
      view.dispatch({
        changes: { from: 0, to: view.state.doc.length, insert: text },
        selection: { anchor: 0 },
        annotations: fromPython.of(true),
      });
      view.scrollDOM.scrollTop = 0;
    },
    readDoc() {
      return view.state.doc.toString();
    },
    setReadOnly(ro) {
      view.dispatch({
        effects: readOnlyComp.reconfigure(
          ro ? [EditorState.readOnly.of(true), EditorView.editable.of(false)] : []
        ),
      });
    },
    setFontSize(px) {
      // Applied without notifying Python — this is Python telling us.
      px = Math.max(MIN_FONT_SIZE, Math.min(MAX_FONT_SIZE, Math.round(px)));
      fontSize = px;
      view.dispatch({ effects: fontSizeComp.reconfigure(fontTheme(px)) });
    },
    setPlaceholder(text) {
      view.dispatch({
        effects: placeholderComp.reconfigure(text ? cmPlaceholder(text) : []),
      });
    },
    focusEditor() {
      view.focus();
    },
    wrapSelection,
    setHeading,
    toggleBulletList,
    insertBlock,
    insertInline,
  };

  new QWebChannel(qt.webChannelTransport, (channel) => {
    bridge = channel.objects.bridge;
    bridge.set_text_requested.connect((text, gen) => {
      window.HorizonEditor.setText(text, gen);
    });
    // Pull the initial document: the page may have finished loading after Python
    // already had content to show. Same idiom as the preview page.
    bridge.get_initial_state((state) => {
      if (!state) return;
      generation = state.generation || 0;
      if (state.font_size) window.HorizonEditor.setFontSize(state.font_size);
      if (state.placeholder) window.HorizonEditor.setPlaceholder(state.placeholder);
      window.HorizonEditor.setText(state.text || "", generation);
      window.HorizonEditor.setReadOnly(!!state.read_only);
      bridge.editor_ready();
    });
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
