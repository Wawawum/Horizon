// Style bar of the mind map editor: font size, text colour, background, shape, border colour
// and width of the selected nodes.
//
// Mind Elixir stores a node's look in `nodeObj.style`, whose keys it copies onto the topic
// element as inline CSS, and applies it with reshapeNode(), which records an undoable
// `reshapeNode` operation — so the change reaches Python's mirror like any other edit. Mind
// Elixir has no panel for it; this bar shows up above the map while nodes are selected.

const FONT_SIZES = ["12", "14", "16", "18", "20", "24", "28", "32", "40"];
// Shapes are border radii (clip-path shapes such as a diamond would clip the border away).
// The ellipse also gets more padding, so that its curve clears the text.
const SHAPES = [
  ["rect", "Rectangle", { borderRadius: "0px", padding: "" }],
  ["rounded", "Arrondi", { borderRadius: "8px", padding: "" }],
  ["pill", "Pilule", { borderRadius: "999px", padding: "" }],
  ["ellipse", "Ellipse", { borderRadius: "50%", padding: "14px 30px" }],
];

const BORDER_WIDTHS = [["0", "Aucune"], ["1", "1 px"], ["2", "2 px"], ["3", "3 px"], ["4", "4 px"], ["6", "6 px"]];

// Strong colours, then light ones (backgrounds).
const PALETTE = [
  ["#000000", "Noir"], ["#868e96", "Gris"], ["#e03131", "Rouge"], ["#f08c00", "Orange"],
  ["#f59f00", "Jaune"], ["#2f9e44", "Vert"], ["#1971c2", "Bleu"], ["#9c36b5", "Violet"],
  ["#ffffff", "Blanc"], ["#f1f3f5", "Gris clair"], ["#ffe3e3", "Rouge clair"], ["#ffe8cc", "Orange clair"],
  ["#fff3bf", "Jaune clair"], ["#d3f9d8", "Vert clair"], ["#d0ebff", "Bleu clair"], ["#e5dbff", "Violet clair"],
];

const CSS = `
#hz-style-bar {
  position: absolute; top: 12px; left: 50%; transform: translateX(-50%); z-index: 20;
  display: none; align-items: center; gap: 6px; padding: 4px 10px; white-space: nowrap;
  font: 12px 'Segoe UI', sans-serif; color: var(--hz-text);
  background: var(--hz-surface-alt-bg); border: 1px solid var(--hz-border); border-radius: 6px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2); user-select: none;
}
#hz-style-bar.visible { display: flex; }
#hz-style-bar select {
  font: inherit; color: var(--hz-text); background: var(--hz-input-bg);
  border: 1px solid var(--hz-border); border-radius: 4px; padding: 1px 4px;
}
#hz-style-bar .hz-sep { width: 1px; align-self: stretch; margin: 0 4px; background: var(--hz-border); }
#hz-style-bar .hz-color-btn {
  display: inline-flex; align-items: center; gap: 3px; padding: 2px 4px; cursor: pointer;
  font: inherit; color: var(--hz-text); background: var(--hz-input-bg);
  border: 1px solid var(--hz-border); border-radius: 4px;
}
#hz-style-bar .hz-color-btn::after { content: "▾"; font-size: 9px; opacity: 0.7; }
.hz-swatch {
  width: 18px; height: 18px; padding: 0; border-radius: 50%; cursor: pointer;
  border: 1px solid var(--hz-border); box-sizing: border-box; display: inline-block;
}
.hz-swatch.auto {
  background: linear-gradient(135deg, var(--hz-input-bg) 45%, #e03131 45%, #e03131 55%, var(--hz-input-bg) 55%);
}
.hz-swatch.mixed { background: repeating-linear-gradient(45deg, #adb5bd 0 3px, transparent 3px 6px); }
#hz-color-pop {
  position: absolute; z-index: 30; display: none; padding: 8px; width: 192px;
  background: var(--hz-surface-alt-bg); border: 1px solid var(--hz-border); border-radius: 6px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25); font: 12px 'Segoe UI', sans-serif; color: var(--hz-text);
}
#hz-color-pop.visible { display: block; }
#hz-color-pop .hz-grid { display: grid; grid-template-columns: repeat(8, 18px); gap: 6px; margin: 6px 0; }
#hz-color-pop .hz-swatch.active { outline: 2px solid var(--hz-accent-color); outline-offset: 1px; }
#hz-color-pop .hz-row { display: flex; align-items: center; gap: 6px; }
#hz-color-pop button.hz-auto-btn {
  font: inherit; color: var(--hz-text); background: none; border: none; cursor: pointer; padding: 0;
  display: inline-flex; align-items: center; gap: 6px;
}
#hz-color-pop input[type="color"] {
  width: 26px; height: 20px; padding: 0; border: none; background: none; cursor: pointer;
}
`;

function swatch(value) {
  const s = document.createElement("span");
  s.className = "hz-swatch" + (value ? "" : " auto");
  if (value) s.style.background = value;
  return s;
}

export function installStyleBar(getMind) {
  const style = document.createElement("style");
  style.textContent = CSS;
  document.head.appendChild(style);

  // Clicks on the bar and its popover must not reach the map, which would clear the selection.
  function shield(el) {
    for (const type of ["mousedown", "pointerdown", "click", "dblclick", "keydown", "wheel"]) {
      el.addEventListener(type, (e) => e.stopPropagation());
    }
  }

  const bar = document.createElement("div");
  bar.id = "hz-style-bar";
  shield(bar);

  // ── Colour popover, shared by the three colour buttons ─────────────────
  const pop = document.createElement("div");
  pop.id = "hz-color-pop";
  shield(pop);
  const autoBtn = document.createElement("button");
  autoBtn.type = "button";
  autoBtn.className = "hz-auto-btn";
  autoBtn.append(swatch(""), "Automatique");
  const grid = document.createElement("div");
  grid.className = "hz-grid";
  const gridSwatches = PALETTE.map(([value, name]) => {
    const s = swatch(value);
    s.title = name;
    s.dataset.color = value;
    s.addEventListener("click", () => pick(value));
    grid.appendChild(s);
    return s;
  });
  const customRow = document.createElement("label");
  customRow.className = "hz-row";
  const custom = document.createElement("input");
  custom.type = "color";
  custom.addEventListener("change", () => pick(custom.value));
  customRow.append(custom, "Autre couleur…");
  autoBtn.addEventListener("click", () => pick(""));
  pop.append(autoBtn, grid, customRow);

  let popKey = null; // style key the open popover edits

  function openPop(key, anchor) {
    if (popKey === key && pop.classList.contains("visible")) return closePop();
    popKey = key;
    const current = commonValue(key);
    for (const s of gridSwatches) s.classList.toggle("active", current !== null && s.dataset.color === current);
    if (current && /^#[0-9a-f]{6}$/.test(current)) custom.value = current;
    const r = anchor.getBoundingClientRect();
    pop.style.left = Math.max(4, Math.min(r.left, window.innerWidth - 212)) + "px";
    pop.style.top = r.bottom + 6 + "px";
    pop.classList.add("visible");
  }

  function closePop() {
    pop.classList.remove("visible");
    popKey = null;
  }

  function pick(value) {
    const key = popKey;
    closePop();
    if (key) apply({ [key]: value });
  }

  document.addEventListener("mousedown", closePop);

  // ── Bar ────────────────────────────────────────────────────────────────
  function label(text) {
    const l = document.createElement("span");
    l.textContent = text;
    return l;
  }

  function sep() {
    const s = document.createElement("span");
    s.className = "hz-sep";
    return s;
  }

  function colorButton(key, title) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "hz-color-btn";
    b.title = title;
    const s = swatch("");
    b.appendChild(s);
    b.addEventListener("click", () => openPop(key, b));
    return { key, button: b, swatch: s };
  }

  const size = document.createElement("select");
  size.title = "Taille de la police";
  size.appendChild(new Option("Auto", ""));
  for (const px of FONT_SIZES) size.appendChild(new Option(px, px));
  size.addEventListener("change", () => apply({ fontSize: size.value ? size.value + "px" : "" }));

  const shape = document.createElement("select");
  shape.title = "Forme du nœud";
  shape.appendChild(new Option("Auto", ""));
  for (const [id, name] of SHAPES) shape.appendChild(new Option(name, id));
  shape.addEventListener("change", () => {
    const found = SHAPES.find(([id]) => id === shape.value);
    apply(found ? found[2] : { borderRadius: "", padding: "" });
  });

  const borderWidth = document.createElement("select");
  borderWidth.title = "Épaisseur de la bordure";
  borderWidth.appendChild(new Option("Auto", ""));
  for (const [px, name] of BORDER_WIDTHS) borderWidth.appendChild(new Option(name, px));
  borderWidth.addEventListener("change", () =>
    apply({ borderWidth: borderWidth.value ? borderWidth.value + "px" : "" }));

  const colorButtons = [
    colorButton("color", "Couleur du texte"),
    colorButton("background", "Couleur de fond"),
    colorButton("borderColor", "Couleur de la bordure"),
  ];
  const [textColor, background, borderColor] = colorButtons;

  bar.append(
    label("Texte"), size, textColor.button, sep(),
    label("Fond"), background.button, sep(),
    label("Forme"), shape, sep(),
    label("Bordure"), borderWidth, borderColor.button,
  );
  document.body.append(bar, pop);

  // ── State ──────────────────────────────────────────────────────────────
  function selected() {
    const mind = getMind();
    return mind ? (mind.currentNodes || []).filter((tpc) => tpc && tpc.nodeObj) : [];
  }

  // The value of `key` shared by every selected node ("" = unset), or null when they differ.
  function commonValue(key) {
    const values = selected().map((tpc) => ((tpc.nodeObj.style || {})[key] || "").toLowerCase());
    if (!values.length) return "";
    return values.every((v) => v === values[0]) ? values[0] : null;
  }

  function showSelect(select, key, choices) {
    const v = commonValue(key);
    const n = v ? String(parseInt(v, 10)) : "";
    select.value = v !== null && choices.includes(n) ? n : "";
  }

  function refresh() {
    const nodes = selected();
    bar.classList.toggle("visible", nodes.length > 0);
    if (!nodes.length) {
      closePop();
      return;
    }
    showSelect(size, "fontSize", FONT_SIZES);
    showSelect(borderWidth, "borderWidth", BORDER_WIDTHS.map(([px]) => px));
    const radius = commonValue("borderRadius");
    const current = radius ? SHAPES.find(([, , st]) => st.borderRadius === radius) : null;
    shape.value = current ? current[0] : "";
    for (const { key, swatch: s } of colorButtons) {
      const v = commonValue(key);
      s.className = "hz-swatch" + (v === null ? " mixed" : v ? "" : " auto");
      s.style.background = v ? v : "";
    }
  }

  async function apply(patch) {
    const mind = getMind();
    for (const tpc of selected()) {
      const next = { ...(tpc.nodeObj.style || {}), ...patch };
      if ("borderWidth" in patch || "borderColor" in patch) {
        // Sub-topics have no border of their own: a colour or a width needs a style, and a
        // colour alone a visible width.
        const custom = next.borderWidth || next.borderColor;
        next.borderStyle = custom ? "solid" : "";
        if (next.borderColor && !next.borderWidth && getComputedStyle(tpc).borderTopStyle === "none") {
          next.borderWidth = "2px";
        }
      }
      // reshapeNode() merges the previous style under the one it is given, so a key cannot
      // be removed: "" overrides it (and keeps undo exact); refresh() reads "" as unset.
      // It neither clears the inline style of an emptied key, hence the explicit reset.
      for (const [key, value] of Object.entries(next)) if (!value) tpc.style[key] = "";
      await mind.reshapeNode(tpc, { style: next });
    }
    refresh();
  }

  return {
    // Called once per Mind Elixir instance (one per loaded map).
    attach(mind) {
      // linkDiv() — every redraw — paints first-level topics' borders in their branch
      // colour, over the node's own style: put a chosen border colour back afterwards.
      const linkDiv = mind.linkDiv;
      mind.linkDiv = function (...args) {
        const result = linkDiv.apply(this, args);
        for (const tpc of this.nodes.querySelectorAll(".me-tpc")) {
          const color = tpc.nodeObj && tpc.nodeObj.style && tpc.nodeObj.style.borderColor;
          if (color) tpc.style.borderColor = color;
        }
        return result;
      };
      mind.linkDiv();
      mind.bus.addListener("selectNodes", refresh);
      mind.bus.addListener("unselectNodes", refresh);
      refresh();
    },
    refresh,
  };
}
