// Node or leaf: how a mind map topic is drawn.
//
// Mind Elixir draws the root's children as boxed "nodes" (background, border, branch line
// reaching their middle) and everything deeper as "leaves" (text underlined by the branch
// line), fixed by its CSS (.me-main > .me-wrapper > .me-parent > .me-tpc) and its two line
// generators. Here the number of levels drawn as nodes is a setting of the map
// (the root's metadata.hzLevels, default 1 = Mind Elixir's own look), and a topic can force
// its kind (metadata.hzKind: "node" | "leaf", "" = from the levels). Both live in `metadata`,
// the node field meant for application data, and one undo/redo restores (diffRefresh only
// compares a fixed list of fields); they are changed with reshapeNode(), pushed to Python
// like any edit.
//
// Rendering: before each layout, classes on .me-parent (hz-node on deeper topics drawn as
// nodes, hz-leaf on first-level topics drawn as leaves) restyle the topics, and the line
// generators are wrapped to start or end the lines where the kind wants them. The generators
// only receive geometry, so the topics they draw for are looked up in the order Mind Elixir
// calls them (document order), checked against that geometry; anything unexpected falls back
// to Mind Elixir's own line.

export const DEFAULT_LEVELS = 1;

/**
 * Keep the map from seeing clicks and keys on a control panel of the page, and hand the
 * keyboard back to the map once a choice is made there — otherwise its shortcuts (Ctrl+Z,
 * Tab, Delete…) would land in the last list used. Text fields keep the focus.
 */
export function shieldControls(el, getMind) {
  for (const type of ["mousedown", "pointerdown", "click", "dblclick", "keydown", "wheel"]) {
    el.addEventListener(type, (e) => e.stopPropagation());
  }
  const refocus = (e) => {
    if (e.target instanceof HTMLInputElement && e.target.type === "text") return;
    if (e.type === "click" && e.target instanceof HTMLSelectElement) return; // still choosing
    const mind = getMind();
    if (mind) setTimeout(() => mind.container.focus({ preventScroll: true }), 0);
  };
  el.addEventListener("change", refocus);
  el.addEventListener("click", refocus);
}
export const MAX_LEVELS = 8;

const CSS = `
.map-container .me-nodes:not(.down) .me-parent.hz-node > .me-tpc {
  border-radius: var(--main-radius); background-color: var(--main-bgcolor);
  border: 2px solid var(--main-color); color: var(--main-color); padding: 8px 25px;
}
.map-container .me-nodes:not(.down) .me-parent.hz-node > .me-epd { top: calc(50% - 9px); }
.map-container .me-nodes:not(.down) .me-main > .me-wrapper > .me-parent.hz-leaf > .me-tpc {
  border: none; border-radius: 3px; background-color: transparent;
  color: var(--color); padding: var(--topic-padding);
}
.map-container .me-nodes:not(.down) .me-main > .me-wrapper > .me-parent.hz-leaf > .me-epd {
  top: calc(100% - 9px);
}
#hz-levels {
  position: absolute; left: 20px; bottom: 20px; z-index: 20; display: flex; align-items: center;
  gap: 6px; padding: 4px 8px; font: 12px 'Segoe UI', sans-serif; color: var(--hz-text);
  background: var(--hz-surface-alt-bg); border: 1px solid var(--hz-border); border-radius: 6px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2); user-select: none;
}
#hz-levels select {
  font: inherit; color: var(--hz-text); background: var(--hz-input-bg);
  border: 1px solid var(--hz-border); border-radius: 4px; padding: 1px 4px;
}
`;

function levelsOf(mind) {
  const v = mind.nodeData && mind.nodeData.metadata && mind.nodeData.metadata.hzLevels;
  return Number.isInteger(v) && v >= 0 ? Math.min(v, MAX_LEVELS) : DEFAULT_LEVELS;
}

// 1 for the root's children, 2 for theirs…
function depthOf(parentEl) {
  let depth = 1;
  for (let el = parentEl.parentElement; el; el = el.parentElement) {
    if (el.classList.contains("me-children")) depth++;
    if (el.classList.contains("me-main")) break;
  }
  return depth;
}

// A topic's forced kind ("" = from the levels).
export function kindSetting(nodeObj) {
  return (nodeObj && nodeObj.metadata && nodeObj.metadata.hzKind) || "";
}

// Set a topic's forced kind ("" = from the levels), through reshapeNode().
export async function setKind(mind, tpc, value) {
  if (tpc.nodeObj.root || kindSetting(tpc.nodeObj) === value) return;
  await mind.reshapeNode(tpc, { metadata: { ...(tpc.nodeObj.metadata || {}), hzKind: value } });
}

export function kindOf(mind, parentEl) {
  const tpc = parentEl.querySelector(":scope > .me-tpc");
  const forced = tpc && kindSetting(tpc.nodeObj);
  if (forced === "node" || forced === "leaf") return forced;
  return depthOf(parentEl) <= levelsOf(mind) ? "node" : "leaf";
}

// The .me-parent of the topic whose children `parentEl` (a child's .me-parent) hangs under.
function parentOf(childParentEl) {
  const wrapper = childParentEl.parentElement; // .me-wrapper
  const children = wrapper && wrapper.parentElement; // .me-children
  const parentWrapper = children && children.parentElement;
  return parentWrapper ? parentWrapper.firstElementChild : null;
}

export function installNodeKinds(getMind) {
  const style = document.createElement("style");
  style.textContent = CSS;
  document.head.appendChild(style);

  // ── Map setting: levels drawn as nodes ─────────────────────────────────
  const panel = document.createElement("div");
  panel.id = "hz-levels";
  shieldControls(panel, getMind);
  const label = document.createElement("span");
  label.textContent = "Niveaux en nœuds";
  const levels = document.createElement("select");
  levels.title = "Nombre de niveaux sous la racine affichés comme des nœuds ; au-delà, des feuilles";
  for (let n = 0; n <= MAX_LEVELS; n++) levels.appendChild(new Option(String(n), String(n)));
  levels.addEventListener("change", async () => {
    const mind = getMind();
    const root = mind && mind.map.querySelector(".me-root > .me-tpc");
    if (root) {
      const metadata = { ...(root.nodeObj.metadata || {}), hzLevels: parseInt(levels.value, 10) };
      await mind.reshapeNode(root, { metadata });
    }
  });
  panel.append(label, levels);
  document.body.appendChild(panel);

  function refreshPanel() {
    const mind = getMind();
    panel.style.display = mind ? "" : "none";
    if (mind) levels.value = String(levelsOf(mind));
  }

  // ── Layout hooks, called by the linkDiv() wrapper ──────────────────────
  let mainQueue = null; // [tpc] in the order the main lines are drawn
  let subQueue = null; // [.me-parent] in the order the sub lines are drawn
  let subCursor = 0;

  // Before Mind Elixir's layout: classes, and the order of the lines it will draw.
  function beforeLayout(mind, onlyWrapper) {
    for (const parentEl of mind.nodes.querySelectorAll(".me-main .me-parent")) {
      const depth = depthOf(parentEl);
      const kind = kindOf(mind, parentEl);
      parentEl.classList.toggle("hz-node", depth >= 2 && kind === "node");
      parentEl.classList.toggle("hz-leaf", depth === 1 && kind === "leaf");
    }
    mainQueue = [...mind.map.querySelectorAll(".me-main > .me-wrapper")].map((w) =>
      w.firstElementChild ? w.firstElementChild.querySelector(":scope > .me-tpc") : null);
    const scope = onlyWrapper ? [onlyWrapper] : mind.map.querySelectorAll(".me-main > .me-wrapper");
    subQueue = [];
    for (const wrapper of scope) subQueue.push(...wrapper.querySelectorAll(".me-children .me-parent"));
    subCursor = 0;
  }

  // After it: deeper topics drawn as nodes get their branch colour as border, as Mind
  // Elixir gives first-level topics (which it has just painted).
  function afterLayout(mind) {
    mainQueue = subQueue = null;
    for (const parentEl of mind.nodes.querySelectorAll(".me-parent.hz-node")) {
      const tpc = parentEl.querySelector(":scope > .me-tpc");
      if (tpc) tpc.style.borderColor = branchColorOf(parentEl) || "";
    }
  }

  function branchColorOf(parentEl) {
    for (let el = parentEl; el; el = parentOf(el)) {
      const tpc = el.querySelector(":scope > .me-tpc");
      const own = tpc && tpc.nodeObj && tpc.nodeObj.branchColor;
      if (own) return own;
      if (!el.parentElement || !el.parentElement.parentElement) break;
      if (el.parentElement.parentElement.classList.contains("me-main")) {
        return tpc ? tpc.style.borderColor : "";
      }
    }
    return "";
  }

  // ── Line generators ────────────────────────────────────────────────────
  function wrapGenerators(mind) {
    const main = mind.generateMainBranch;
    const sub = mind.generateSubBranch;

    mind.generateMainBranch = function (p) {
      const tpc = mainQueue && mainQueue.shift();
      const leaf = p.direction !== "down" && tpc && tpc.offsetWidth === p.cW && tpc.offsetHeight === p.cH &&
        tpc.parentElement.classList.contains("hz-leaf");
      if (!leaf) return main.call(this, p);
      // Mind Elixir ends the line at the topic's middle: end it at the bottom, then underline.
      const d = main.call(this, { ...p, cH: p.cH * 2 });
      return `${d} H ${p.direction === "lhs" ? p.cL : p.cL + p.cW}`;
    };

    mind.generateSubBranch = function (p) {
      if (p.direction === "down" || !subQueue) return sub.call(this, p);
      let child = null;
      for (let i = subCursor; i < subQueue.length; i++) {
        const el = subQueue[i];
        if (el.offsetTop === p.cT && el.offsetLeft === p.cL && el.offsetWidth === p.cW && el.offsetHeight === p.cH) {
          child = el;
          subCursor = i + 1;
          break;
        }
      }
      if (!child) return sub.call(this, p);
      const parent = parentOf(child);
      const parentIsNode = parent ? kindOf(mind, parent) === "node" : p.isFirst;
      const childIsNode = child.classList.contains("hz-node");
      // isFirst: the line leaves from the parent's middle (a box) rather than under it;
      // a child node: it reaches the child's middle, its underline hidden by the box.
      return sub.call(this, { ...p, isFirst: parentIsNode, cH: childIsNode ? p.cH / 2 : p.cH });
    };
  }

  return {
    attach(mind) {
      wrapGenerators(mind);
      mind.bus.addListener("operation", refreshPanel);
      refreshPanel();
    },
    beforeLayout,
    afterLayout,
  };
}
