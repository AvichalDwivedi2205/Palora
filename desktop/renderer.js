const MOON_SVG = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>`;
const SUN_SVG = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>`;

const state = {
  config: null,
  sessionId: "sess_demo",
  snapshot: null,
  clusterGraph: null,
  inspector: null,
  activeView: "home",
  activeFocusId: null,
  activeNodeId: null,
  activeDraftId: null,
  liveBuild: {
    active: false,
    stages: [],
    needs: [],
    targetEntities: [],
    graph: { nodes: [], edges: [], clusters: [] },
    newNodeIds: new Set(),
  },
  ephemeralMessages: [],
  paletteQuery: "",
  paletteOpen: false,
};

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function toast(message) {
  const el = document.getElementById("toast-el");
  el.textContent = message;
  el.classList.add("show");
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => el.classList.remove("show"), 2600);
}

async function api(path, options = {}) {
  const response = await fetch(`${state.config.baseUrl}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${state.config.token}`,
      ...(options.headers || {}),
    },
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response.text();
}

function activeQueueItem() {
  if (!state.snapshot?.queue?.length) return null;
  return state.snapshot.queue.find((item) => item.entity_id === state.activeFocusId) || state.snapshot.queue[0];
}

function activeDraft() {
  if (!state.snapshot?.drafts?.length) return null;
  return state.snapshot.drafts.find((draft) => draft.id === state.activeDraftId) || state.snapshot.drafts[0];
}

function nav(view) {
  state.activeView = view;
  document.querySelectorAll(".dock-btn[data-view]").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === view);
  });
  document.querySelectorAll(".view").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.panel === view);
  });
  document.getElementById("status-copy").textContent = `${view[0].toUpperCase()}${view.slice(1)} · Palora desktop flow`;
  if (view === "recall") {
    renderRecall();
  }
}

function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  document.getElementById("theme-toggle").innerHTML = theme === "dark" ? SUN_SVG : MOON_SVG;
  localStorage.setItem("palora-theme", theme);
  renderRecall();
  renderMiniMemory();
  renderContextBuildGraph();
}

function toggleTheme() {
  const current = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  setTheme(current);
}

function openPalette(prefill = "") {
  state.paletteOpen = true;
  state.paletteQuery = prefill;
  document.getElementById("cmd-overlay").classList.add("open");
  const input = document.getElementById("palette-input");
  input.value = prefill;
  renderPalette();
  setTimeout(() => input.focus(), 30);
}

function closePalette() {
  state.paletteOpen = false;
  document.getElementById("cmd-overlay").classList.remove("open");
}

function paletteItems() {
  const items = [];
  if (state.snapshot?.queue) {
    for (const item of state.snapshot.queue) {
      items.push({
        title: item.title,
        sub: item.summary,
        run: () => {
          nav("chat");
          setComposer(item.prompt);
          closePalette();
        },
      });
    }
  }
  items.push(
    {
      title: "What am I waiting on right now?",
      sub: "Quick context sweep.",
      run: () => {
        nav("chat");
        sendChat("What am I waiting on right now?");
        closePalette();
      },
    },
    {
      title: "Open recall graph",
      sub: "Jump into graph mode for memory structure.",
      run: () => {
        nav("recall");
        closePalette();
      },
    },
    {
      title: "Summarize Palora build status",
      sub: "Ask across indexed spec, preview, and queue.",
      run: () => {
        nav("chat");
        setComposer("Summarize Palora build status and suggest next actions.");
        closePalette();
      },
    },
  );
  return items;
}

function renderPalette() {
  const query = state.paletteQuery.trim().toLowerCase();
  let items = paletteItems();
  if (query) {
    items = items.filter((item) => item.title.toLowerCase().includes(query) || item.sub.toLowerCase().includes(query));
    if (!items.length) {
      items = [
        {
          title: `Send to chat: "${state.paletteQuery}"`,
          sub: "Use freeform prompt in agentic chat.",
          run: () => {
            nav("chat");
            sendChat(state.paletteQuery);
            closePalette();
          },
        },
      ];
    }
  }
  const container = document.getElementById("palette-actions");
  container.innerHTML = items
    .map(
      (item, index) => `
        <button class="palette-action" data-palette-index="${index}">
          <strong>${escapeHtml(item.title)}</strong>
          <span>${escapeHtml(item.sub)}</span>
        </button>
      `,
    )
    .join("");
  container.querySelectorAll("[data-palette-index]").forEach((button) => {
    button.addEventListener("click", () => items[Number(button.dataset.paletteIndex)].run());
  });
}

function queueTags(tags = []) {
  return tags
    .map((tag, index) => `<span class="tag${index === 0 ? " amber" : ""}">${escapeHtml(tag)}</span>`)
    .join("");
}

function renderTopbar() {
  if (!state.snapshot) return;
  document.getElementById("chip-open-loops").textContent = `${state.snapshot.stats.open_loops} open`;
  document.getElementById("chip-drafts").textContent = `${state.snapshot.stats.drafts} drafts`;
  document.getElementById("chip-approvals").textContent = `${state.snapshot.stats.pending_approvals} approvals`;
  document.getElementById("dock-drafts-count").textContent = String(state.snapshot.drafts.length);
  document.getElementById("dock-actions-count").textContent = String(
    state.snapshot.actions.filter((action) => action.status === "pending-approval").length,
  );
}

function renderQueue() {
  const container = document.getElementById("queue-list");
  container.innerHTML = (state.snapshot?.queue || [])
    .map(
      (item) => `
        <button class="q-item${item.entity_id === state.activeFocusId ? " active" : ""}" data-focus-id="${item.entity_id}">
          <div class="item-meta">
            <span class="meta-label">${escapeHtml(item.kind)}</span>
            <span class="meta-label">${escapeHtml(item.time)}</span>
          </div>
          <div class="item-title">${escapeHtml(item.title)}</div>
          <div class="tag-row">${queueTags(item.tags)}</div>
        </button>
      `,
    )
    .join("");
  container.querySelectorAll("[data-focus-id]").forEach((button) => {
    button.addEventListener("click", async () => {
      await selectFocus(button.dataset.focusId);
    });
  });
}

function renderSpotlight() {
  const item = activeQueueItem();
  if (!item) return;
  document.getElementById("spotlight").innerHTML = `
    <div class="label">Priority focus</div>
    <div class="spotlight-title">${escapeHtml(item.title)}</div>
    <div class="tag-row">${queueTags(item.tags)}</div>
    <div class="spotlight-actions">
      <button class="btn-primary" id="spotlight-chat">Open full chat</button>
      <button class="btn-ghost" id="spotlight-ask">Quick ask</button>
      <button class="btn-ghost" id="spotlight-recall">Recall</button>
    </div>
  `;
  document.getElementById("spotlight-chat").addEventListener("click", () => {
    nav("chat");
    setComposer(item.prompt);
  });
  document.getElementById("spotlight-ask").addEventListener("click", () => openPalette(item.prompt));
  document.getElementById("spotlight-recall").addEventListener("click", () => nav("recall"));
}

function renderTimeline() {
  const container = document.getElementById("timeline-items");
  container.innerHTML = (state.snapshot?.timeline || [])
    .map(
      (item) => `
        <div class="tl-item">
          <div class="tl-time">${escapeHtml(item.time)}</div>
          <div class="tl-text">${escapeHtml(item.text)}</div>
        </div>
      `,
    )
    .join("");
}

function renderStats() {
  if (!state.snapshot) return;
  const stats = [
    { value: state.snapshot.stats.open_loops, label: "open loops" },
    { value: state.snapshot.stats.pending_approvals, label: "approval pending" },
    { value: state.snapshot.stats.drafts, label: "drafts staged" },
    { value: state.snapshot.stats.next_deadline, label: "next deadline" },
  ];
  document.getElementById("stats-grid").innerHTML = stats
    .map(
      (item) => `
        <div class="stat-tile">
          <strong>${escapeHtml(item.value)}</strong>
          <span>${escapeHtml(item.label)}</span>
        </div>
      `,
    )
    .join("");
}

function renderContext() {
  const item = activeQueueItem();
  if (!item) return;
  const context = item.context || {};
  document.getElementById("context-panel").innerHTML = `
    <div class="meta-label">${escapeHtml(context.eyebrow || "Focus context")}</div>
    <div class="ctx-name">${escapeHtml(context.name || item.title)}</div>
    <div class="ctx-stats">
      ${(context.stats || [])
        .map(
          (stat) => `
            <div class="ctx-stat">
              <strong>${escapeHtml(stat.v)}</strong>
              <span>${escapeHtml(stat.l)}</span>
            </div>
          `,
        )
        .join("")}
    </div>
    <div class="tag-row">${queueTags(context.tags || item.tags)}</div>
    <div class="stack-actions">
      ${(context.actions || [])
        .map((action) => `<button class="mini-action" data-context-action="${escapeHtml(action)}">${escapeHtml(action)}</button>`)
        .join("")}
    </div>
  `;
  document.querySelectorAll("[data-context-action]").forEach((button) => {
    button.addEventListener("click", () => handleContextAction(button.dataset.contextAction));
  });
}

function handleContextAction(action) {
  if (action.includes("full chat")) {
    nav("chat");
    return;
  }
  if (action.includes("recall")) {
    nav("recall");
    return;
  }
  if (action.toLowerCase().includes("reminder")) {
    nav("act");
    return;
  }
  if (action.toLowerCase().includes("draft") || action.toLowerCase().includes("review")) {
    nav("drafts");
    return;
  }
  toast(action);
}

function setComposer(value) {
  document.getElementById("chat-composer").value = value;
}

function renderSuggestions() {
  const suggestions = [
    "Draft follow-up to Recruiter X in my tone and ask me before sending.",
    "What am I waiting on right now?",
    "Summarize Priya backend spec for me.",
  ];
  document.getElementById("chat-suggestions").innerHTML = suggestions
    .map((value) => `<button class="suggestion" data-suggestion="${escapeHtml(value)}">${escapeHtml(value)}</button>`)
    .join("");
  document.querySelectorAll("[data-suggestion]").forEach((button) => {
    button.addEventListener("click", () => setComposer(button.dataset.suggestion));
  });
}

function renderChat() {
  const persisted = state.snapshot?.chat_messages || [];
  const messages = [...persisted, ...state.ephemeralMessages];
  const container = document.getElementById("chat-thread");
  container.innerHTML = messages
    .map((message) => {
      const tool = message.tool
        ? `
          <div class="chat-tool">
            <h4>${escapeHtml(message.tool.title || "Prepared next step")}</h4>
            <p>${escapeHtml(message.tool.summary || "")}</p>
            <div class="chat-tool-actions">
              ${(message.tool.actions || [])
                .map(
                  (action) =>
                    `<button class="${action.toLowerCase().includes("draft") ? "primary" : ""}" data-tool-action="${escapeHtml(action)}">${escapeHtml(action)}</button>`,
                )
                .join("")}
            </div>
          </div>
        `
        : "";
      return `
        <div class="msg ${message.role}">
          <div class="msg-av">${message.role === "assistant" ? "P" : "Y"}</div>
          <div>
            <div class="msg-who">${escapeHtml(message.label)}</div>
            <div class="bubble">${escapeHtml(message.body)}${tool}</div>
          </div>
        </div>
      `;
    })
    .join("");
  container.scrollTop = container.scrollHeight;
  container.querySelectorAll("[data-tool-action]").forEach((button) => {
    button.addEventListener("click", () => handleContextAction(button.dataset.toolAction));
  });
}

function renderChatContext() {
  const item = activeQueueItem();
  if (!item) return;
  document.getElementById("chat-context").innerHTML = `
    <div class="s-eyebrow">${escapeHtml(item.kind)}</div>
    <h3>${escapeHtml(item.title)}</h3>
    <p>${escapeHtml(item.summary)}</p>
    <div class="tag-row">${queueTags(item.tags)}</div>
  `;
}

function renderDrafts() {
  const drafts = state.snapshot?.drafts || [];
  if (!state.activeDraftId && drafts[0]) state.activeDraftId = drafts[0].id;
  document.getElementById("draft-list").innerHTML = drafts
    .map(
      (draft) => `
        <button class="draft-item${draft.id === state.activeDraftId ? " active" : ""}" data-draft-id="${draft.id}">
          <div class="item-meta">
            <span class="meta-label">${escapeHtml(draft.kind)}</span>
            <span class="meta-label">${escapeHtml(draft.status)}</span>
          </div>
          <div class="item-title">${escapeHtml(draft.title)}</div>
          <div class="item-body">${escapeHtml(draft.summary)}</div>
          <div class="tag-row">
            <span class="tag amber">${escapeHtml(draft.status)}</span>
            <span class="tag">${escapeHtml(draft.kind)}</span>
          </div>
        </button>
      `,
    )
    .join("");
  document.querySelectorAll("[data-draft-id]").forEach((button) => {
    button.addEventListener("click", () => {
      state.activeDraftId = button.dataset.draftId;
      renderDrafts();
    });
  });
  renderDraftDetail();
}

function renderDraftDetail() {
  const draft = activeDraft();
  const container = document.getElementById("draft-detail");
  if (!draft) {
    container.innerHTML = `<p class="item-body">No draft selected.</p>`;
    return;
  }
  container.innerHTML = `
    <div class="draft-detail-shell">
      <div class="meta-label">${escapeHtml(draft.kind)}</div>
      <div class="draft-title">${escapeHtml(draft.title)}</div>
      <p class="item-body">${escapeHtml(draft.summary)}</p>
      <div class="draft-body">${escapeHtml(draft.body)}</div>
      <div class="draft-actions">
        <button class="primary" id="draft-open-chat">Open in chat</button>
        <button id="draft-open-act">Send to act lane</button>
      </div>
    </div>
  `;
  document.getElementById("draft-open-chat").addEventListener("click", () => {
    nav("chat");
    setComposer(`Rewrite this draft with same intent but slightly tighter opener:\n\n${draft.body}`);
  });
  document.getElementById("draft-open-act").addEventListener("click", () => nav("act"));
}

function actionTitle(action) {
  const args = action.prepared_args || {};
  return args.title || args.subject || action.tool_name.replace(".", " ");
}

function actionSummary(action) {
  const args = action.prepared_args || {};
  return args.notes || args.body || action.reason;
}

function renderActions() {
  const actions = state.snapshot?.actions || [];
  const container = document.getElementById("act-list");
  container.innerHTML = actions
    .map(
      (action) => `
        <div class="act-item">
          <div class="item-meta">
            <span class="meta-label">${escapeHtml(action.tool_name)}</span>
            <span class="meta-label">${escapeHtml(action.status)}</span>
          </div>
          <div class="item-title">${escapeHtml(actionTitle(action))}</div>
          <div class="item-body">${escapeHtml(actionSummary(action))}</div>
          <div class="tag-row">
            <span class="tag amber">Risk ${escapeHtml(action.risk_class)}</span>
            <span class="tag">${escapeHtml(action.status)}</span>
          </div>
          <div class="action-buttons">
            ${
              action.status === "pending-approval" || action.status === "ready"
                ? `
                  <button class="primary" data-approve-id="${action.id}">${action.requires_approval ? "Approve" : "Run"}</button>
                  <button data-reject-id="${action.id}">Reject</button>
                `
                : ""
            }
          </div>
        </div>
      `,
    )
    .join("");
  container.querySelectorAll("[data-approve-id]").forEach((button) => {
    button.addEventListener("click", async () => {
      const action = (state.snapshot?.actions || []).find((item) => item.id === button.dataset.approveId);
      if (!action) return;
      await api(`/v1/actions/${action.id}/approve`, {
        method: "POST",
        body: JSON.stringify({ prepared_hash: action.prepared_hash }),
      });
      toast(`Executed ${action.tool_name}`);
      await refreshData(false);
    });
  });
  container.querySelectorAll("[data-reject-id]").forEach((button) => {
    button.addEventListener("click", async () => {
      await api(`/v1/actions/${button.dataset.rejectId}/reject`, {
        method: "POST",
      });
      toast("Action rejected");
      await refreshData(false);
    });
  });
}

function clusterCenters(count, variant) {
  if (variant === "mini") {
    return [
      { x: 28, y: 42, w: 38, h: 58 },
      { x: 72, y: 42, w: 38, h: 58 },
      { x: 50, y: 76, w: 42, h: 36 },
    ].slice(0, Math.max(count, 1));
  }
  return [
    { x: 24, y: 34, w: 32, h: 52 },
    { x: 72, y: 34, w: 32, h: 52 },
    { x: 28, y: 76, w: 30, h: 28 },
    { x: 72, y: 76, w: 30, h: 28 },
  ].slice(0, Math.max(count, 1));
}

function layoutGraph(graph, variant = "full") {
  const groups = new Map();
  for (const node of graph.nodes || []) {
    const key = node.cluster_id || node.kind || "misc";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(node);
  }
  const entries = Array.from(groups.entries());
  const centers = clusterCenters(entries.length, variant);
  const positions = new Map();
  const bubbles = [];
  entries.forEach(([clusterId, nodes], clusterIndex) => {
    const center = centers[clusterIndex] || { x: 50, y: 50, w: 30, h: 30 };
    bubbles.push({
      clusterId,
      label: nodes[0]?.cluster_label || clusterId.replaceAll("_", " "),
      x: center.x,
      y: center.y,
      w: center.w,
      h: center.h,
    });
    const radius = variant === "mini" ? 12 : 14;
    nodes.forEach((node, nodeIndex) => {
      const angle = (Math.PI * 2 * nodeIndex) / Math.max(nodes.length, 1);
      const x = center.x + Math.cos(angle) * radius;
      const y = center.y + Math.sin(angle) * radius * 0.9;
      positions.set(node.id, { x, y });
    });
  });
  return { positions, bubbles };
}

function edgeStyle(kind) {
  const dark = document.documentElement.dataset.theme === "dark";
  const styles = {
    waiting_on: { stroke: dark ? "rgba(232,168,74,0.55)" : "rgba(180,110,20,0.5)", width: 1.8, dash: "6 5" },
    recruiter_for: { stroke: dark ? "rgba(255,248,238,0.18)" : "rgba(40,24,10,0.18)", width: 1.2, dash: "" },
    works_with: { stroke: dark ? "rgba(255,248,238,0.2)" : "rgba(40,24,10,0.2)", width: 1.4, dash: "" },
    used_in: { stroke: dark ? "rgba(140,128,240,0.38)" : "rgba(100,90,200,0.38)", width: 1.3, dash: "3 5" },
    mentions: { stroke: dark ? "rgba(255,248,238,0.12)" : "rgba(40,24,10,0.14)", width: 1.1, dash: "4 5" },
    derived_from: { stroke: dark ? "rgba(93,201,168,0.34)" : "rgba(60,150,130,0.34)", width: 1.2, dash: "4 4" },
  };
  return styles[kind] || styles.mentions;
}

function renderGraphStage(container, graph, activeNodeId, variant = "full", newNodeIds = new Set()) {
  if (!container || !graph) return;
  const { positions, bubbles } = layoutGraph(graph, variant);
  container.innerHTML = "";
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "graph-svg");
  container.appendChild(svg);

  for (const bubble of bubbles) {
    const bubbleEl = document.createElement("div");
    bubbleEl.className = "cluster-bubble";
    bubbleEl.style.left = `${bubble.x - bubble.w / 2}%`;
    bubbleEl.style.top = `${bubble.y - bubble.h / 2}%`;
    bubbleEl.style.width = `${bubble.w}%`;
    bubbleEl.style.height = `${bubble.h}%`;
    container.appendChild(bubbleEl);

    const labelEl = document.createElement("div");
    labelEl.className = "cluster-label";
    labelEl.style.left = `${bubble.x - bubble.w / 2 + 2}%`;
    labelEl.style.top = `${bubble.y - bubble.h / 2 + 2}%`;
    labelEl.textContent = bubble.label;
    container.appendChild(labelEl);
  }

  for (const edge of graph.edges || []) {
    const from = positions.get(edge.source);
    const to = positions.get(edge.target);
    if (!from || !to) continue;
    const style = edgeStyle(edge.kind);
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    const cx = from.x + (to.x - from.x) * 0.5 + (to.y - from.y) * 0.08;
    const cy = from.y + (to.y - from.y) * 0.5 - (to.x - from.x) * 0.08;
    path.setAttribute("d", `M ${from.x}% ${from.y}% Q ${cx}% ${cy}% ${to.x}% ${to.y}%`);
    path.setAttribute("fill", "none");
    path.setAttribute("stroke", style.stroke);
    path.setAttribute("stroke-width", String(style.width));
    if (style.dash) path.setAttribute("stroke-dasharray", style.dash);
    svg.appendChild(path);
  }

  for (const node of graph.nodes || []) {
    const pos = positions.get(node.id);
    if (!pos) continue;
    const button = document.createElement("button");
    button.className = `graph-node ${node.kind}${node.id === activeNodeId ? " active" : ""}${newNodeIds.has(node.id) ? " enter" : ""}`;
    button.style.left = `${pos.x}%`;
    button.style.top = `${pos.y}%`;
    button.innerHTML = `
      <div class="graph-halo"></div>
      <div class="graph-vis">${escapeHtml((node.label || "").split(" ").slice(0, 2).map((part) => part[0]).join("").slice(0, 4) || "N")}</div>
      <div class="graph-label">${escapeHtml(node.label)}</div>
    `;
    button.addEventListener("click", () => selectNode(node.id));
    container.appendChild(button);
  }
}

function renderRecall() {
  if (!state.clusterGraph) return;
  renderGraphStage(document.getElementById("recall-stage"), state.clusterGraph, state.activeNodeId, "full");
  document.getElementById("cluster-chip-row").innerHTML = (state.clusterGraph.clusters || [])
    .map((cluster, index) => `<div class="chip${index === 0 ? " amber" : ""}">${escapeHtml(cluster.cluster_label)} · ${cluster.count}</div>`)
    .join("");
  renderInspector();
}

function renderMiniMemory() {
  if (!state.clusterGraph) return;
  const graph = {
    ...state.clusterGraph,
    nodes: state.clusterGraph.nodes.slice(0, 6),
    edges: state.clusterGraph.edges.slice(0, 6),
  };
  renderGraphStage(document.getElementById("mini-memory-stage"), graph, state.activeNodeId, "mini");
}

function renderContextBuild() {
  const container = document.getElementById("context-build");
  const stages = state.liveBuild.active
    ? state.liveBuild.stages
    : [{ step: "idle", label: "Idle. Send prompt to watch nodes populate.", status: "done" }];
  const needs = state.liveBuild.needs || [];
  container.innerHTML = `
    ${stages
      .map(
        (stage) => `
          <div class="build-stage ${stage.status}">
            <span>${escapeHtml(stage.label)}</span>
          </div>
        `,
      )
      .join("")}
    ${
      needs.length
        ? `<div class="tag-row">${needs.map((need) => `<span class="tag amber">${escapeHtml(need)}</span>`).join("")}</div>`
        : ""
    }
  `;
  renderContextBuildGraph();
}

function renderContextBuildGraph() {
  const graph = state.liveBuild.active && state.liveBuild.graph.nodes.length ? state.liveBuild.graph : state.clusterGraph;
  if (!graph) return;
  renderGraphStage(
    document.getElementById("context-build-graph"),
    graph,
    state.activeNodeId,
    "mini",
    state.liveBuild.newNodeIds,
  );
}

function renderInspector() {
  const container = document.getElementById("recall-inspector");
  const inspector = state.inspector;
  if (!inspector) {
    container.innerHTML = `<div class="inspector-block"><p class="item-body">Select node to inspect.</p></div>`;
    return;
  }
  container.innerHTML = `
    <div class="inspector-block">
      <div class="meta-label">${escapeHtml(inspector.node.kind)}</div>
      <h2>${escapeHtml(inspector.node.label)}</h2>
      <p>${escapeHtml(inspector.summary)}</p>
    </div>
    <div class="inspector-block">
      <div class="meta-label">Evidence</div>
      ${(inspector.evidence || [])
        .map((item) => `<p class="item-body">${escapeHtml(item.title)}: ${escapeHtml(item.text.slice(0, 140))}</p>`)
        .join("")}
    </div>
    <div class="inspector-block">
      <div class="meta-label">Rules</div>
      ${(inspector.rules || []).map((rule) => `<p class="item-body">${escapeHtml(rule.text)}</p>`).join("")}
    </div>
    <div class="inspector-block">
      <div class="meta-label">Recent history</div>
      ${(inspector.history || []).map((item) => `<p class="item-body">${escapeHtml(item.text)}</p>`).join("")}
    </div>
  `;
}

async function selectFocus(entityId) {
  state.activeFocusId = entityId;
  await loadClusterGraph();
  renderAll();
}

async function selectNode(nodeId) {
  state.activeNodeId = nodeId;
  state.inspector = await api(`/v1/graph/node/${encodeURIComponent(nodeId)}`);
  renderRecall();
  renderMiniMemory();
  renderContextBuildGraph();
}

async function loadClusterGraph() {
  if (!state.activeFocusId) return;
  state.clusterGraph = await api(
    `/v1/graph/root?mode=cluster&session_id=${encodeURIComponent(state.sessionId)}&focus_entity_id=${encodeURIComponent(state.activeFocusId)}&limit=18`,
  );
  const validNodeIds = new Set((state.clusterGraph.nodes || []).map((node) => node.id));
  if (!state.activeNodeId || !validNodeIds.has(state.activeNodeId)) {
    state.activeNodeId = state.activeFocusId || state.clusterGraph.nodes?.[0]?.id || null;
  }
  if (state.activeNodeId) {
    state.inspector = await api(`/v1/graph/node/${encodeURIComponent(state.activeNodeId)}`);
  }
}

async function refreshData(preserveFocus = true) {
  state.snapshot = await api(`/v1/sessions/${encodeURIComponent(state.sessionId)}/snapshot`);
  if (!preserveFocus || !state.activeFocusId) {
    state.activeFocusId = state.snapshot.active_focus_id || state.snapshot.queue?.[0]?.entity_id || null;
  }
  if (!state.activeDraftId && state.snapshot.drafts?.[0]) {
    state.activeDraftId = state.snapshot.drafts[0].id;
  }
  await loadClusterGraph();
  renderAll();
}

function renderAll() {
  renderTopbar();
  renderQueue();
  renderSpotlight();
  renderTimeline();
  renderStats();
  renderContext();
  renderSuggestions();
  renderChat();
  renderChatContext();
  renderDrafts();
  renderActions();
  renderRecall();
  renderMiniMemory();
  renderContextBuild();
}

function resetLiveBuild() {
  state.liveBuild = {
    active: true,
    stages: [],
    needs: [],
    targetEntities: [],
    graph: { nodes: [], edges: [], clusters: [] },
    newNodeIds: new Set(),
  };
  renderContextBuild();
}

function markBuildStage(step, label) {
  const stages = state.liveBuild.stages.map((stage) => ({
    ...stage,
    status: stage.status === "active" ? "done" : stage.status,
  }));
  const existing = stages.find((stage) => stage.step === step);
  if (existing) {
    existing.label = label;
    existing.status = "active";
  } else {
    stages.push({ step, label, status: "active" });
  }
  state.liveBuild.stages = stages;
  renderContextBuild();
}

function upsertGraphDelta(payload) {
  const graph = state.liveBuild.graph;
  if (payload.kind === "node") {
    if (!graph.nodes.some((node) => node.id === payload.node.id)) {
      graph.nodes.push(payload.node);
      state.liveBuild.newNodeIds.add(payload.node.id);
    }
  }
  if (payload.kind === "edge") {
    if (!graph.edges.some((edge) => edge.id === payload.edge.id)) {
      graph.edges.push(payload.edge);
    }
  }
  graph.clusters = Array.from(
    new Map(
      graph.nodes.map((node) => [
        node.cluster_id || node.kind,
        {
          cluster_id: node.cluster_id || node.kind,
          cluster_label: node.cluster_label || (node.cluster_id || node.kind),
          count: graph.nodes.filter((item) => (item.cluster_id || item.kind) === (node.cluster_id || node.kind)).length,
        },
      ]),
    ).values(),
  );
  if (state.clusterGraph) {
    if (payload.kind === "node" && !state.clusterGraph.nodes.some((node) => node.id === payload.node.id)) {
      state.clusterGraph.nodes.push(payload.node);
    }
    if (payload.kind === "edge" && !state.clusterGraph.edges.some((edge) => edge.id === payload.edge.id)) {
      state.clusterGraph.edges.push(payload.edge);
    }
  }
  renderContextBuildGraph();
  renderMiniMemory();
  if (state.activeView === "recall") renderRecall();
}

async function parseSSE(response) {
  const decoder = new TextDecoder();
  const reader = response.body.getReader();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() || "";
    for (const part of parts) {
      const lines = part.split("\n").filter(Boolean);
      let eventName = "message";
      let data = "";
      for (const line of lines) {
        if (line.startsWith("event:")) eventName = line.slice(6).trim();
        if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      if (!data) continue;
      handleStreamEvent(eventName, JSON.parse(data));
    }
  }
}

function handleStreamEvent(eventName, data) {
  if (eventName === "status") {
    markBuildStage(data.step, data.label);
    return;
  }
  if (eventName === "retrieval_plan") {
    state.liveBuild.needs = data.needs || [];
    state.liveBuild.targetEntities = data.target_entities || [];
    renderContextBuild();
    return;
  }
  if (eventName === "graph_delta") {
    upsertGraphDelta(data);
    return;
  }
  if (eventName === "pending_action") {
    state.snapshot.actions = [data, ...(state.snapshot.actions || []).filter((item) => item.id !== data.id)];
    renderActions();
    renderTopbar();
    return;
  }
  if (eventName === "draft_created") {
    toast(`Draft staged: ${data.title}`);
    return;
  }
  if (eventName === "token") {
    const streaming = state.ephemeralMessages.find((message) => message.id === "streaming-assistant");
    if (streaming) {
      streaming.body += data.text;
      renderChat();
    }
    return;
  }
  if (eventName === "final") {
    const streaming = state.ephemeralMessages.find((message) => message.id === "streaming-assistant");
    if (streaming) streaming.body = data.assistant_message;
  }
}

async function sendChat(prefilled = null) {
  const composer = document.getElementById("chat-composer");
  const message = (prefilled ?? composer.value).trim();
  if (!message) return;
  composer.value = "";
  nav("chat");
  resetLiveBuild();
  state.ephemeralMessages = [
    ...state.ephemeralMessages.filter((messageItem) => !messageItem.id?.startsWith("streaming")),
    {
      id: `user-${Date.now()}`,
      role: "user",
      label: "You",
      body: message,
    },
    {
      id: "streaming-assistant",
      role: "assistant",
      label: "Palora",
      body: "",
    },
  ];
  renderChat();

  const response = await fetch(`${state.config.baseUrl}/v1/chat/turn/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${state.config.token}`,
    },
    body: JSON.stringify({
      session_id: state.sessionId,
      message,
      attachments: [],
      mode: "default",
    }),
  });

  if (!response.ok) {
    toast("Chat stream failed");
    return;
  }

  await parseSSE(response);
  state.liveBuild.stages = state.liveBuild.stages.map((stage) => ({
    ...stage,
    status: stage.status === "active" ? "done" : stage.status,
  }));
  state.liveBuild.active = false;
  state.ephemeralMessages = [];
  await refreshData(true);
}

async function submitIngest() {
  const title = document.getElementById("ingest-title").value.trim();
  const text = document.getElementById("ingest-text").value.trim();
  if (!title || !text) {
    toast("Need title + text");
    return;
  }
  await api("/v1/ingest/source", {
    method: "POST",
    body: JSON.stringify({
      source_type: "pasted_text",
      source_ref: `manual_${Date.now()}`,
      title,
      text,
      metadata: { origin: "desktop_ingest" },
    }),
  });
  document.getElementById("ingest-title").value = "";
  document.getElementById("ingest-text").value = "";
  toast("Source indexed");
  await refreshData(false);
}

function attachStaticEvents() {
  document.querySelectorAll(".dock-btn[data-view]").forEach((button) => {
    button.addEventListener("click", () => nav(button.dataset.view));
  });
  document.querySelectorAll("[data-nav]").forEach((button) => {
    button.addEventListener("click", () => nav(button.dataset.nav));
  });
  document.querySelectorAll("[data-open-palette]").forEach((button) => {
    button.addEventListener("click", () => openPalette());
  });
  document.querySelectorAll("[data-quick]").forEach((button) => {
    button.addEventListener("click", () => sendChat(button.dataset.quick));
  });

  document.getElementById("refresh-app").addEventListener("click", () => refreshData(false));
  document.getElementById("theme-toggle").addEventListener("click", toggleTheme);
  document.getElementById("open-palette").addEventListener("click", () => openPalette());
  document.getElementById("send-chat").addEventListener("click", () => sendChat());
  document.getElementById("submit-ingest").addEventListener("click", submitIngest);
  document.getElementById("chat-composer").addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      sendChat();
    }
  });

  const overlay = document.getElementById("cmd-overlay");
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay) closePalette();
  });
  document.getElementById("palette-input").addEventListener("input", (event) => {
    state.paletteQuery = event.target.value;
    renderPalette();
  });
  document.getElementById("palette-input").addEventListener("keydown", (event) => {
    if (event.key === "Escape") closePalette();
    if (event.key === "Enter") {
      event.preventDefault();
      const first = document.querySelector("#palette-actions [data-palette-index='0']");
      first?.click();
    }
  });

  document.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      openPalette();
    }
    if (event.key === "Escape") closePalette();
  });

  window.addEventListener("resize", () => {
    renderRecall();
    renderMiniMemory();
    renderContextBuildGraph();
  });
}

async function init() {
  const savedTheme = localStorage.getItem("palora-theme") || "dark";
  setTheme(savedTheme);
  attachStaticEvents();
  state.config = await window.paloraDesktop.getConfig();
  await refreshData(false);
}

init().catch((error) => {
  console.error(error);
  toast("Palora boot failed");
});
