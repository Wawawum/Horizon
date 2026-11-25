// Mind Elixir mind map editor for Horizon's Diagrams module.
//
// The Python half is src/horizon/widgets/mindelixir.py (MindElixirEditor). As with the note
// editors, Python keeps a mirror of the document (Mind Elixir's getDataString() JSON), fed by
// push_data after every operation; the generation counter drops pushes from a map that has
// since been replaced. Renderings (SVG for the notes, PNG for the list thumbnail) are made
// from the data by @erseco/mind-elixir-export-svg — native vector SVG, no foreignObject — and
// sent back through export_done.

import MindElixir from "mind-elixir";
import { fr } from "mind-elixir/i18n";
import "mind-elixir/style.css";
import { renderSvg } from "@erseco/mind-elixir-export-svg";

const PUSH_DELAY_MS = 300;

let bridge = null;
let mind = null;
let generation = 0;
let dark = false;
let pushTimer = null;

function theme() {
  return dark ? MindElixir.DARK_THEME : MindElixir.THEME;
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
      const out = await renderSvg(mind.getData(), { theme: theme(), padding: 16 });
      if (fmt === "svg") {
        result = "data:image/svg+xml;base64," + btoa(unescape(encodeURIComponent(out.svg)));
      } else {
        result = await svgToPng(out.svg, out.width, out.height);
      }
    }
  } catch (e) {
    console.error("Horizon: export de la mind map impossible", e);
    result = "";
  }
  if (bridge) bridge.export_done(requestId, result);
}

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
