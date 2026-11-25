// Mind Elixir mind map editor for Horizon's Diagrams module.
//
// The Python half is src/horizon/widgets/mindelixir.py (MindElixirEditor). As with the note
// editors, Python keeps a mirror of the document (Mind Elixir's getDataString() JSON), fed by
// push_data after every operation; the generation counter drops pushes from a map that has
// since been replaced.
//
// Topics, arrow and summary labels are Markdown, rendered by marked and sanitised by
// DOMPurify (https://docs.mind-elixir.com/docs/advanced-guides/markdown-latex). Since what
// the editor shows is HTML, renderings (SVG for the notes, PNG for the list thumbnail) are
// captures of the map's DOM by SnapDOM, sent back through export_done.

import MindElixir from "mind-elixir";
import { fr } from "mind-elixir/i18n";
import "mind-elixir/style.css";
import { marked } from "marked";
import DOMPurify from "dompurify";
import { snapdom } from "@zumer/snapdom";

const PUSH_DELAY_MS = 300;

let bridge = null;
let mind = null;
let generation = 0;
let dark = false;
let pushTimer = null;

function theme() {
  return dark ? MindElixir.DARK_THEME : MindElixir.THEME;
}

// Links open in the system browser (through Python), never in the editor page.
DOMPurify.addHook("afterSanitizeAttributes", (node) => {
  if (node.tagName === "A") {
    node.setAttribute("target", "_blank");
    node.setAttribute("rel", "noopener noreferrer");
  }
});

function markdownToHtml(text) {
  if (!text) return "";
  const html = marked.parse(String(text), { gfm: true, breaks: true, async: false }).trim();
  return DOMPurify.sanitize(html);
}

function pushNow() {
  if (pushTimer !== null) {
    clearTimeout(pushTimer);
    pushTimer = null;
  }
  if (mind && bridge) bridge.push_data(mind.getDataString(), generation);
}

function schedulePush() {
  if (pushTimer !== null) clearTimeout(pushTimer);
  pushTimer = setTimeout(pushNow, PUSH_DELAY_MS);
}

async function load(data, gen, rootTopic) {
  if (pushTimer !== null) {
    clearTimeout(pushTimer);
    pushTimer = null;
  }
  generation = gen;
  if (mind) {
    mind.destroy();
    mind = null;
  }
  const el = document.getElementById("map");
  el.innerHTML = "";

  let parsed = null;
  if (data) {
    try {
      parsed = JSON.parse(data);
    } catch (e) {
      console.error("Horizon: données de mind map illisibles", e);
    }
  }
  const isNew = parsed === null;
  if (isNew) parsed = MindElixir.new(rootTopic || "Idée centrale");

  const instance = new MindElixir({
    el,
    direction: typeof parsed.direction === "number" ? parsed.direction : MindElixir.SIDE,
    toolBar: true,
    keypress: true,
    contextMenu: { locale: fr, focus: true, link: true },
    allowUndo: true,
    theme: theme(),
    markdown: markdownToHtml,
  });
  mind = instance;
  const error = await instance.init(parsed);
  if (mind !== instance) return; // replaced while starting
  if (error) console.error("Horizon: Mind Elixir n'a pas pu charger la carte", error);
  // The map follows Horizon's theme, whatever theme it was saved with.
  instance.changeTheme(theme());
  instance.bus.addListener("operation", schedulePush);
  if (isNew || error) pushNow(); // a new map exists as soon as it is created
  if (bridge) bridge.editor_ready(gen);
}

const CROP_MARGIN = 16;

// The map's content box inside mind.nodes, in its own (unscaled) pixels: mind.nodes carries
// the editor's wide padding (--map-padding), which a picture in a note does not need.
function contentBox() {
  const host = mind.nodes.getBoundingClientRect();
  const scale = mind.scaleVal || 1;
  let left = Infinity, top = Infinity, right = -Infinity, bottom = -Infinity;
  const parts = mind.nodes.querySelectorAll(
    ".me-tpc, svg.lines path, svg.topiclinks g, svg.summary g, .label-container > *");
  for (const el of parts) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) continue;
    left = Math.min(left, r.left); top = Math.min(top, r.top);
    right = Math.max(right, r.right); bottom = Math.max(bottom, r.bottom);
  }
  const width = mind.nodes.offsetWidth, height = mind.nodes.offsetHeight;
  if (left === Infinity) return { x: 0, y: 0, width, height };
  const x = Math.max(0, Math.floor((left - host.left) / scale) - CROP_MARGIN);
  const y = Math.max(0, Math.floor((top - host.top) / scale) - CROP_MARGIN);
  return {
    x, y,
    width: Math.min(width, Math.ceil((right - host.left) / scale) + CROP_MARGIN) - x,
    height: Math.min(height, Math.ceil((bottom - host.top) / scale) + CROP_MARGIN) - y,
  };
}

// Point the root <svg> of a capture at `box`.
function cropSvg(svg, box) {
  return svg.replace(/<svg\b[^>]*>/, (tag) =>
    tag
      .replace(/\swidth="[^"]*"/, ` width="${box.width}"`)
      .replace(/\sheight="[^"]*"/, ` height="${box.height}"`)
      .replace(/\sviewBox="[^"]*"/, ` viewBox="${box.x} ${box.y} ${box.width} ${box.height}"`));
}

function svgToPng(svg, width, height) {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => {
      // Twice the size, so the list thumbnail (shrunk by Python) stays sharp.
      const scale = Math.min(2, 4000 / Math.max(width, height, 1));
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(width * scale));
      canvas.height = Math.max(1, Math.round(height * scale));
      const ctx = canvas.getContext("2d");
      ctx.scale(scale, scale);
      ctx.drawImage(img, 0, 0, width, height);
      resolve(canvas.toDataURL("image/png"));
    };
    img.onerror = () => resolve("");
    img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
  });
}

async function exportImage(fmt, requestId) {
  let result = "";
  try {
    if (mind) {
      pushNow();
      // The selection outline would end up in the picture.
      mind.clearSelection();
      // The whole map (topics, branches, arrows, summaries), whatever is scrolled into view.
      const capture = await snapdom(mind.nodes, {
        backgroundColor: mind.theme.cssVar["--bgcolor"],
        embedFonts: true,
        dpr: 1,
        scale: 1,
      });
      const box = contentBox();
      const svg = cropSvg(await (await capture.toBlob()).text(), box);
      if (fmt === "svg") {
        result = "data:image/svg+xml;base64," + btoa(unescape(encodeURIComponent(svg)));
      } else {
        result = await svgToPng(svg, box.width, box.height);
      }
    }
  } catch (e) {
    console.error("Horizon: export de la mind map impossible", e);
    result = "";
  }
  if (bridge) bridge.export_done(requestId, result);
}

// Links in topics (Markdown or a node's hyperlink): opened by Python in the system browser.
document.addEventListener(
  "click",
  (e) => {
    const a = e.target && e.target.closest ? e.target.closest("a[href]") : null;
    if (!a) return;
    e.preventDefault();
    e.stopPropagation();
    if (bridge) bridge.open_link(a.href);
  },
  true,
);

window.HorizonMindmap = {
  load(data, gen, rootTopic) {
    load(data, gen, rootTopic);
  },
  exportImage,
  // Read by MindElixirEditor.flush(), so Python's mirror is exact on save. A JSON string:
  // runJavaScript() hands objects back to Python as "".
  readDoc() {
    if (pushTimer !== null) {
      clearTimeout(pushTimer);
      pushTimer = null;
    }
    return mind ? JSON.stringify({ generation, data: mind.getDataString() }) : "";
  },
};

new QWebChannel(qt.webChannelTransport, async (channel) => {
  bridge = channel.objects.bridge;
  bridge.get_initial_state((state) => {
    dark = !!state.dark;
    if (state.generation > 0) load(state.data, state.generation, state.root_topic);
  });
});
