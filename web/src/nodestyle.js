// Style bar of the mind map editor: font size and colour of the selected nodes.
//
// Mind Elixir stores a node's look in `nodeObj.style` (fontSize, color, …) and applies it
// with reshapeNode(), which records an undoable `reshapeNode` operation — so the change
// reaches Python's mirror like any other edit. Mind Elixir has no panel for it; this bar
// shows up above the map while nodes are selected.

const FONT_SIZES = ["12", "14", "16", "18", "20", "24", "28", "32", "40"];

// "" = the theme's colour (the style key is removed).
const COLORS = [
  ["", "Automatique"],
  ["#000000", "Noir"],
  ["#868e96", "Gris"],
  ["#e03131", "Rouge"],
  ["#f08c00", "Orange"],
  ["#2f9e44", "Vert"],
  ["#1971c2", "Bleu"],
  ["#9c36b5", "Violet"],
  ["#ffffff", "Blanc"],
];

const CSS = `
#hz-style-bar {
  position: absolute; top: 12px; left: 50%; transform: translateX(-50%); z-index: 20;
  display: none; align-items: center; gap: 8px; padding: 4px 10px;
  font: 12px 'Segoe UI', sans-serif; color: var(--hz-text);
  background: var(--hz-surface-alt-bg); border: 1px solid var(--hz-border); border-radius: 6px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2); user-select: none;
}
#hz-style-bar.visible { display: flex; }
#hz-style-bar select {
  font: inherit; color: var(--hz-text); background: var(--hz-input-bg);
  border: 1px solid var(--hz-border); border-radius: 4px; padding: 1px 4px;
}
#hz-style-bar .hz-sep { width: 1px; align-self: stretch; background: var(--hz-border); }
#hz-style-bar .hz-swatch {
  width: 18px; height: 18px; padding: 0; border-radius: 50%; cursor: pointer;
  border: 1px solid var(--hz-border); box-sizing: border-box;
}
#hz-style-bar .hz-swatch.active { outline: 2px solid var(--hz-accent-color); outline-offset: 1px; }
#hz-style-bar .hz-swatch.auto {
  background: linear-gradient(135deg, var(--hz-input-bg) 45%, #e03131 45%, #e03131 55%, var(--hz-input-bg) 55%);
}
#hz-style-bar input[type="color"] {
  width: 22px; height: 20px; padding: 0; border: none; background: none; cursor: pointer;
}
`;

export function installStyleBar(getMind) {
  const style = document.createElement("style");
  style.textContent = CSS;
  document.head.appendChild(style);

  const bar = document.createElement("div");
  bar.id = "hz-style-bar";
  // Clicks on the bar must not reach the map, which would clear the selection.
  for (const type of ["mousedown", "pointerdown", "click", "dblclick", "keydown", "wheel"]) {
    bar.addEventListener(type, (e) => e.stopPropagation());
  }

  const sizeLabel = document.createElement("span");
  sizeLabel.textContent = "Taille";
  const size = document.createElement("select");
  size.title = "Taille de la police";
  size.appendChild(new Option("Auto", ""));
  for (const px of FONT_SIZES) size.appendChild(new Option(px, px));
  size.addEventListener("change", () => apply({ fontSize: size.value ? size.value + "px" : "" }));

  const sep = document.createElement("span");
  sep.className = "hz-sep";
  const colorLabel = document.createElement("span");
  colorLabel.textContent = "Couleur";

  const swatches = COLORS.map(([value, name]) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "hz-swatch" + (value ? "" : " auto");
    if (value) b.style.background = value;
    b.title = name;
    b.dataset.color = value;
    b.addEventListener("click", () => apply({ color: value }));
    return b;
  });

  const custom = document.createElement("input");
  custom.type = "color";
  custom.title = "Autre couleur…";
  custom.addEventListener("change", () => apply({ color: custom.value }));

  bar.append(sizeLabel, size, sep, colorLabel, ...swatches, custom);
  document.body.appendChild(bar);

  function selected() {
    const mind = getMind();
    return mind ? (mind.currentNodes || []).filter((tpc) => tpc && tpc.nodeObj) : [];
  }

  // Show the first selected node's values (blank / Auto when they differ between nodes).
  function refresh() {
    const nodes = selected();
    bar.classList.toggle("visible", nodes.length > 0);
    if (!nodes.length) return;
    const styles = nodes.map((tpc) => tpc.nodeObj.style || {});
    const same = (key) => styles.every((s) => (s[key] || "") === (styles[0][key] || ""));
    size.value = same("fontSize") ? String(parseInt(styles[0].fontSize, 10) || "") : "";
    if (!FONT_SIZES.includes(size.value)) size.value = "";
    const color = same("color") ? (styles[0].color || "").toLowerCase() : null;
    for (const b of swatches) b.classList.toggle("active", color !== null && b.dataset.color === color);
    if (color && /^#[0-9a-f]{6}$/.test(color)) custom.value = color;
  }

  async function apply(patch) {
    const mind = getMind();
    for (const tpc of selected()) {
      // reshapeNode() merges the previous style under the one it is given, so a key cannot
      // be removed: "" overrides it (and keeps undo exact); refresh() reads "" as unset.
      // It neither clears the inline style of an emptied key, hence the explicit reset.
      for (const [key, value] of Object.entries(patch)) if (!value) tpc.style[key] = "";
      await mind.reshapeNode(tpc, { style: { ...(tpc.nodeObj.style || {}), ...patch } });
    }
    refresh();
  }

  return {
    // Called once per Mind Elixir instance (one per loaded map).
    attach(mind) {
      mind.bus.addListener("selectNodes", refresh);
      mind.bus.addListener("unselectNodes", refresh);
      refresh();
    },
    refresh,
  };
}
