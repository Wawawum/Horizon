// Horizon WYSIWYG editor — CKEditor 5 inside a QWebEngineView.
//
// Same contract with Python as editor.js (widgets/webeditor.py keeps the mirror and the
// generation counter); only the document changes: it is HTML instead of markdown.
// CKEditor 5 is used under the GPL — see THIRD-PARTY-NOTICES.md.
//
// Bundled by esbuild in IIFE format — see web/README.md for why ESM would break.

import {
  ClassicEditor, Essentials, Paragraph, Heading, Bold, Italic, Underline, Strikethrough,
  Code, List, BlockQuote, Link, Table, TableToolbar, CodeBlock, Image, ImageUpload,
  ImageToolbar, ImageCaption, ImageTextAlternative, HorizontalLine, Autoformat,
} from "ckeditor5";
import translations from "ckeditor5/translations/fr.js";
import "ckeditor5/ckeditor5.css";

// Unlike CodeMirror's doc.toString(), CKEditor's getData() serialises the whole model to
// HTML on the main thread: ~5 ms on a short note, ~100 ms on a long one. Pushed after every
// keystroke (people type slower than a 120 ms debounce), it froze rendering and made the
// last typed letter vanish and come back. So the mirror is only refreshed on a real pause,
// when the browser is idle; blur, Ctrl+S and Python's flush() still read it at once.
const PUSH_IDLE_MS = 1500;
const PUSH_IDLE_TIMEOUT_MS = 1000;
const DEFAULT_FONT_SIZE = 13;
const MIN_FONT_SIZE = 8;
const MAX_FONT_SIZE = 32;

let editor = null;
let bridge = null;
let generation = 0;
let pushTimer = null;
let pushIdle = null;
let dirtySinceLastPush = false;
let fromPython = false;
let fontSize = DEFAULT_FONT_SIZE;

function cancelScheduledPush() {
  if (pushTimer !== null) {
    clearTimeout(pushTimer);
    pushTimer = null;
  }
  if (pushIdle !== null) {
    cancelIdleCallback(pushIdle);
    pushIdle = null;
  }
}

function pushNow() {
  cancelScheduledPush();
  // Nothing new since the last push: skip the serialisation (blur, Ctrl+S on a clean doc).
  if (!bridge || !editor || !dirtySinceLastPush) return;
  bridge.push_text(editor.getData(), generation);
  dirtySinceLastPush = false;
}

function schedulePush() {
  cancelScheduledPush();
  pushTimer = setTimeout(() => {
    pushTimer = null;
    pushIdle = requestIdleCallback(pushNow, { timeout: PUSH_IDLE_TIMEOUT_MS });
  }, PUSH_IDLE_MS);
}

function onDataChanged() {
  if (fromPython) return;
  // Tell Python immediately that JS holds unpushed state, so its flush() knows
  // whether it needs to spin an event loop at all.
  if (!dirtySinceLastPush && bridge) {
    dirtySinceLastPush = true;
    bridge.mark_dirty();
  }
  schedulePush();
}

function applyFontSize(px) {
  fontSize = Math.max(MIN_FONT_SIZE, Math.min(MAX_FONT_SIZE, Math.round(px)));
  document.documentElement.style.setProperty("--hz-editor-font-size", fontSize + "px");
}

function setFontSize(px) {
  const before = fontSize;
  applyFontSize(px);
  if (fontSize !== before && bridge) bridge.set_font_size_from_js(fontSize);
}

// ── Images ──────────────────────────────────────────────────────────────────
// Pasted or dropped images go to Python's ImageRepository; the document only keeps
// a horizon-image://<id> reference, served back by a Qt URL scheme handler.

function HorizonUploadAdapter(ed) {
  ed.plugins.get("FileRepository").createUploadAdapter = (loader) => ({
    upload: () =>
      loader.file.then(
        (file) =>
          new Promise((resolve, reject) => {
            bridge.image_upload_started();
            const reader = new FileReader();
            reader.onerror = () => {
              bridge.image_upload_finished(false);
              reject("Horizon: could not read pasted image");
            };
            reader.onload = () => {
              bridge.store_image(String(reader.result), (imageId) => {
                if (imageId > 0) {
                  bridge.image_upload_finished(true);
                  resolve({ default: "horizon-image://" + imageId });
                } else {
                  bridge.image_upload_finished(false);
                  reject("Horizon: image store failed");
                }
              });
            };
            reader.readAsDataURL(file);
          })
      ),
    abort() {},
  });
}

// ── Links ───────────────────────────────────────────────────────────────────
// The page must never navigate: Ctrl+click in the text, or a click on the link shown
// in CKEditor's balloon, is handed to Python, which opens notes, tasks and URLs.

function linkHandlers(ed) {
  ed.ui.getEditableElement().addEventListener(
    "click",
    (e) => {
      if (!e.ctrlKey) return;
      const a = e.target.closest && e.target.closest("a[href]");
      if (!a) return;
      e.preventDefault();
      e.stopPropagation();
      if (bridge) bridge.open_link(a.getAttribute("href"));
    },
    true
  );
  document.addEventListener(
    "click",
    (e) => {
      const a = e.target.closest && e.target.closest(".ck-balloon-panel a[href]");
      if (!a) return;
      e.preventDefault();
      e.stopPropagation();
      if (bridge) bridge.open_link(a.getAttribute("href"));
    },
    true
  );
}

function keyHandlers() {
  window.addEventListener(
    "keydown",
    (e) => {
      if (!e.ctrlKey || e.altKey) return;
      const key = e.key.toLowerCase();
      if (key === "s") {
        e.preventDefault();
        pushNow();
        if (bridge) bridge.shortcut("save");
      } else if (key === "+" || key === "=") {
        e.preventDefault();
        setFontSize(fontSize + 1);
      } else if (key === "-") {
        e.preventDefault();
        setFontSize(fontSize - 1);
      } else if (key === "0") {
        e.preventDefault();
        setFontSize(DEFAULT_FONT_SIZE);
      }
    },
    true
  );
  window.addEventListener(
    "wheel",
    (e) => {
      if (!e.ctrlKey) return;
      e.preventDefault();
      setFontSize(fontSize + (e.deltaY < 0 ? 1 : -1));
    },
    { passive: false, capture: true }
  );
}

function preventFileDrops() {
  // Dropping a file outside the editable navigates the page to it, destroying the
  // editor. Drops on the editable are CKEditor's (image upload).
  const stop = (e) => {
    if (e.target.closest && e.target.closest(".ck-editor__editable")) return;
    if (e.dataTransfer && Array.from(e.dataTransfer.types || []).includes("Files")) {
      e.preventDefault();
      e.stopPropagation();
    }
  };
  window.addEventListener("dragover", stop, true);
  window.addEventListener("drop", stop, true);
}

// ── Setup ───────────────────────────────────────────────────────────────────

function createEditor(state) {
  return ClassicEditor.create(document.getElementById("editor"), {
    licenseKey: "GPL",
    language: "fr",
    translations: [translations],
    placeholder: state.placeholder || "",
    plugins: [
      Essentials, Paragraph, Heading, Bold, Italic, Underline, Strikethrough, Code,
      List, BlockQuote, Link, Table, TableToolbar, CodeBlock, Image, ImageUpload,
      ImageToolbar, ImageCaption, ImageTextAlternative, HorizontalLine, Autoformat,
      HorizonUploadAdapter,
    ],
    toolbar: {
      items: [
        "undo", "redo", "|", "heading", "|", "bold", "italic", "underline",
        "strikethrough", "code", "|", "bulletedList", "numberedList", "blockQuote", "|",
        "link", "insertTable", "codeBlock", "uploadImage", "horizontalLine",
      ],
      shouldNotGroupWhenFull: false,
    },
    // Titre N = <hN>, comme en markdown (CKEditor décale d'un niveau par défaut).
    heading: {
      options: [
        { model: "paragraph", title: "Paragraphe", class: "ck-heading_paragraph" },
        { model: "heading1", view: "h1", title: "Titre 1", class: "ck-heading_heading1" },
        { model: "heading2", view: "h2", title: "Titre 2", class: "ck-heading_heading2" },
        { model: "heading3", view: "h3", title: "Titre 3", class: "ck-heading_heading3" },
        { model: "heading4", view: "h4", title: "Titre 4", class: "ck-heading_heading4" },
      ],
    },
    link: { allowedProtocols: ["horizon"] },
    table: { contentToolbar: ["tableColumn", "tableRow", "mergeTableCells"] },
    image: { toolbar: ["imageTextAlternative", "toggleImageCaption"] },
    codeBlock: {
      languages: [
        { language: "plaintext", label: "Texte brut" },
        { language: "python", label: "Python" },
        { language: "csharp", label: "C#" },
        { language: "javascript", label: "JavaScript" },
        { language: "typescript", label: "TypeScript" },
        { language: "sql", label: "SQL" },
        { language: "json", label: "JSON" },
        { language: "yaml", label: "YAML" },
        { language: "xml", label: "XML" },
        { language: "html", label: "HTML" },
        { language: "css", label: "CSS" },
        { language: "powershell", label: "PowerShell" },
        { language: "bash", label: "Bash" },
        { language: "dockerfile", label: "Dockerfile" },
        { language: "mermaid", label: "Mermaid" },
      ],
    },
  });
}

function init() {
  preventFileDrops();
  keyHandlers();
  applyFontSize(DEFAULT_FONT_SIZE);

  new QWebChannel(qt.webChannelTransport, (channel) => {
    bridge = channel.objects.bridge;
    // Before the editor exists these are dropped: the state pulled once it does
    // carries the latest document anyway.
    bridge.set_text_requested.connect((text, gen, normalize) => {
      if (editor) window.HorizonEditor.setText(text, gen, normalize);
    });
    // The editor is created only once the initial state is known: CKEditor reads its
    // placeholder from the config, and the toolbar choice is made before first paint.
    bridge.get_initial_state((state) => {
      state = state || {};
      if (state.show_toolbar === false) document.body.classList.add("no-toolbar");
      createEditor(state)
        .then((ed) => {
          editor = ed;
          editor.model.document.on("change:data", onDataChanged);
          editor.ui.focusTracker.on("change:isFocused", (evt, name, isFocused) => {
            if (isFocused) return;
            // Push synchronously before telling Python focus was lost: QWebChannel
            // preserves call order, so the mirror is exact by the time Python's
            // editing_finished handler runs.
            pushNow();
            if (bridge) bridge.editor_blurred();
          });
          linkHandlers(editor);
          installApi();
          // Pulled again: CKEditor starts asynchronously, and Python may have loaded
          // another note or toggled read-only (call_js lands nowhere) in the meantime.
          bridge.get_initial_state((latest) => {
            latest = latest || state;
            if (latest.font_size) window.HorizonEditor.setFontSize(latest.font_size);
            window.HorizonEditor.setText(latest.text || "", latest.generation || 0, !!latest.normalize);
            window.HorizonEditor.setReadOnly(!!latest.read_only);
            bridge.editor_ready();
          });
        })
        .catch((err) => console.error("Horizon: CKEditor failed to start", err));
    });
  });
}

function installApi() {
  window.HorizonEditor = {
    setText(text, gen, normalize) {
      generation = gen;
      cancelScheduledPush();
      dirtySinceLastPush = false;
      fromPython = true;
      try {
        editor.setData(text);
      } finally {
        fromPython = false;
      }
      document.querySelector(".ck-editor__main").scrollTop = 0;
      // After a markdown → HTML conversion the stored HTML is QTextDocument's, full of
      // inline styles; pushing CKEditor's own serialisation back lets Python save the
      // normalised form. Never done on an ordinary load, where it would look like an edit.
      if (normalize && editor.getData() !== text) {
        dirtySinceLastPush = true;
        bridge.mark_dirty();
        pushNow();
      }
    },
    readDoc() {
      // Python's flush() takes this as the mirror: the pending idle push would only
      // serialise the same document a second time.
      cancelScheduledPush();
      dirtySinceLastPush = false;
      return editor.getData();
    },
    setReadOnly(ro) {
      if (ro) editor.enableReadOnlyMode("horizon");
      else editor.disableReadOnlyMode("horizon");
    },
    setFontSize(px) {
      // Applied without notifying Python — this is Python telling us.
      applyFontSize(px);
    },
    setPlaceholder(text) {
      const root = editor.editing.view.document.getRoot();
      if (root) root.placeholder = text;
    },
    focusEditor() {
      editor.editing.view.focus();
    },
  };
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
