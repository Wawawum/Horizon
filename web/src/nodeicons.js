// Icon picker of the mind map style bar.
//
// Mind Elixir shows `nodeObj.icons` — a list of strings, escaped — after a topic's text, so
// icons are emoji. A click on one adds it to the selected nodes, or removes it when they all
// have it; any other emoji can be typed (Windows + .) or pasted. Changes go through
// reshapeNode(), an undoable operation pushed to Python like any edit.

const GROUPS = [
  ["Priorité", ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "🔴", "🟠", "🟡", "🟢", "🔵"]],
  ["Statut", ["✅", "☑️", "❌", "⚠️", "❗", "❓", "⏳", "🚧", "🔒", "⛔"]],
  ["Symboles", ["⭐", "❤️", "💡", "🎯", "🚀", "🔥", "📌", "🏁", "🔍", "💬"]],
  ["Objets", ["📅", "📧", "📞", "📁", "📝", "📎", "💰", "👤", "👥", "🌐"]],
  ["Flèches", ["⬆️", "⬇️", "➡️", "⬅️", "🔄", "↗️", "↘️", "➕", "➖", "🔗"]],
];

const CSS = `
#hz-style-bar .hz-icons-btn {
  padding: 2px 8px; cursor: pointer; font: inherit; color: var(--hz-text);
  background: var(--hz-input-bg); border: 1px solid var(--hz-border); border-radius: 4px;
}
#hz-style-bar .hz-icons-btn::after { content: " ▾"; font-size: 9px; opacity: 0.7; }
#hz-icon-pop {
  position: absolute; z-index: 30; display: none; padding: 8px 10px;
  background: var(--hz-surface-alt-bg); border: 1px solid var(--hz-border); border-radius: 6px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25); font: 12px 'Segoe UI', sans-serif; color: var(--hz-text);
}
#hz-icon-pop.visible { display: block; }
#hz-icon-pop .hz-icon-grid {
  display: grid; grid-template-columns: auto repeat(10, 26px); gap: 4px 4px; align-items: center;
}
#hz-icon-pop .hz-icon-grid > span.hz-group { padding-right: 6px; opacity: 0.8; }
#hz-icon-pop .hz-icon {
  width: 26px; height: 26px; padding: 0; cursor: pointer; border-radius: 4px;
  border: 1px solid transparent; background: none;
  font: 16px/24px 'Segoe UI Emoji', 'Segoe UI Symbol', sans-serif; text-align: center;
}
#hz-icon-pop .hz-icon:hover { background: var(--hz-input-bg); border-color: var(--hz-border); }
#hz-icon-pop .hz-icon.active { background: var(--hz-input-bg); border-color: var(--hz-accent-color); }
#hz-icon-pop .hz-icon-row { display: flex; align-items: center; gap: 6px; margin-top: 8px; }
#hz-icon-pop input {
  width: 90px; font: inherit; color: var(--hz-text); background: var(--hz-input-bg);
  border: 1px solid var(--hz-border); border-radius: 4px; padding: 2px 4px;
}
#hz-icon-pop button.hz-text-btn {
  font: inherit; color: var(--hz-text); background: var(--hz-input-bg); cursor: pointer;
  border: 1px solid var(--hz-border); border-radius: 4px; padding: 2px 8px;
}
#hz-icon-pop button.hz-clear { margin-left: auto; }
`;

/**
 * @param getMind     () => the current MindElixir instance
 * @param getSelected () => the selected topic elements
 * @param shield      (el) => stops the map from seeing the element's clicks and keys
 * @param beforeOpen  () => closes the bar's other popovers
 */
export function installIconPicker({ getMind, getSelected, shield, beforeOpen }) {
  const style = document.createElement("style");
  style.textContent = CSS;
  document.head.appendChild(style);

  const button = document.createElement("button");
  button.type = "button";
  button.className = "hz-icons-btn";
  button.title = "Ajouter ou retirer des icônes";
  button.textContent = "Icônes";

  const pop = document.createElement("div");
  pop.id = "hz-icon-pop";
  shield(pop);

  const grid = document.createElement("div");
  grid.className = "hz-icon-grid";
  const cells = [];
  for (const [name, icons] of GROUPS) {
    const label = document.createElement("span");
    label.className = "hz-group";
    label.textContent = name;
    grid.appendChild(label);
    for (const icon of icons) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "hz-icon";
      b.textContent = icon;
      b.addEventListener("click", () => toggle(icon));
      cells.push({ icon, cell: b });
      grid.appendChild(b);
    }
  }

  const row = document.createElement("div");
  row.className = "hz-icon-row";
  const other = document.createElement("input");
  other.placeholder = "Autre emoji…";
  other.title = "Saisir ou coller un emoji (Windows + .), puis Entrée";
  const add = document.createElement("button");
  add.type = "button";
  add.className = "hz-text-btn";
  add.textContent = "Ajouter";
  const clear = document.createElement("button");
  clear.type = "button";
  clear.className = "hz-text-btn hz-clear";
  clear.textContent = "Retirer toutes les icônes";
  row.append(other, add, clear);
  pop.append(grid, row);

  function addOther() {
    const icon = other.value.trim();
    if (!icon) return;
    other.value = "";
    update((icons) => (icons.includes(icon) ? icons : [...icons, icon]));
  }
  add.addEventListener("click", addOther);
  other.addEventListener("keydown", (e) => {
    if (e.key === "Enter") addOther();
  });
  clear.addEventListener("click", () => update(() => []));

  // Remove `icon` when every selected node has it, else add it where it is missing.
  function toggle(icon) {
    const everywhere = getSelected().every((tpc) => (tpc.nodeObj.icons || []).includes(icon));
    update((icons) =>
      everywhere ? icons.filter((i) => i !== icon) : icons.includes(icon) ? icons : [...icons, icon]);
  }

  async function update(change) {
    const mind = getMind();
    for (const tpc of getSelected()) {
      const before = tpc.nodeObj.icons || [];
      const after = change(before);
      if (after.length === before.length && after.every((v, i) => v === before[i])) continue;
      await mind.reshapeNode(tpc, { icons: after });
    }
    refresh();
  }

  function refresh() {
    const nodes = getSelected();
    for (const { icon, cell } of cells) {
      cell.classList.toggle(
        "active", nodes.length > 0 && nodes.every((tpc) => (tpc.nodeObj.icons || []).includes(icon)));
    }
  }

  function open() {
    if (pop.classList.contains("visible")) return close();
    beforeOpen();
    refresh();
    const r = button.getBoundingClientRect();
    pop.style.left = Math.max(4, Math.min(r.left, window.innerWidth - 360)) + "px";
    pop.style.top = r.bottom + 6 + "px";
    pop.classList.add("visible");
  }

  function close() {
    pop.classList.remove("visible");
  }

  button.addEventListener("click", open);
  return { button, pop, close, refresh };
}
