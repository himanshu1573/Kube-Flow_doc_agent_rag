/* ============================================================
   Kubeflow Docs Agent — Chat Widget (Vanilla JS)
   Connects to the agent FastAPI backend (server-https) via SSE streaming.
   ============================================================ */
(function () {
  "use strict";

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
  const MARKED_CDN = "https://cdn.jsdelivr.net/npm/marked/marked.min.js";

  // ── State ───────────────────────────────────────────────────
  let isOpen = false;
  let threadId = null;

  // ── SVG Icons ───────────────────────────────────────────────
  const ICON = {
    chat: '<svg viewBox="0 0 24 24"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>',
    close: '<svg viewBox="0 0 24 24"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>',
    bot: '<svg viewBox="0 0 24 24"><path d="M12 8V4H8"/><rect width="16" height="12" x="4" y="8" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/></svg>',
    user: '<svg viewBox="0 0 24 24"><path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>',
    sparkle: '<svg viewBox="0 0 24 24"><path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z"/></svg>',
    send: '<svg viewBox="0 0 24 24"><path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/></svg>',
    plus: '<svg viewBox="0 0 24 24"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>',
    key: '<svg viewBox="0 0 24 24"><circle cx="7.5" cy="15.5" r="5.5"/><path d="m21 2-9.6 9.6"/><path d="m15.5 7.5 3 3L22 7l-3-3"/></svg>',
  };

  // --- Build DOM -------------------------------------------------
  function init() {
    // Floating button
    const btn = document.createElement("button");
    btn.id = "kf-agent-btn";
    btn.innerHTML = ICON.chat;
    btn.setAttribute("aria-label", "Open AI Assistant");
    btn.addEventListener("click", () => toggle());
    document.body.appendChild(btn);

    // Side panel
    const panel = document.createElement("div");
    panel.id = "kf-agent-panel";
    panel.innerHTML = `
      <div id="kf-resizer"></div>
      <div class="panel-header">
        <div class="header-left">
          <div class="header-icon">${ICON.bot}</div>
          <div>
            <div class="header-title">AI Assistant</div>
            <div class="header-status">● Online</div>
          </div>
        </div>
        <div class="header-actions">
          <button id="kf-key-btn" aria-label="LLM API key settings" title="Use your own LLM API key">${ICON.key}</button>
          <button id="kf-new-chat" aria-label="New chat">${ICON.plus}</button>
          <button id="kf-close" aria-label="Close panel">${ICON.close}</button>
        </div>
      </div>
      <div id="kf-context-status">
        <span>AI has context of:</span>
        <div class="kf-context-badge">
          <span id="kf-page-title">Current Documentation</span>
        </div>
      </div>
      <div id="kf-key-panel" hidden>
        <div class="kf-key-title">Use your own LLM API key</div>
        <p class="kf-key-help" id="kf-key-help">Your key is kept only in this browser tab (sessionStorage, cleared when the tab closes) and is sent only to this assistant's API with your questions.</p>
        <label for="kf-key-input">API key</label>
        <input id="kf-key-input" type="password" autocomplete="off" spellcheck="false" placeholder="Paste your key">
        <label for="kf-model-input">Model (optional)</label>
        <input id="kf-model-input" type="text" autocomplete="off" spellcheck="false" placeholder="Server default">
        <div class="kf-key-actions">
          <button id="kf-key-save" type="button">Save key</button>
          <button id="kf-key-clear" type="button">Clear key</button>
        </div>
        <div id="kf-key-msg" role="status"></div>
      </div>
      <div id="kf-agent-messages">
        <div class="kf-welcome">
          <div class="welcome-icon">${ICON.sparkle}</div>
          <h3>Kubeflow Docs Agent</h3>
          <p>Ask anything about Kubeflow — installation, pipelines, KServe, troubleshooting, and more.</p>
          <div class="kf-suggestions">
            <button data-q="How do I install Kubeflow?">Install Kubeflow</button>
            <button data-q="What is KServe?">What is KServe?</button>
            <button data-q="How to create a Kubeflow Pipeline?">Pipelines</button>
            <button data-q="How to use Kubeflow Notebooks?">Notebooks</button>
          </div>
        </div>
      </div>
      <div id="kf-agent-input-area">
        <div id="kf-agent-input-wrap">
          <textarea id="kf-agent-input" rows="1" placeholder="Ask a question..."></textarea>
          <button id="kf-agent-send">${ICON.send}</button>
        </div>
        <div class="kf-footer-text">GSoC 2026 · Kubeflow Docs Agent · Powered by Milvus, Groq, and Architecture B</div>
      </div>
    `;
    document.body.appendChild(panel);

    // RESTORE SESSION
    threadId = localStorage.getItem("kf-thread-id");
    const savedMsgs = localStorage.getItem("kf-messages");
    if (savedMsgs) {
      document.getElementById("kf-agent-messages").innerHTML = savedMsgs;
    }

    const wasOpen = localStorage.getItem("kf-panel-open") === "true";
    if (wasOpen) {
      toggle(true);
    }

    const savedWidth = localStorage.getItem("kf-panel-width");
    if (savedWidth) {
      panel.style.width = savedWidth + "px";
    }

    // RESIZE LOGIC
    const resizer = document.getElementById("kf-resizer");
    let isResizing = false;

    resizer.addEventListener("mousedown", (e) => {
      isResizing = true;
      resizer.classList.add("dragging");
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
    });

    window.addEventListener("mousemove", (e) => {
      if (!isResizing) return;
      const newWidth = window.innerWidth - e.clientX;
      if (newWidth > 320 && newWidth < 800) {
        panel.style.width = newWidth + "px";
        localStorage.setItem("kf-panel-width", newWidth);
      }
    });

    window.addEventListener("mouseup", () => {
      isResizing = false;
      resizer.classList.remove("dragging");
      document.body.style.cursor = "default";
      document.body.style.userSelect = "auto";
    });

    // Event listeners
    document.getElementById("kf-close").addEventListener("click", () => toggle());
    document.getElementById("kf-new-chat").addEventListener("click", resetChat);
    document.getElementById("kf-key-btn").addEventListener("click", () => toggleKeyPanel());
    document.getElementById("kf-key-save").addEventListener("click", saveKey);
    document.getElementById("kf-key-clear").addEventListener("click", clearKey);
    document.getElementById("kf-key-input").addEventListener("keydown", function (e) {
      if (e.key === "Enter") saveKey();
    });
    document.getElementById("kf-agent-send").addEventListener("click", handleSend);

    const input = document.getElementById("kf-agent-input");
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    });
    // Auto-resize textarea
    input.addEventListener("input", function () {
      this.style.height = "auto";
      this.style.height = Math.min(this.scrollHeight, 120) + "px";
    });

    bindSuggestions();
    updateKeyStatus();
    loadServerConfig();
  }

  // ── Bring-your-own LLM API key ──────────────────────────────
  // Stored in sessionStorage so it disappears when the tab closes, and sent
  // only to API_URL as the X-LLM-API-Key header (never in the body or URL).
  const KEY_STORE = "kf-llm-api-key";
  const MODEL_STORE = "kf-llm-model";
  let serverConfig = null;

  function readSession(name) {
    try { return sessionStorage.getItem(name) || ""; } catch (e) { return ""; }
  }

  function writeSession(name, value) {
    try {
      if (value) sessionStorage.setItem(name, value);
      else sessionStorage.removeItem(name);
    } catch (e) { /* storage unavailable: key lives only for this request */ }
  }

  function requestHeaders() {
    var headers = { "Content-Type": "application/json" };
    var key = readSession(KEY_STORE);
    var model = readSession(MODEL_STORE);
    if (key) {
      headers["X-LLM-API-Key"] = key;
      if (model) headers["X-LLM-Model"] = model;
    }
    return headers;
  }

  function updateKeyStatus() {
    var status = document.querySelector("#kf-agent-panel .header-status");
    var hasKey = !!readSession(KEY_STORE);
    var needsKey = !!(serverConfig && serverConfig.require_client_api_key && !hasKey);
    status.textContent = hasKey ? "● Using your API key" : needsKey ? "● API key required" : "● Online";
    status.classList.toggle("kf-status-warn", needsKey);
    document.getElementById("kf-key-btn").classList.toggle("kf-key-active", hasKey);
  }

  function setKeyMessage(text) {
    document.getElementById("kf-key-msg").textContent = text;
  }

  function toggleKeyPanel(forceOpen) {
    var keyPanel = document.getElementById("kf-key-panel");
    var open = forceOpen !== undefined ? forceOpen : keyPanel.hidden;
    keyPanel.hidden = !open;
    if (open) {
      document.getElementById("kf-key-input").value = readSession(KEY_STORE);
      document.getElementById("kf-model-input").value = readSession(MODEL_STORE);
      setKeyMessage("");
      document.getElementById("kf-key-input").focus();
    }
  }

  function saveKey() {
    var key = document.getElementById("kf-key-input").value.trim();
    var model = document.getElementById("kf-model-input").value.trim();
    if (!key) {
      setKeyMessage("Paste a key first, or use Clear key to go back to the server default.");
      return;
    }
    writeSession(KEY_STORE, key);
    writeSession(MODEL_STORE, model);
    updateKeyStatus();
    setKeyMessage("Saved for this tab.");
    setTimeout(function () { toggleKeyPanel(false); }, 700);
  }

  function clearKey() {
    writeSession(KEY_STORE, "");
    writeSession(MODEL_STORE, "");
    document.getElementById("kf-key-input").value = "";
    document.getElementById("kf-model-input").value = "";
    updateKeyStatus();
    setKeyMessage("Key cleared from this browser.");
  }

  async function loadServerConfig() {
    try {
      var response = await fetch(CONFIG_URL);
      if (!response.ok) return;
      serverConfig = await response.json();
    } catch (e) {
      return; // older API without /config: keep the key option available
    }
    if (!serverConfig.allow_client_api_keys) {
      document.getElementById("kf-key-btn").style.display = "none";
    }
    var help = "Your key is kept only in this browser tab (sessionStorage, cleared when the tab closes) and is sent only to this assistant's API with your questions.";
    if (serverConfig.llm_provider_host) {
      help = "Use a key for " + serverConfig.llm_provider_host +
        (serverConfig.model ? " (default model: " + serverConfig.model + ")" : "") + ". " + help;
    }
    document.getElementById("kf-key-help").textContent = help;
    updateKeyStatus();
  }

  function bindSuggestions() {
    document.getElementById("kf-agent-panel").querySelectorAll(".kf-suggestions button").forEach(function (btn) {
      btn.addEventListener("click", function () {
        sendMessage(this.getAttribute("data-q"));
      });
    });
  }

  // --- Toggle Panel ----------------------------------------------
  function toggle(forceOpen) {
    if (forceOpen !== undefined) isOpen = !forceOpen;
    isOpen = !isOpen;
    var panel = document.getElementById("kf-agent-panel");
    var btn = document.getElementById("kf-agent-btn");

    if (isOpen) {
      panel.classList.add("open");
      btn.style.display = "none"; // Hide button to prevent collision

      // Update context hint
      const title = document.querySelector('h1')?.innerText || document.title;
      document.getElementById("kf-page-title").textContent = title;

      document.getElementById("kf-agent-input").focus();
      localStorage.setItem("kf-panel-open", "true");
    } else {
      panel.classList.remove("open");
      btn.style.display = "flex"; // Show button again
      localStorage.setItem("kf-panel-open", "false");
    }
  }

  // ── Reset Chat ──────────────────────────────────────────────
  function resetChat() {
    threadId = null;
    localStorage.removeItem("kf-thread-id");
    localStorage.removeItem("kf-messages");

    var msgs = document.getElementById("kf-agent-messages");
    msgs.innerHTML = `
      <div class="kf-welcome">
        <div class="welcome-icon">${ICON.sparkle}</div>
        <h3>Kubeflow Docs Agent</h3>
        <p>Ask anything about Kubeflow — installation, pipelines, KServe, troubleshooting, and more.</p>
        <div class="kf-suggestions">
          <button data-q="How do I install Kubeflow?">Install Kubeflow</button>
          <button data-q="What is KServe?">What is KServe?</button>
          <button data-q="How to create a Kubeflow Pipeline?">Pipelines</button>
          <button data-q="How to use Kubeflow Notebooks?">Notebooks</button>
        </div>
      </div>
    `;
    bindSuggestions();
  }

  // ── Handle Send ─────────────────────────────────────────────
  function handleSend() {
    var input = document.getElementById("kf-agent-input");
    var text = input.value.trim();
    if (!text) return;
    input.value = "";
    input.style.height = "auto";
    sendMessage(text);
  }

  // --- Send Message -----------------------------------------------------------
  async function sendMessage(text) {
    var msgs = document.getElementById("kf-agent-messages");

    // Capture Page Context (Where is the user right now?)
    const pageContext = {
      url: window.location.href,
      title: document.querySelector('h1')?.innerText || document.title,
      path: window.location.pathname
    };

    // Clear welcome screen if present
    var welcome = msgs.querySelector(".kf-welcome");
    if (welcome) welcome.remove();

    // Add user message
    appendMessage("user", text);

    // Add thinking indicator
    var thinkEl = document.createElement("div");
    thinkEl.className = "kf-msg assistant";
    thinkEl.id = "kf-thinking";
    thinkEl.innerHTML = `
      <div class="kf-avatar">${ICON.bot}</div>
      <div class="kf-body">
        <div class="kf-label">Kubeflow Agent</div>
        <div class="kf-thinking"><span></span><span></span><span></span></div>
      </div>
    `;
    msgs.appendChild(thinkEl);
    scrollToBottom();

    try {
      var response = await fetch(API_URL, {
        method: "POST",
        headers: requestHeaders(),
        body: JSON.stringify({
          message: text,
          stream: true,
          thread_id: threadId,
          context: pageContext  // <--- The AI now knows where you are!
        }),
      });

      if (!response.ok) {
        var detail = "";
        try { detail = (await response.json()).detail || ""; } catch (e) { /* non-JSON error */ }
        if (response.status === 401 || response.status === 400) toggleKeyPanel(true);
        var httpError = new Error(detail || "HTTP " + response.status);
        httpError.userMessage = detail || "The assistant returned HTTP " + response.status + ".";
        throw httpError;
      }

      // Remove thinking indicator
      var thinking = document.getElementById("kf-thinking");
      if (thinking) thinking.remove();

      // Create assistant message element
      var msgEl = document.createElement("div");
      msgEl.className = "kf-msg assistant";
      var bodyEl = document.createElement("div");
      bodyEl.className = "kf-body";
      var labelEl = document.createElement("div");
      labelEl.className = "kf-label";
      labelEl.textContent = "Kubeflow Agent";
      var textEl = document.createElement("div");
      textEl.className = "kf-text";
      textEl.textContent = "";
      var avatarEl = document.createElement("div");
      avatarEl.className = "kf-avatar";
      avatarEl.innerHTML = ICON.bot;

      bodyEl.appendChild(labelEl);
      bodyEl.appendChild(textEl);
      msgEl.appendChild(avatarEl);
      msgEl.appendChild(bodyEl);
      msgs.appendChild(msgEl);

      // Stream response
      var reader = response.body.getReader();
      var decoder = new TextDecoder();
      var sseBuffer = "";
      var content = "";
      var citations = [];
      var sawError = false;

      while (true) {
        var result = await reader.read();
        if (result.done) {
          // Final safety check: if content is still empty, let the user know
          if (!content && !citations.length && !sawError) {
            textEl.textContent = "The agent couldn't find a specific answer for this query in the documentation.";
            textEl.style.fontStyle = "italic";
            textEl.style.opacity = "0.7";
          }
          break;
        }

        // SSE events can be split across network chunks: keep the trailing
        // partial line buffered until the next chunk completes it.
        sseBuffer += decoder.decode(result.value, { stream: true });
        var lines = sseBuffer.split("\n");
        sseBuffer = lines.pop();

        for (var i = 0; i < lines.length; i++) {
          var line = lines[i];
          if (!line.startsWith("data: ")) continue;
          try {
            var data = JSON.parse(line.slice(6));

            if (data.type === "thread" && data.thread_id) {
              threadId = data.thread_id;
              localStorage.setItem("kf-thread-id", threadId);
            } else if (data.type === "content") {
              content += data.content;
              // Use marked if available, otherwise fallback to textContent
              if (window.marked) {
                textEl.innerHTML = window.marked.parse(content);
              } else {
                textEl.textContent = content;
              }
              scrollToBottom();
            } else if (data.type === "citations") {
              citations = data.citations || [];
            } else if (data.type === "error") {
              sawError = true;
              if (data.status === 401 || data.status === 403) toggleKeyPanel(true);
              const errorText = content + " **[Error: " + data.content + "]**";
              if (window.marked) {
                textEl.innerHTML = window.marked.parse(errorText);
              } else {
                textEl.innerHTML = escapeHtml(errorText);
              }
              textEl.style.color = "#ef4444";
              scrollToBottom();
            }
          } catch (e) { }
        }
      }

      // Render citations
      if (citations.length > 0) {
        var citEl = document.createElement("div");
        citEl.className = "kf-citations";
        citEl.innerHTML = '<div class="cit-label">📚 Sources</div>';
        var seen = {};
        for (var c = 0; c < citations.length; c++) {
          if (seen[citations[c]]) continue;
          seen[citations[c]] = true;
          var a = document.createElement("a");
          a.href = citations[c];
          a.target = "_blank";
          a.rel = "noopener";
          a.textContent = citations[c];
          citEl.appendChild(a);
        }
        bodyEl.appendChild(citEl);
      }

      scrollToBottom();
      localStorage.setItem("kf-messages", msgs.innerHTML);
    } catch (err) {
      console.error("Agent error:", err);
      var thinkingEl = document.getElementById("kf-thinking");
      if (thinkingEl) thinkingEl.remove();
      appendMessage("assistant", err.userMessage || "Sorry, I couldn't connect to the backend. Is the API server running?");
    }
  }

  // --- Helpers -------------------------------------------------
  function appendMessage(role, text) {
    var msgs = document.getElementById("kf-agent-messages");
    var el = document.createElement("div");
    el.className = "kf-msg " + role;
    const bodyContent = (role === "assistant" && window.marked) 
      ? window.marked.parse(text) 
      : escapeHtml(text).replace(/\n/g, '<br>');

    el.innerHTML = `
      <div class="kf-avatar">${role === "user" ? ICON.user : ICON.bot}</div>
      <div class="kf-body">
        <div class="kf-label">${role === "user" ? "You" : "Kubeflow Agent"}</div>
        <div class="kf-text">${bodyContent}</div>
      </div>
    `;
    msgs.appendChild(el);
    scrollToBottom();
    localStorage.setItem("kf-messages", msgs.innerHTML);
  }

  function scrollToBottom() {
    var msgs = document.getElementById("kf-agent-messages");
    msgs.scrollTop = msgs.scrollHeight;
  }

  function escapeHtml(str) {
    var div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  // ── Init on DOM Ready ───────────────────────────────────────
  function loadMarked(callback) {
    if (window.marked) {
      callback();
      return;
    }
    const script = document.createElement("script");
    script.src = MARKED_CDN;
    script.onload = callback;
    document.head.appendChild(script);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => loadMarked(init));
  } else {
    loadMarked(init);
  }
})();
