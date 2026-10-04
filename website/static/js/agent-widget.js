/* ============================================================
   Kubeflow Docs Agent — Chat Widget (vanilla JS, no build step)
   Streams answers from the agent API (server-https) over SSE.

   Contract with the API:
     POST {API_URL}  body {message, stream, thread_id, context}
                     headers X-LLM-API-Key / X-LLM-Model (optional, bring-your-own-key)
     SSE events: thread, tool_result, content, citations, error, done
     GET  {CONFIG_URL} key policy + provider host
   ============================================================ */
(function () {
  "use strict";

  if (window.__kfAgentWidgetLoaded) return;
  window.__kfAgentWidgetLoaded = true;

  // --- Config --------------------------------------------------
  function resolveApiUrl() {
    const runtimeConfig = window.KUBEFLOW_AGENT_CONFIG || {};
    if (runtimeConfig.apiUrl) {
      return runtimeConfig.apiUrl;
    }

    const isLocal =
      window.location.hostname === "localhost" ||
      window.location.hostname === "127.0.0.1";

    if (isLocal) {
      return "http://localhost:8000/chat";
    }

    // Same-origin path; put a reverse proxy in front of the agent API or
    // set window.KUBEFLOW_AGENT_CONFIG.apiUrl (see website/README.md).
    return "/api/agent/chat";
  }

  const API_URL = resolveApiUrl();
  const CONFIG_URL = API_URL.replace(/\/chat\/?$/, "/config");
  const MARKED_CDN = "https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js";
  const PURIFY_CDN = "https://cdn.jsdelivr.net/npm/dompurify@3.1.6/dist/purify.min.js";

  const STORE = {
    thread: "kf-thread-id",
    messages: "kf-chat-v2",
    legacyMessages: "kf-messages",
    open: "kf-panel-open",
    width: "kf-panel-width",
    wide: "kf-panel-wide",
  };
  // Bring-your-own key: sessionStorage only, so it disappears with the tab.
  const KEY_STORE = "kf-llm-api-key";
  const MODEL_STORE = "kf-llm-model";
  const MAX_SAVED_MESSAGES = 40;

  // --- State ---------------------------------------------------
  const state = {
    open: false,
    threadId: null,
    messages: [], // {role, content, citations, steps, error, stopped}
    streaming: false,
    controller: null,
    serverConfig: null,
    stickToBottom: true,
  };

  // --- Icons (inline SVG, currentColor) --------------------------
  const svg = (body, extra) =>
    '<svg viewBox="0 0 24 24" aria-hidden="true" ' + (extra || "") + ">" + body + "</svg>";
  const ICON = {
    sparkle: svg('<path d="M12 3l1.9 5.8a2 2 0 0 0 1.3 1.3L21 12l-5.8 1.9a2 2 0 0 0-1.3 1.3L12 21l-1.9-5.8a2 2 0 0 0-1.3-1.3L3 12l5.8-1.9a2 2 0 0 0 1.3-1.3z"/>'),
    close: svg('<path d="M18 6 6 18M6 6l12 12"/>'),
    plus: svg('<path d="M12 5v14M5 12h14"/>'),
    key: svg('<circle cx="7.5" cy="15.5" r="5.5"/><path d="m21 2-9.6 9.6M15.5 7.5l3 3L22 7l-3-3"/>'),
    send: svg('<path d="M12 19V5M5 12l7-7 7 7"/>'),
    stop: svg('<rect x="7" y="7" width="10" height="10" rx="2"/>', 'class="kf-fill"'),
    copy: svg('<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/>'),
    check: svg('<path d="M20 6 9 17l-5-5"/>'),
    retry: svg('<path d="M3 12a9 9 0 0 1 15.5-6.2L21 8M21 3v5h-5M21 12a9 9 0 0 1-15.5 6.2L3 16M3 21v-5h5"/>'),
    expand: svg('<path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/>'),
    collapse: svg('<path d="M4 14h6v6M20 10h-6V4M14 10l7-7M3 21l7-7"/>'),
    doc: svg('<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h4"/>'),
    code: svg('<path d="m16 18 6-6-6-6M8 6l-6 6 6 6"/>'),
    search: svg('<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>'),
    route: svg('<path d="M6 3v12M18 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM18 9a9 9 0 0 1-9 9"/>'),
    pen: svg('<path d="M12 20h9M16.5 3.5a2.1 2.1 0 1 1 3 3L7 19l-4 1 1-4z"/>'),
    down: svg('<path d="M12 5v14M19 12l-7 7-7-7"/>'),
    rocket: svg('<path d="M4.5 16.5c-1.5 1.3-2 5-2 5s3.7-.5 5-2c.7-.8.7-2.1-.1-2.9a2.2 2.2 0 0 0-2.9-.1zM12 15l-3-3a22 22 0 0 1 2-3.9A12.9 12.9 0 0 1 22 2c0 2.7-.8 7.5-6 11a22.4 22.4 0 0 1-4 2z"/>'),
    box: svg('<path d="M21 8 12 3 3 8v8l9 5 9-5z"/><path d="m3 8 9 5 9-5M12 13v8"/>'),
    bug: svg('<path d="M8 2l1.9 1.9M16 2l-1.9 1.9M9 7.1V6a3 3 0 1 1 6 0v1.1M12 20c-3.3 0-6-2.7-6-6v-3a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v3c0 3.3-2.7 6-6 6zM12 20v-9M6.5 13H3M21 13h-3.5M6 9l-3-2M18 9l3-2M6 17l-3 2M18 17l3 2"/>'),
  };

  // --- Storage helpers (never throw: private mode, blocked storage) ---
  function lsGet(name) { try { return localStorage.getItem(name); } catch (e) { return null; } }
  function lsSet(name, value) { try { localStorage.setItem(name, value); } catch (e) { /* ignore */ } }
  function lsRemove(name) { try { localStorage.removeItem(name); } catch (e) { /* ignore */ } }
  function readSession(name) { try { return sessionStorage.getItem(name) || ""; } catch (e) { return ""; } }
  function writeSession(name, value) {
    try {
      if (value) sessionStorage.setItem(name, value);
      else sessionStorage.removeItem(name);
    } catch (e) { /* storage unavailable: key lives only for this request */ }
  }

  const $ = (id) => document.getElementById(id);

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str == null ? "" : String(str);
    return div.innerHTML;
  }

  function pageTitle() {
    const h1 = document.querySelector("main h1, .td-content h1, h1");
    return ((h1 && h1.innerText) || document.title || "this page").trim();
  }

  // --- Markdown (sanitized) ------------------------------------
  function renderMarkdown(text) {
    if (window.marked && window.DOMPurify) {
      const html = window.marked.parse(text || "", { gfm: true, breaks: false });
      return window.DOMPurify.sanitize(html);
    }
    // Without a sanitizer never inject model HTML: escape and keep line breaks.
    return "<p>" + escapeHtml(text || "").replace(/\n/g, "<br>") + "</p>";
  }

  function enhanceMarkdown(container) {
    container.querySelectorAll("a[href]").forEach((a) => {
      a.target = "_blank";
      a.rel = "noopener noreferrer";
    });
    container.querySelectorAll("pre").forEach((pre) => {
      if (pre.parentElement && pre.parentElement.classList.contains("kf-code")) return;
      const code = pre.querySelector("code");
      const match = code && /language-([\w+-]+)/.exec(code.className || "");
      const wrap = document.createElement("div");
      wrap.className = "kf-code";
      const head = document.createElement("div");
      head.className = "kf-code-head";
      const lang = document.createElement("span");
      lang.textContent = match ? match[1] : "code";
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "kf-code-copy";
      btn.innerHTML = ICON.copy + "<span>Copy</span>";
      btn.addEventListener("click", () => copyText((code || pre).innerText, btn));
      head.appendChild(lang);
      head.appendChild(btn);
      pre.parentNode.insertBefore(wrap, pre);
      wrap.appendChild(head);
      wrap.appendChild(pre);
    });
  }

  function copyText(text, button) {
    const done = () => {
      if (!button) return;
      const original = button.innerHTML;
      button.innerHTML = ICON.check + "<span>Copied</span>";
      button.classList.add("kf-copied");
      setTimeout(() => {
        button.innerHTML = original;
        button.classList.remove("kf-copied");
      }, 1500);
    };
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(done, () => fallbackCopy(text, done));
    } else {
      fallbackCopy(text, done);
    }
  }

  function fallbackCopy(text, done) {
    const area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    try { document.execCommand("copy"); done(); } catch (e) { /* ignore */ }
    area.remove();
  }

  // --- Sources -------------------------------------------------
  function titleCase(slug) {
    return decodeURIComponent(slug)
      .replace(/[-_]+/g, " ")
      .replace(/\.(md|html?)$/i, "")
      .replace(/\b\w/g, (c) => c.toUpperCase());
  }

  function describeSource(url) {
    try {
      const u = new URL(url, window.location.href);
      if (u.hostname === "github.com") {
        const parts = u.pathname.split("/").filter(Boolean);
        const blob = parts.indexOf("blob");
        const filePath = blob >= 0 ? parts.slice(blob + 2) : parts.slice(2);
        const file = filePath[filePath.length - 1] || parts[1] || "GitHub";
        const dir = filePath.slice(0, -1).join("/");
        const line = /^#L(\d+)/.exec(u.hash);
        return {
          kind: "code",
          title: file,
          subtitle: (parts[0] && parts[1] ? parts[0] + "/" + parts[1] : "github") +
            (dir ? " · " + dir : "") + (line ? " · L" + line[1] : ""),
        };
      }
      const segments = u.pathname.split("/").filter(Boolean);
      const docsIndex = segments.indexOf("docs");
      const trail = (docsIndex >= 0 ? segments.slice(docsIndex + 1) : segments).map(titleCase);
      return {
        kind: "docs",
        title: trail[trail.length - 1] || u.hostname,
        subtitle: [u.hostname.replace(/^www\./, "")].concat(trail.slice(0, -1)).join(" › "),
      };
    } catch (e) {
      return { kind: "docs", title: url, subtitle: "" };
    }
  }

  // --- DOM -----------------------------------------------------
  function buildDom() {
    const btn = document.createElement("button");
    btn.id = "kf-agent-btn";
    btn.type = "button";
    btn.setAttribute("aria-label", "Ask the Kubeflow AI assistant");
    const isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
    btn.innerHTML = ICON.sparkle + "<span>Ask AI</span><kbd>" + (isMac ? "⌘" : "Ctrl") + " I</kbd>";
    btn.addEventListener("click", () => toggle(true));
    document.body.appendChild(btn);

    const panel = document.createElement("aside");
    panel.id = "kf-agent-panel";
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", "Kubeflow AI assistant");
    panel.innerHTML = `
      <div id="kf-resizer" aria-hidden="true"></div>
      <header class="kf-header">
        <div class="kf-brand">
          <span class="kf-logo">${ICON.sparkle}</span>
          <div class="kf-brand-text">
            <div class="kf-title">Kubeflow Assistant</div>
            <div class="kf-status" id="kf-status">Docs + manifests · Online</div>
          </div>
        </div>
        <div class="kf-header-actions">
          <button type="button" id="kf-new-chat" class="kf-icon-btn" aria-label="New chat" title="New chat">${ICON.pen}</button>
          <button type="button" id="kf-key-btn" class="kf-icon-btn" aria-label="LLM API key settings" title="Use your own LLM API key">${ICON.key}</button>
          <button type="button" id="kf-wide-btn" class="kf-icon-btn" aria-label="Toggle wide view" title="Wide view">${ICON.expand}</button>
          <button type="button" id="kf-close" class="kf-icon-btn" aria-label="Close assistant" title="Close (Esc)">${ICON.close}</button>
        </div>
      </header>
      <div id="kf-key-panel" hidden>
        <div class="kf-key-title">${ICON.key}<span>Use your own LLM API key</span></div>
        <p class="kf-key-help" id="kf-key-help">Your key is kept only in this browser tab (sessionStorage, cleared when the tab closes) and is sent only to this assistant's API with your questions.</p>
        <label for="kf-key-input">API key</label>
        <input id="kf-key-input" type="password" autocomplete="off" spellcheck="false" placeholder="Paste your key">
        <label for="kf-model-input">Model <span class="kf-optional">optional</span></label>
        <input id="kf-model-input" type="text" autocomplete="off" spellcheck="false" placeholder="Server default">
        <div class="kf-key-actions">
          <button id="kf-key-clear" type="button" class="kf-btn kf-btn-ghost">Clear key</button>
          <button id="kf-key-save" type="button" class="kf-btn kf-btn-primary">Save key</button>
        </div>
        <div id="kf-key-msg" role="status"></div>
      </div>
      <div id="kf-scroll">
        <div id="kf-agent-messages" aria-live="polite"></div>
      </div>
      <button type="button" id="kf-jump" class="kf-icon-btn" aria-label="Jump to latest" hidden>${ICON.down}</button>
      <footer class="kf-composer">
        <div id="kf-agent-input-wrap">
          <textarea id="kf-agent-input" rows="1" placeholder="Ask anything about Kubeflow…" aria-label="Message"></textarea>
          <button type="button" id="kf-agent-send" aria-label="Send message" disabled>${ICON.send}</button>
        </div>
        <div class="kf-composer-meta">
          <span class="kf-context" id="kf-context">${ICON.doc}<span id="kf-page-title"></span></span>
          <span class="kf-disclaimer">AI can make mistakes. Check the sources.</span>
        </div>
      </footer>
    `;
    document.body.appendChild(panel);
  }

  function bindEvents() {
    const panel = $("kf-agent-panel");
    $("kf-close").addEventListener("click", () => toggle(false));
    $("kf-new-chat").addEventListener("click", resetChat);
    $("kf-wide-btn").addEventListener("click", toggleWide);
    $("kf-key-btn").addEventListener("click", () => toggleKeyPanel());
    $("kf-key-save").addEventListener("click", saveKey);
    $("kf-key-clear").addEventListener("click", clearKey);
    $("kf-key-input").addEventListener("keydown", (e) => { if (e.key === "Enter") saveKey(); });
    $("kf-agent-send").addEventListener("click", () => (state.streaming ? stopStreaming() : handleSend()));
    $("kf-jump").addEventListener("click", () => { state.stickToBottom = true; scrollToBottom(true); });

    const input = $("kf-agent-input");
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
        e.preventDefault();
        if (!state.streaming) handleSend();
      }
    });
    input.addEventListener("input", () => {
      autoGrow(input);
      updateSendButton();
    });

    const scroller = $("kf-scroll");
    scroller.addEventListener("scroll", () => {
      const distance = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight;
      state.stickToBottom = distance < 80;
      $("kf-jump").hidden = state.stickToBottom;
    });

    document.addEventListener("keydown", (e) => {
      if ((e.metaKey || e.ctrlKey) && !e.shiftKey && !e.altKey && e.key.toLowerCase() === "i") {
        e.preventDefault();
        toggle();
      } else if (e.key === "Escape" && state.open) {
        if (!$("kf-key-panel").hidden) toggleKeyPanel(false);
        else toggle(false);
      }
    });

    // Resize by dragging the left edge.
    const resizer = $("kf-resizer");
    let resizing = false;
    resizer.addEventListener("mousedown", (e) => {
      resizing = true;
      e.preventDefault();
      panel.classList.add("kf-resizing");
    });
    window.addEventListener("mousemove", (e) => {
      if (!resizing) return;
      const width = Math.min(Math.max(window.innerWidth - e.clientX, 360), Math.min(960, window.innerWidth - 40));
      panel.style.width = width + "px";
    });
    window.addEventListener("mouseup", () => {
      if (!resizing) return;
      resizing = false;
      panel.classList.remove("kf-resizing");
      lsSet(STORE.width, parseInt(panel.style.width, 10) || "");
    });
  }

  function autoGrow(input) {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 180) + "px";
  }

  function updateSendButton() {
    const send = $("kf-agent-send");
    if (state.streaming) {
      send.disabled = false;
      send.innerHTML = ICON.stop;
      send.classList.add("kf-stop");
      send.setAttribute("aria-label", "Stop generating");
      return;
    }
    send.innerHTML = ICON.send;
    send.classList.remove("kf-stop");
    send.setAttribute("aria-label", "Send message");
    send.disabled = !$("kf-agent-input").value.trim();
  }

  // --- Panel ---------------------------------------------------
  function toggle(forceOpen) {
    state.open = forceOpen === undefined ? !state.open : !!forceOpen;
    const panel = $("kf-agent-panel");
    panel.classList.toggle("kf-open", state.open);
    $("kf-agent-btn").classList.toggle("kf-hidden", state.open);
    lsSet(STORE.open, String(state.open));
    if (state.open) {
      $("kf-page-title").textContent = pageTitle();
      $("kf-context").title = "The assistant knows you are reading: " + pageTitle();
      renderAll();
      setTimeout(() => $("kf-agent-input").focus(), 60);
    }
  }

  function toggleWide() {
    const panel = $("kf-agent-panel");
    const wide = !panel.classList.contains("kf-wide");
    panel.classList.toggle("kf-wide", wide);
    $("kf-wide-btn").innerHTML = wide ? ICON.collapse : ICON.expand;
    lsSet(STORE.wide, String(wide));
  }

  function resetChat() {
    stopStreaming();
    state.threadId = null;
    state.messages = [];
    lsRemove(STORE.thread);
    persist();
    renderAll();
    $("kf-agent-input").focus();
  }

  // --- Rendering -----------------------------------------------
  function suggestionList() {
    const title = pageTitle();
    return [
      { icon: ICON.doc, title: "Summarize this page", prompt: 'Summarize the Kubeflow docs page "' + title + '" and list the key steps.' },
      { icon: ICON.rocket, title: "Install Kubeflow", prompt: "How do I install Kubeflow using the manifests?" },
      { icon: ICON.box, title: "Serve a model with KServe", prompt: "How do I deploy a model with KServe?" },
      { icon: ICON.code, title: "Show me a manifest", prompt: "Show me the YAML for the notebook controller mutating webhook." },
    ];
  }

  function renderEmpty(container) {
    const empty = document.createElement("div");
    empty.className = "kf-empty";
    empty.innerHTML = `
      <div class="kf-empty-logo">${ICON.sparkle}</div>
      <h2>How can I help with Kubeflow?</h2>
      <p>Answers come from the official docs and the kubeflow/manifests code, with sources you can check.</p>
      <div class="kf-suggestions"></div>
    `;
    const grid = empty.querySelector(".kf-suggestions");
    suggestionList().forEach((s) => {
      const card = document.createElement("button");
      card.type = "button";
      card.className = "kf-suggestion";
      card.innerHTML = '<span class="kf-suggestion-icon">' + s.icon + "</span><span></span>";
      card.lastChild.textContent = s.title;
      card.addEventListener("click", () => sendMessage(s.prompt));
      grid.appendChild(card);
    });
    container.appendChild(empty);
  }

  function renderAll() {
    const container = $("kf-agent-messages");
    container.innerHTML = "";
    if (!state.messages.length) {
      renderEmpty(container);
      return;
    }
    state.messages.forEach((msg, index) => container.appendChild(renderMessage(msg, index)));
    scrollToBottom(true);
  }

  function renderMessage(msg, index) {
    const row = document.createElement("div");
    row.className = "kf-row kf-" + msg.role;
    row.dataset.index = String(index);
    if (msg.role === "user") {
      const bubble = document.createElement("div");
      bubble.className = "kf-bubble";
      bubble.textContent = msg.content;
      row.appendChild(bubble);
      return row;
    }
    row.innerHTML = `
      <div class="kf-avatar">${ICON.sparkle}</div>
      <div class="kf-content">
        <div class="kf-steps-slot"></div>
        <div class="kf-md"></div>
        <div class="kf-error" hidden></div>
        <div class="kf-sources" hidden></div>
        <div class="kf-actions" hidden></div>
      </div>
    `;
    updateAssistant(row, msg, index);
    return row;
  }

  function stepIcon(step) {
    if (step.state === "active") return '<span class="kf-spinner"></span>';
    return { route: ICON.route, docs: ICON.doc, code: ICON.code, search: ICON.search, write: ICON.pen }[step.kind] || ICON.check;
  }

  function renderSteps(slot, msg, live) {
    slot.innerHTML = "";
    if (!msg.steps || !msg.steps.length) return;
    const list = document.createElement("ol");
    list.className = "kf-step-list";
    msg.steps.forEach((step) => {
      const li = document.createElement("li");
      li.className = "kf-step kf-step-" + step.state;
      li.innerHTML = '<span class="kf-step-icon">' + stepIcon(step) + '</span><span class="kf-step-label"></span>';
      li.lastChild.textContent = step.label;
      list.appendChild(li);
    });
    if (live) {
      slot.appendChild(list);
      return;
    }
    const details = document.createElement("details");
    details.className = "kf-steps";
    const summary = document.createElement("summary");
    const searches = msg.steps.filter((s) => s.kind === "docs" || s.kind === "code" || s.kind === "search").length;
    const sources = (msg.citations || []).length;
    summary.textContent = searches
      ? "Ran " + searches + (searches === 1 ? " search" : " searches") +
        (sources ? " · " + sources + (sources === 1 ? " source" : " sources") : "")
      : "Agent steps";
    details.appendChild(summary);
    details.appendChild(list);
    slot.appendChild(details);
  }

  function renderSources(box, citations) {
    box.innerHTML = "";
    if (!citations || !citations.length) {
      box.hidden = true;
      return;
    }
    box.hidden = false;
    const label = document.createElement("div");
    label.className = "kf-sources-label";
    label.textContent = "Sources";
    box.appendChild(label);
    const grid = document.createElement("div");
    grid.className = "kf-source-grid";
    citations.slice(0, 8).forEach((url, i) => {
      const info = describeSource(url);
      const card = document.createElement("a");
      card.className = "kf-source kf-source-" + info.kind;
      card.href = url;
      card.target = "_blank";
      card.rel = "noopener noreferrer";
      card.title = url;
      card.innerHTML = '<span class="kf-source-num"></span><span class="kf-source-icon">' +
        (info.kind === "code" ? ICON.code : ICON.doc) +
        '</span><span class="kf-source-text"><span class="kf-source-title"></span><span class="kf-source-sub"></span></span>';
      card.querySelector(".kf-source-num").textContent = String(i + 1);
      card.querySelector(".kf-source-title").textContent = info.title;
      card.querySelector(".kf-source-sub").textContent = info.subtitle;
      grid.appendChild(card);
    });
    box.appendChild(grid);
  }

  function renderActions(box, msg, index) {
    box.innerHTML = "";
    const live = state.streaming && index === state.messages.length - 1;
    if (live || (!msg.content && !msg.error)) {
      box.hidden = true;
      return;
    }
    box.hidden = false;
    if (msg.content) {
      const copy = document.createElement("button");
      copy.type = "button";
      copy.className = "kf-action";
      copy.innerHTML = ICON.copy + "<span>Copy</span>";
      copy.addEventListener("click", () => copyText(msg.content, copy));
      box.appendChild(copy);
    }
    if (index === state.messages.length - 1 && !state.streaming) {
      const retry = document.createElement("button");
      retry.type = "button";
      retry.className = "kf-action";
      retry.innerHTML = ICON.retry + "<span>Regenerate</span>";
      retry.addEventListener("click", regenerate);
      box.appendChild(retry);
    }
  }

  function updateAssistant(row, msg, index) {
    const live = state.streaming && index === state.messages.length - 1;
    renderSteps(row.querySelector(".kf-steps-slot"), msg, live && !msg.content);

    const md = row.querySelector(".kf-md");
    if (msg.content) {
      md.innerHTML = renderMarkdown(msg.content);
      enhanceMarkdown(md);
    } else if (!live && !msg.error) {
      md.innerHTML = '<p class="kf-muted">' + (msg.stopped ? "Stopped." : "No answer was returned for this question.") + "</p>";
    } else {
      md.innerHTML = "";
    }
    md.classList.toggle("kf-streaming", live && !!msg.content);
    if (msg.stopped && msg.content) {
      const note = document.createElement("p");
      note.className = "kf-muted";
      note.textContent = "Stopped.";
      md.appendChild(note);
    }

    const error = row.querySelector(".kf-error");
    error.hidden = !msg.error;
    error.textContent = msg.error || "";

    renderSources(row.querySelector(".kf-sources"), live ? [] : msg.citations);
    renderActions(row.querySelector(".kf-actions"), msg, index);
  }

  let frameRequested = false;
  function scheduleUpdate() {
    if (frameRequested) return;
    frameRequested = true;
    requestAnimationFrame(() => {
      frameRequested = false;
      refreshLast();
    });
  }

  function refreshLast() {
    const index = state.messages.length - 1;
    const row = $("kf-agent-messages").querySelector('.kf-row[data-index="' + index + '"]');
    if (row && state.messages[index].role === "assistant") updateAssistant(row, state.messages[index], index);
    scrollToBottom();
  }

  function scrollToBottom(force) {
    const scroller = $("kf-scroll");
    if (force || state.stickToBottom) {
      scroller.scrollTop = scroller.scrollHeight;
      $("kf-jump").hidden = true;
    }
  }

  function persist() {
    const saved = state.messages.slice(-MAX_SAVED_MESSAGES).map((m) => ({
      role: m.role,
      content: m.content,
      citations: m.citations || [],
      steps: (m.steps || []).map((s) => ({ kind: s.kind, label: s.label, state: "done" })),
      error: m.error || "",
      stopped: !!m.stopped,
    }));
    lsSet(STORE.messages, JSON.stringify(saved));
  }

  function restore() {
    lsRemove(STORE.legacyMessages); // old versions stored raw HTML; never re-inject it
    state.threadId = lsGet(STORE.thread);
    try {
      const saved = JSON.parse(lsGet(STORE.messages) || "[]");
      state.messages = Array.isArray(saved)
        ? saved.filter((m) => m && (m.role === "user" || m.role === "assistant") && typeof m.content === "string")
        : [];
    } catch (e) {
      state.messages = [];
    }
    const width = parseInt(lsGet(STORE.width), 10);
    if (width) $("kf-agent-panel").style.width = width + "px";
    if (lsGet(STORE.wide) === "true") toggleWide();
  }

  // --- Agent steps from SSE events -----------------------------
  const TOOL_LABELS = {
    search_kubeflow_docs: { kind: "docs", label: "Searched the documentation" },
    search_kubeflow_code: { kind: "code", label: "Searched manifests and code" },
    search_kubeflow_context: { kind: "search", label: "Searched docs and code" },
  };
  const ROUTE_LABELS = {
    docs: "Routed to documentation",
    code: "Routed to manifests and code",
    hybrid: "Routed to docs and code",
  };

  function setActiveStep(msg, kind, label) {
    msg.steps = (msg.steps || []).filter((s) => s.state !== "active");
    msg.steps.push({ kind: kind, label: label, state: "active" });
  }

  function completeSteps(msg) {
    msg.steps = (msg.steps || []).filter((s) => s.state !== "active");
  }

  function handleEvent(msg, data) {
    switch (data.type) {
      case "thread":
        if (data.thread_id) {
          state.threadId = data.thread_id;
          lsSet(STORE.thread, state.threadId);
        }
        completeSteps(msg);
        if (data.route) msg.steps.push({ kind: "route", label: ROUTE_LABELS[data.route] || "Routed: " + data.route, state: "done" });
        setActiveStep(msg, "search", "Searching Kubeflow knowledge…");
        break;
      case "tool_result": {
        const tool = TOOL_LABELS[data.tool_name] || { kind: "search", label: "Ran " + (data.tool_name || "tool") };
        const hits = ((data.content || "").match(/^\[(DOCS|CODE)\]/gm) || []).length;
        completeSteps(msg);
        msg.steps.push({ kind: tool.kind, label: tool.label + (hits ? " · " + hits + " results" : ""), state: "done" });
        setActiveStep(msg, "write", "Writing the answer…");
        break;
      }
      case "content":
        if (!msg.content) completeSteps(msg);
        msg.content += data.content || "";
        break;
      case "citations":
        msg.citations = Array.from(new Set((msg.citations || []).concat(data.citations || [])));
        break;
      case "error":
        completeSteps(msg);
        msg.error = data.content || "Something went wrong.";
        if (data.status === 401 || data.status === 403) toggleKeyPanel(true);
        break;
      default:
        break;
    }
  }

  // --- Sending -------------------------------------------------
  function handleSend() {
    const input = $("kf-agent-input");
    const text = input.value.trim();
    if (!text || state.streaming) return;
    input.value = "";
    autoGrow(input);
    sendMessage(text);
  }

  function regenerate() {
    if (state.streaming) return;
    let lastUser = -1;
    for (let i = state.messages.length - 1; i >= 0; i--) {
      if (state.messages[i].role === "user") { lastUser = i; break; }
    }
    if (lastUser < 0) return;
    const text = state.messages[lastUser].content;
    state.messages = state.messages.slice(0, lastUser);
    sendMessage(text);
  }

  function stopStreaming() {
    if (state.controller) state.controller.abort();
  }

  async function sendMessage(text) {
    if (state.streaming) return;
    if (!state.open) toggle(true);

    const msg = { role: "assistant", content: "", citations: [], steps: [], error: "", stopped: false };
    state.messages.push({ role: "user", content: text });
    state.messages.push(msg);
    setActiveStep(msg, "route", "Understanding the question…");
    state.streaming = true;
    state.stickToBottom = true;
    state.controller = new AbortController();
    updateSendButton();
    renderAll();

    try {
      const response = await fetch(API_URL, {
        method: "POST",
        headers: requestHeaders(),
        signal: state.controller.signal,
        body: JSON.stringify({
          message: text,
          stream: true,
          thread_id: state.threadId,
          context: { url: window.location.href, title: pageTitle(), path: window.location.pathname },
        }),
      });

      if (!response.ok) {
        let detail = "";
        try { detail = (await response.json()).detail || ""; } catch (e) { /* non-JSON error */ }
        if (response.status === 401 || response.status === 400) toggleKeyPanel(true);
        completeSteps(msg);
        msg.error = detail || "The assistant returned HTTP " + response.status + ".";
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let sseBuffer = "";
      for (;;) {
        const result = await reader.read();
        if (result.done) break;
        // SSE events can be split across network chunks: keep the trailing
        // partial line buffered until the next chunk completes it.
        sseBuffer += decoder.decode(result.value, { stream: true });
        const lines = sseBuffer.split("\n");
        sseBuffer = lines.pop();
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          let data;
          try { data = JSON.parse(line.slice(6)); } catch (e) { continue; }
          handleEvent(msg, data);
          scheduleUpdate();
        }
      }
    } catch (err) {
      completeSteps(msg);
      if (err && err.name === "AbortError") {
        msg.stopped = true;
      } else {
        console.error("Kubeflow agent error:", err);
        msg.error = "Couldn't reach the assistant API (" + API_URL + "). Is it running?";
      }
    } finally {
      completeSteps(msg);
      state.streaming = false;
      state.controller = null;
      updateSendButton();
      persist();
      refreshLast();
    }
  }

  // --- Bring-your-own LLM API key ------------------------------
  function requestHeaders() {
    const headers = { "Content-Type": "application/json" };
    const key = readSession(KEY_STORE);
    const model = readSession(MODEL_STORE);
    if (key) {
      headers["X-LLM-API-Key"] = key;
      if (model) headers["X-LLM-Model"] = model;
    }
    return headers;
  }

  function updateKeyStatus() {
    const status = $("kf-status");
    const hasKey = !!readSession(KEY_STORE);
    const needsKey = !!(state.serverConfig && state.serverConfig.require_client_api_key && !hasKey);
    status.textContent = hasKey
      ? "Docs + manifests · Using your API key"
      : needsKey ? "API key required · click the key icon" : "Docs + manifests · Online";
    status.classList.toggle("kf-status-warn", needsKey);
    status.classList.toggle("kf-status-key", hasKey);
    $("kf-key-btn").classList.toggle("kf-key-active", hasKey);
  }

  function setKeyMessage(text) {
    $("kf-key-msg").textContent = text;
  }

  function toggleKeyPanel(forceOpen) {
    const keyPanel = $("kf-key-panel");
    const open = forceOpen !== undefined ? forceOpen : keyPanel.hidden;
    keyPanel.hidden = !open;
    $("kf-key-btn").classList.toggle("kf-pressed", open);
    if (open) {
      $("kf-key-input").value = readSession(KEY_STORE);
      $("kf-model-input").value = readSession(MODEL_STORE);
      setKeyMessage("");
      $("kf-key-input").focus();
    }
  }

  function saveKey() {
    const key = $("kf-key-input").value.trim();
    const model = $("kf-model-input").value.trim();
    if (!key) {
      setKeyMessage("Paste a key first, or use Clear key to go back to the server default.");
      return;
    }
    writeSession(KEY_STORE, key);
    writeSession(MODEL_STORE, model);
    updateKeyStatus();
    setKeyMessage("Saved for this tab.");
    setTimeout(() => toggleKeyPanel(false), 700);
  }

  function clearKey() {
    writeSession(KEY_STORE, "");
    writeSession(MODEL_STORE, "");
    $("kf-key-input").value = "";
    $("kf-model-input").value = "";
    updateKeyStatus();
    setKeyMessage("Key cleared from this browser.");
  }

  async function loadServerConfig() {
    try {
      const response = await fetch(CONFIG_URL);
      if (!response.ok) return;
      state.serverConfig = await response.json();
    } catch (e) {
      return; // older API without /config: keep the key option available
    }
    if (!state.serverConfig.allow_client_api_keys) $("kf-key-btn").style.display = "none";
    let help = "Your key is kept only in this browser tab (sessionStorage, cleared when the tab closes) and is sent only to this assistant's API with your questions.";
    if (state.serverConfig.llm_provider_host) {
      help = "Use a key for " + state.serverConfig.llm_provider_host +
        (state.serverConfig.model ? " (default model: " + state.serverConfig.model + ")" : "") + ". " + help;
    }
    $("kf-key-help").textContent = help;
    if (state.serverConfig.model) $("kf-model-input").placeholder = state.serverConfig.model;
    updateKeyStatus();
  }

  // --- Init ----------------------------------------------------
  function init() {
    buildDom();
    bindEvents();
    restore();
    updateKeyStatus();
    updateSendButton();
    if (lsGet(STORE.open) === "true") toggle(true);
    loadServerConfig();
  }

  function loadScript(src) {
    return new Promise((resolve) => {
      const script = document.createElement("script");
      script.src = src;
      script.async = true;
      script.onload = resolve;
      script.onerror = resolve; // fall back to escaped plain text
      document.head.appendChild(script);
    });
  }

  function start() {
    const deps = [];
    if (!window.marked) deps.push(loadScript(MARKED_CDN));
    if (!window.DOMPurify) deps.push(loadScript(PURIFY_CDN));
    Promise.all(deps).then(() => {
      init();
      if (state.open) renderAll();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
