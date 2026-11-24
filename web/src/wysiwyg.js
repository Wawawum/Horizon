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
  ImageToolbar, ImageCaption, ImageTextAlternative, ImageStyle, TableProperties,
  HorizontalLine, Autoformat, IconObjectLeft, IconObjectCenter, Widget, toWidget, Command,
  ButtonView, Plugin, WidgetToolbarRepository, isWidget, FontColor, Highlight,
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

// ── Diagrams ────────────────────────────────────────────────────────────────
// A draw.io diagram is embedded by reference: the stored HTML is
// <figure class="horizon-diagram" data-diagram-id="12"><img src="horizon-diagram://12"></figure>,
// and the page shows whatever Python's scheme handler serves for that id — the diagram
// as it is now. Picking one (toolbar button) and editing one (double-click) are Python's.

const DIAGRAM_ICON =
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">' +
  '<rect x="1.75" y="2.75" width="7.5" height="5" rx="1" fill="none" stroke="currentColor" stroke-width="1.5"/>' +
  '<rect x="10.75" y="12.25" width="7.5" height="5" rx="1" fill="none" stroke="currentColor" stroke-width="1.5"/>' +
  '<path d="M5.5 7.75v7h5.25" fill="none" stroke="currentColor" stroke-width="1.5"/>' +
  "</svg>";

// Chromium caches images by URL for the life of the page, and this page outlives many
// notes. So the URL carries a per-page nonce and a per-diagram revision that
// refreshDiagram() bumps once Python has redrawn the diagram.
const PAGE_NONCE = Date.now().toString(36);
const diagramRevisions = new Map();

function diagramUrl(id) {
  return "horizon-diagram://" + id + "?v=" + PAGE_NONCE + "." + (diagramRevisions.get(id) || 0);
}

class InsertDiagramCommand extends Command {
  refresh() {
    const model = this.editor.model;
    const position = model.document.selection.getFirstPosition();
    this.isEnabled = model.schema.findAllowedParent(position, "horizonDiagram") !== null;
  }

  execute({ diagramId }) {
    const model = this.editor.model;
    model.change((writer) => {
      const diagram = writer.createElement("horizonDiagram", { diagramId });
      model.insertObject(diagram, null, null, { setSelection: "on" });
    });
  }
}

function HorizonDiagram(ed) {
  ed.model.schema.register("horizonDiagram", {
    inheritAllFrom: "$blockObject",
    allowAttributes: ["diagramId"],
  });

  // The <img> inside the figure is not converted: it would otherwise become an image.
  ed.conversion.for("upcast").add((dispatcher) => {
    dispatcher.on(
      "element:figure",
      (evt, data, conversionApi) => {
        const figure = data.viewItem;
        if (!figure.hasClass("horizon-diagram")) return;
        const diagramId = parseInt(figure.getAttribute("data-diagram-id"), 10);
        if (!(diagramId > 0) || !conversionApi.consumable.test(figure, { name: true })) return;
        const diagram = conversionApi.writer.createElement("horizonDiagram", { diagramId });
        if (!conversionApi.safeInsert(diagram, data.modelCursor)) return;
        conversionApi.consumable.consume(figure, { name: true });
        conversionApi.updateConversionResult(diagram, data);
      },
      { priority: "high" }
    );
  });

  ed.conversion.for("dataDowncast").elementToElement({
    model: "horizonDiagram",
    view: (modelElement, { writer }) => {
      const id = modelElement.getAttribute("diagramId");
      return writer.createContainerElement(
        "figure",
        { class: "horizon-diagram", "data-diagram-id": String(id) },
        [writer.createEmptyElement("img", { src: "horizon-diagram://" + id, alt: "Diagramme #" + id })]
      );
    },
  });

  ed.conversion.for("editingDowncast").elementToElement({
    model: "horizonDiagram",
    view: (modelElement, { writer }) => {
      const id = modelElement.getAttribute("diagramId");
      const figure = writer.createContainerElement(
        "figure",
        {
          class: "horizon-diagram",
          "data-diagram-id": String(id),
          title: "Double-cliquer pour modifier le diagramme",
        },
        // alt only shows when the image fails: the diagram was deleted.
        [writer.createEmptyElement("img", { src: diagramUrl(id), alt: "Diagramme #" + id + " introuvable" })]
      );
      return toWidget(figure, writer, { label: "Diagramme draw.io" });
    },
  });

  ed.commands.add("insertHorizonDiagram", new InsertDiagramCommand(ed));

  ed.ui.componentFactory.add("insertDiagram", (locale) => {
    const button = new ButtonView(locale);
    button.set({ label: "Insérer un diagramme draw.io", icon: DIAGRAM_ICON, tooltip: true });
    button.bind("isEnabled").to(ed.commands.get("insertHorizonDiagram"), "isEnabled");
    button.on("execute", () => {
      if (bridge) bridge.pick_diagram();
    });
    return button;
  });
}

function diagramHandlers(ed) {
  ed.ui.getEditableElement().addEventListener("dblclick", (e) => {
    const figure = e.target.closest && e.target.closest("figure.horizon-diagram");
    if (!figure) return;
    e.preventDefault();
    const id = parseInt(figure.getAttribute("data-diagram-id"), 10);
    if (id > 0 && bridge) bridge.open_diagram(id);
  });
}

// ── Attachments ─────────────────────────────────────────────────────────────
// Files, Outlook e-mails and URLs dropped on the note (Python's attachment_drop.py
// archives them). The stored HTML is a <figure class="horizon-attachment" data-…>
// whose data-* attributes are authoritative; its inner HTML is a plain fallback
// (link, subject, excerpt) for the search index and for API readers. In the editor it
// is a widget showing, OneNote-style, either an icon card or a preview — PDF pages
// served by horizon-attachment://<id>?page=<n>, or the e-mail itself.
//
// Untrusted text (file names, e-mail bodies) is only ever set through textContent.

const ATTACHMENT_ATTRS = {
  attachmentId: "data-attachment-id",
  kind: "data-kind",
  display: "data-display",
  name: "data-name",
  size: "data-size",
  mime: "data-mime",
  pages: "data-pages",
  href: "data-href",
  title: "data-title",
  subject: "data-subject",
  sender: "data-sender",
  date: "data-date",
  excerpt: "data-excerpt",
};
const NUMERIC_ATTACHMENT_ATTRS = new Set(["attachmentId", "size", "pages"]);
const PREVIEW_MAX_PAGES = 5;

const BADGE_COLORS = [
  [/^pdf$/, "#d93025"],
  [/^(docx?|dotx?|rtf|odt)$/, "#2b579a"],
  [/^(xlsx?|xlsm|csv|ods)$/, "#217346"],
  [/^(pptx?|potx?|odp)$/, "#d24726"],
  [/^(msg|eml)$/, "#0078d4"],
  [/^(zip|7z|rar|gz|tar)$/, "#8a6d3b"],
  [/^(vsdx?)$/, "#3955a3"],
  [/^(txt|md|log|json|xml|ya?ml)$/, "#5f6b7a"],
];

function attachmentExtension(name) {
  const match = /\.([A-Za-z0-9]{1,6})$/.exec(name || "");
  return match ? match[1].toLowerCase() : "";
}

function formatSize(bytes) {
  if (!(bytes > 0)) return "";
  const units = ["octets", "Ko", "Mo", "Go"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit++;
  }
  return (unit === 0 ? value : value.toFixed(value < 10 ? 1 : 0)).toString().replace(".", ",") + " " + units[unit];
}

// A link to the original: a file or folder (file://), an Outlook e-mail (outlook:), or
// a web page. The first two carry the original's name, which gives the badge.
function linkTarget(href) {
  if (/^file:/i.test(href)) {
    try {
      // file:///C:/x → C:\x ; file://serveur/partage → \\serveur\partage
      return decodeURI(href.replace(/^file:\/*/i, (m) => (m.length > 7 ? "" : "\\\\"))).replace(/\//g, "\\");
    } catch (e) {
      return href;
    }
  }
  if (/^outlook:/i.test(href)) return "Courriel Outlook — lien vers l'original";
  return href;
}

function isFileLink(attrs) {
  return attrs.kind === "link" && /^file:/i.test(attrs.href || "");
}

// Hover text of a card: the full path of a linked file or folder, then how to open it.
function attachmentTooltip(attrs) {
  if (isFileLink(attrs)) return linkTarget(attrs.href) + "\nDouble-cliquer pour ouvrir";
  return attrs.kind === "link" ? "Double-cliquer pour ouvrir le lien" : "Double-cliquer pour ouvrir";
}

function attachmentHost(href) {
  try {
    return new URL(href).hostname.replace(/^www\./, "");
  } catch (e) {
    return href;
  }
}

function canPreview(attrs) {
  return attrs.kind === "email" || (attrs.kind === "file" && attrs.pages > 0);
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function badge(label, color) {
  const node = el("span", "hz-att-badge", label);
  node.style.background = color;
  return node;
}

function attachmentBadge(attrs) {
  if (attrs.kind === "link") {
    if (attrs.mime === "inode/directory") return badge("DOS", "#c79a2b");
    if (/^outlook:/i.test(attrs.href)) return badge("MSG", "#0078d4");
    if (!attrs.name) return badge("WEB", "var(--hz-accent-color)");
  }
  if (attrs.kind === "email") return badge((attachmentExtension(attrs.name) || "msg").toUpperCase(), "#0078d4");
  const ext = attachmentExtension(attrs.name);
  const color = (BADGE_COLORS.find(([re]) => re.test(ext)) || [null, "#5f6b7a"])[1];
  return badge((ext || "?").toUpperCase().slice(0, 4), color);
}

// The editing view of one attachment, rebuilt whenever one of its attributes changes.
function renderAttachment(dom, attrs) {
  dom.textContent = "";
  const preview = attrs.display === "preview" && canPreview(attrs);
  const card = el("div", "hz-att-card");
  card.appendChild(attachmentBadge(attrs));
  const text = el("div", "hz-att-text");
  let main;
  let sub;
  if (attrs.kind === "link") {
    main = attrs.title || attachmentHost(attrs.href);
    // A file or folder link shows its name only; the path is in the tooltip.
    if (isFileLink(attrs)) sub = "";
    else if (attrs.sender || attrs.date) sub = [attrs.sender, attrs.date].filter(Boolean).join(" · ");
    else sub = linkTarget(attrs.href);
  } else if (attrs.kind === "email") {
    main = attrs.subject || attrs.name;
    sub = [attrs.sender, attrs.date].filter(Boolean).join(" · ");
  } else {
    main = attrs.name;
    const ext = attachmentExtension(attrs.name).toUpperCase();
    sub = [ext, formatSize(attrs.size), attrs.pages > 0 ? attrs.pages + " page" + (attrs.pages > 1 ? "s" : "") : ""]
      .filter(Boolean)
      .join(" · ");
  }
  text.appendChild(el("div", "hz-att-name", main));
  if (sub) text.appendChild(el("div", "hz-att-sub", sub));
  card.appendChild(text);
  dom.appendChild(card);

  if (!preview) return;
  if (attrs.kind === "email") {
    if (attrs.excerpt) dom.appendChild(el("div", "hz-att-excerpt", attrs.excerpt));
    return;
  }
  const pages = el("div", "hz-att-pages");
  const shown = Math.min(attrs.pages, PREVIEW_MAX_PAGES);
  for (let i = 0; i < shown; i++) {
    const img = el("img", "hz-att-page");
    img.src = "horizon-attachment://" + attrs.attachmentId + "?page=" + i;
    img.alt = "Page " + (i + 1);
    img.loading = "lazy";
    img.draggable = false;
    pages.appendChild(img);
  }
  dom.appendChild(pages);
  if (attrs.pages > shown) {
    dom.appendChild(el("div", "hz-att-more", "… " + (attrs.pages - shown) + " page(s) de plus — double-cliquer pour ouvrir le document"));
  }
}

function attachmentAttrsOf(modelElement) {
  const attrs = {};
  for (const key of Object.keys(ATTACHMENT_ATTRS)) {
    const value = modelElement.getAttribute(key);
    attrs[key] = NUMERIC_ATTACHMENT_ATTRS.has(key) ? Number(value) || 0 : value || "";
  }
  return attrs;
}

// Plain fallback content of the stored HTML (search index, API, a reader without
// Horizon). Escaped by building it as DOM, then serialised.
function attachmentFallbackHtml(attrs) {
  const box = document.createElement("div");
  if (attrs.kind === "link") {
    const a = el("a", null, attrs.title || attrs.href);
    a.setAttribute("href", attrs.href);
    box.appendChild(a);
  } else {
    const a = el("a", null, attrs.kind === "email" ? attrs.subject || attrs.name : attrs.name);
    a.setAttribute("href", "horizon-attachment://" + attrs.attachmentId);
    box.appendChild(a);
    if (attrs.kind === "email") {
      const meta = [attrs.sender, attrs.date].filter(Boolean).join(" · ");
      if (meta) box.appendChild(el("p", null, meta));
      if (attrs.excerpt) box.appendChild(el("p", null, attrs.excerpt));
    }
  }
  return box.innerHTML;
}

function selectedAttachment(ed) {
  const element = ed.model.document.selection.getSelectedElement();
  return element && element.is("element", "horizonAttachment") ? element : null;
}

class AttachmentDisplayCommand extends Command {
  constructor(ed, display) {
    super(ed);
    this.display = display;
  }

  refresh() {
    const element = selectedAttachment(this.editor);
    this.isEnabled = !!element && canPreview(attachmentAttrsOf(element));
    this.value = !!element && element.getAttribute("display") === this.display;
  }

  execute() {
    const element = selectedAttachment(this.editor);
    if (!element) return;
    this.editor.model.change((writer) => writer.setAttribute("display", this.display, element));
  }
}

// Open / save as: read-only actions, available in a locked note or an old version too.
class AttachmentActionCommand extends Command {
  constructor(ed, action) {
    super(ed);
    this.action = action;
    this.affectsData = false;
  }

  refresh() {
    const element = selectedAttachment(this.editor);
    const kind = element && element.getAttribute("kind");
    this.isEnabled = !!element && (this.action === "open" || kind !== "link");
  }

  execute() {
    const element = selectedAttachment(this.editor);
    if (element) openAttachment(attachmentAttrsOf(element), this.action);
  }
}

function openAttachment(attrs, action) {
  if (!bridge) return;
  if (attrs.kind === "link") {
    if (action === "open") bridge.open_link(attrs.href);
  } else if (attrs.attachmentId > 0) {
    if (action === "save") bridge.save_attachment(attrs.attachmentId);
    else bridge.open_attachment(attrs.attachmentId);
  }
}

function HorizonAttachment(ed) {
  ed.model.schema.register("horizonAttachment", {
    inheritAllFrom: "$blockObject",
    allowAttributes: Object.keys(ATTACHMENT_ATTRS),
  });

  ed.conversion.for("upcast").add((dispatcher) => {
    dispatcher.on(
      "element:figure",
      (evt, data, conversionApi) => {
        const figure = data.viewItem;
        if (!figure.hasClass("horizon-attachment")) return;
        if (!conversionApi.consumable.test(figure, { name: true })) return;
        const attrs = {};
        for (const [key, name] of Object.entries(ATTACHMENT_ATTRS)) {
          const value = figure.getAttribute(name);
          if (value === undefined || value === null || value === "") continue;
          attrs[key] = NUMERIC_ATTACHMENT_ATTRS.has(key) ? parseInt(value, 10) || 0 : value;
        }
        if (attrs.kind === "link" ? !attrs.href : !(attrs.attachmentId > 0)) return;
        const element = conversionApi.writer.createElement("horizonAttachment", attrs);
        if (!conversionApi.safeInsert(element, data.modelCursor)) return;
        // The children (fallback content) are deliberately not converted.
        conversionApi.consumable.consume(figure, { name: true });
        conversionApi.updateConversionResult(element, data);
      },
      { priority: "high" }
    );
  });

  ed.conversion.for("dataDowncast").elementToElement({
    model: "horizonAttachment",
    view: (modelElement, { writer }) => {
      const attrs = attachmentAttrsOf(modelElement);
      const viewAttrs = { class: "horizon-attachment" };
      for (const [key, name] of Object.entries(ATTACHMENT_ATTRS)) {
        const value = attrs[key];
        if (value !== "" && value !== 0) viewAttrs[name] = String(value);
      }
      return writer.createRawElement("figure", viewAttrs, (dom) => {
        dom.innerHTML = attachmentFallbackHtml(attrs);
      });
    },
  });

  ed.conversion.for("editingDowncast").elementToElement({
    // Listing the attributes makes CKEditor rebuild the widget when one changes
    // (display toggled, link title fetched).
    model: { name: "horizonAttachment", attributes: Object.keys(ATTACHMENT_ATTRS) },
    view: (modelElement, { writer }) => {
      const attrs = attachmentAttrsOf(modelElement);
      const figure = writer.createContainerElement(
        "figure",
        {
          class: "horizon-attachment hz-att-" + attrs.kind + (attrs.display === "preview" && canPreview(attrs) ? " hz-att-preview" : ""),
          "data-attachment-id": String(attrs.attachmentId || ""),
          title: attachmentTooltip(attrs),
        },
        [writer.createRawElement("div", { class: "hz-att-body" }, (dom) => renderAttachment(dom, attrs))]
      );
      return toWidget(figure, writer, { label: "Pièce jointe" });
    },
  });

  ed.commands.add("attachmentShowIcon", new AttachmentDisplayCommand(ed, "icon"));
  ed.commands.add("attachmentShowPreview", new AttachmentDisplayCommand(ed, "preview"));
  ed.commands.add("attachmentOpen", new AttachmentActionCommand(ed, "open"));
  ed.commands.add("attachmentSave", new AttachmentActionCommand(ed, "save"));

  const buttons = [
    ["attachmentOpen", "Ouvrir"],
    ["attachmentSave", "Enregistrer sous…"],
    ["attachmentShowIcon", "Icône"],
    ["attachmentShowPreview", "Aperçu"],
  ];
  for (const [name, label] of buttons) {
    ed.ui.componentFactory.add(name, (locale) => {
      const button = new ButtonView(locale);
      const command = ed.commands.get(name);
      button.set({ label, withText: true, tooltip: false });
      button.bind("isEnabled").to(command, "isEnabled");
      if (command instanceof AttachmentDisplayCommand) button.bind("isOn").to(command, "value");
      button.on("execute", () => ed.execute(name));
      return button;
    });
  }
}

class HorizonAttachmentToolbar extends Plugin {
  static get requires() {
    return [WidgetToolbarRepository];
  }

  afterInit() {
    this.editor.plugins.get(WidgetToolbarRepository).register("horizonAttachment", {
      ariaLabel: "Pièce jointe",
      items: ["attachmentOpen", "attachmentSave", "|", "attachmentShowIcon", "attachmentShowPreview"],
      getRelatedElement: (selection) => {
        const element = selection.getSelectedElement();
        return element && isWidget(element) && element.hasClass("horizon-attachment") ? element : null;
      },
    });
  }
}

function attachmentHandlers(ed) {
  ed.ui.getEditableElement().addEventListener("dblclick", (e) => {
    const figure = e.target.closest && e.target.closest("figure.horizon-attachment");
    if (!figure) return;
    e.preventDefault();
    const element = selectedAttachment(ed);
    if (element) openAttachment(attachmentAttrsOf(element), "open");
  });
}

// Drops are taken by Python before Chromium sees them (it reads the Windows clipboard
// formats Outlook uses); it only asks the page to move the caret where the item fell.
function modelPositionAt(x, y) {
  const range = document.caretRangeFromPoint(x, y);
  const editable = editor.ui.getEditableElement();
  if (!range || !editable.contains(range.startContainer)) return null;
  const viewPosition = editor.editing.view.domConverter.domPositionToView(range.startContainer, range.startOffset);
  if (!viewPosition) return null;
  try {
    return editor.editing.mapper.toModelPosition(viewPosition);
  } catch (e) {
    return null;
  }
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
      ImageToolbar, ImageCaption, ImageTextAlternative, ImageStyle, TableProperties,
      HorizontalLine, Autoformat, Widget, HorizonUploadAdapter, HorizonDiagram,
      HorizonAttachment, HorizonAttachmentToolbar, FontColor, Highlight,
    ],
    toolbar: {
      items: [
        "undo", "redo", "|", "heading", "|", "bold", "italic", "underline",
        "strikethrough", "code", "|", "fontColor", "highlight", "|", "bulletedList", "numberedList", "blockQuote", "|",
        "link", "insertTable", "codeBlock", "uploadImage", "insertDiagram", "horizontalLine",
      ],
      shouldNotGroupWhenFull: false,
    },
    // Text colour: a palette readable on both the light and the dark theme (no black or
    // white, which would vanish on one of them), plus the picker for any other colour.
    // "Couleur par défaut" removes it, so the text follows the theme again.
    fontColor: {
      colors: [
        { color: "#e03131", label: "Rouge" },
        { color: "#f76707", label: "Orange" },
        { color: "#f59f00", label: "Jaune" },
        { color: "#2f9e44", label: "Vert" },
        { color: "#0c8599", label: "Turquoise" },
        { color: "#1c7ed6", label: "Bleu" },
        { color: "#7048e8", label: "Violet" },
        { color: "#d6336c", label: "Rose" },
        { color: "#868e96", label: "Gris" },
      ],
      columns: 9,
      documentColors: 9,
      colorPicker: { format: "hex" },
    },
    // Highlighting: <mark class="marker-…">. The first four classes are styled by
    // CKEditor's own CSS, the others by the page CSS (webeditor.py), which also keeps the
    // highlighted text dark so it stays readable on the dark theme.
    highlight: {
      options: [
        { model: "yellowMarker", class: "marker-yellow", title: "Surligneur jaune", color: "var(--ck-content-highlight-marker-yellow)", type: "marker" },
        { model: "greenMarker", class: "marker-green", title: "Surligneur vert", color: "var(--ck-content-highlight-marker-green)", type: "marker" },
        { model: "pinkMarker", class: "marker-pink", title: "Surligneur rose", color: "var(--ck-content-highlight-marker-pink)", type: "marker" },
        { model: "blueMarker", class: "marker-blue", title: "Surligneur bleu", color: "var(--ck-content-highlight-marker-blue)", type: "marker" },
        { model: "orangeMarker", class: "marker-orange", title: "Surligneur orange", color: "var(--hz-highlight-marker-orange)", type: "marker" },
        { model: "purpleMarker", class: "marker-purple", title: "Surligneur violet", color: "var(--hz-highlight-marker-purple)", type: "marker" },
      ],
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
    // allowedProtocols replaces CKEditor's list rather than extending it: the usual web
    // protocols must be restated, or their links are rendered with href="#" in the editor.
    link: {
      allowedProtocols: ["https", "http", "ftp", "ftps", "mailto", "tel", "horizon", "horizon-attachment", "file", "outlook"],
      defaultProtocol: "https://",
    },
    // Block alignment: tables through the table properties balloon (alignment, plus
    // borders, background and size), images through three buttons on their toolbar.
    // Left is the default for both: CKEditor writes nothing for a default style, so the
    // page CSS (webeditor.py) left-aligns unclassed blocks — older notes included — and
    // centring gets a class of its own.
    table: {
      contentToolbar: ["tableColumn", "tableRow", "mergeTableCells", "|", "tableProperties"],
      tableProperties: { defaultProperties: { alignment: "left" } },
    },
    image: {
      styles: {
        options: [
          {
            name: "alignBlockLeft", title: "Image alignée à gauche", icon: IconObjectLeft,
            modelElements: ["imageBlock"], className: "image-style-block-align-left",
            isDefault: true,
          },
          {
            name: "blockCenter", title: "Image centrée", icon: IconObjectCenter,
            modelElements: ["imageBlock"], className: "image-style-block-center",
          },
          "alignBlockRight",
        ],
      },
      toolbar: [
        "imageStyle:alignBlockLeft", "imageStyle:blockCenter", "imageStyle:alignBlockRight", "|",
        "imageTextAlternative", "toggleImageCaption",
      ],
    },
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
          diagramHandlers(editor);
          attachmentHandlers(editor);
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
    insertDiagram(id) {
      editor.execute("insertHorizonDiagram", { diagramId: id });
      editor.editing.view.focus();
    },
    setCaretAt(x, y) {
      // Where a drop fell; outside the text (margin, toolbar) it goes to the end.
      const position = modelPositionAt(x, y);
      editor.model.change((writer) => {
        writer.setSelection(position || writer.createPositionAt(editor.model.document.getRoot(), "end"));
      });
    },
    insertBlocks(blocks) {
      // One undo step for the whole drop.
      editor.model.change((writer) => {
        for (const block of blocks) {
          let element;
          if (block.kind === "image") {
            element = writer.createElement("imageBlock", { src: "horizon-image://" + block.imageId });
          } else {
            const attrs = {};
            for (const key of Object.keys(ATTACHMENT_ATTRS)) {
              const value = block[key];
              if (value !== undefined && value !== null && value !== "" && value !== 0) attrs[key] = value;
            }
            element = writer.createElement("horizonAttachment", attrs);
          }
          // "after": the caret lands past the block, so the next one follows it instead
          // of replacing it.
          editor.model.insertObject(element, null, null, { setSelection: "after" });
        }
      });
      editor.editing.view.focus();
    },
    setLinkTitle(href, placeholder, title) {
      // A title fetched after the drop; a card the user already renamed is left alone.
      const root = editor.model.document.getRoot();
      editor.model.change((writer) => {
        for (const item of editor.model.createRangeIn(root).getItems()) {
          if (item.is("element", "horizonAttachment") && item.getAttribute("kind") === "link"
              && item.getAttribute("href") === href && item.getAttribute("title") === placeholder) {
            writer.setAttribute("title", title, item);
          }
        }
      });
    },
    refreshDiagram(id) {
      diagramRevisions.set(id, (diagramRevisions.get(id) || 0) + 1);
      const root = editor.model.document.getRoot();
      // Reconverting re-renders the widget under the new URL; the data is unchanged, so
      // it must not look like an edit.
      fromPython = true;
      try {
        for (const item of editor.model.createRangeIn(root).getItems()) {
          if (item.is("element", "horizonDiagram") && item.getAttribute("diagramId") === id) {
            editor.editing.reconvertItem(item);
          }
        }
      } finally {
        fromPython = false;
      }
    },
  };
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
