const STORAGE_KEY = "kubeflow-docs-rag-threads";

const threadList = document.getElementById("thread-list");
const newThreadButton = document.getElementById("new-thread-button");
const messageList = document.getElementById("message-list");
const emptyState = document.getElementById("empty-state");
const composerForm = document.getElementById("composer-form");
const messageInput = document.getElementById("message-input");
const sendButton = document.getElementById("send-button");
const providerBadge = document.getElementById("provider-badge");
const collectionChip = document.getElementById("collection-chip");
const messageTemplate = document.getElementById("message-template");

let threads = loadThreads();
let activeThreadId = threads[0]?.id ?? null;

function uid() {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function loadThreads() {
  const raw = window.localStorage.getItem(STORAGE_KEY);
  if (!raw) {
    return [createThread("New Thread")];
  }

  try {
    const parsed = JSON.parse(raw);
    return parsed.length ? parsed : [createThread("New Thread")];
  } catch {
    return [createThread("New Thread")];
  }
}

function saveThreads() {
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(threads));
}

function createThread(title) {
  return {
    id: uid(),
    title,
    messages: [],
  };
}

function activeThread() {
  return threads.find((thread) => thread.id === activeThreadId);
}

function setActiveThread(threadId) {
  activeThreadId = threadId;
  renderThreads();
  renderMessages();
}

function renderThreads() {
  threadList.innerHTML = "";
  for (const thread of threads) {
    const button = document.createElement("button");
    button.className = `thread-item${thread.id === activeThreadId ? " active" : ""}`;
    button.type = "button";

    const title = document.createElement("span");
    title.className = "thread-title";
    title.textContent = thread.title;

    const preview = document.createElement("span");
    preview.className = "thread-preview";
    preview.textContent = thread.messages.at(-1)?.content.slice(0, 72) || "No messages yet";

    button.append(title, preview);
    button.addEventListener("click", () => setActiveThread(thread.id));
    threadList.appendChild(button);
  }
}

function renderMessages() {
  const thread = activeThread();
  const messages = thread?.messages ?? [];

  emptyState.classList.toggle("hidden", messages.length > 0);
  messageList.innerHTML = "";

  for (const message of messages) {
    const fragment = messageTemplate.content.cloneNode(true);
    const article = fragment.querySelector(".message");
    const role = fragment.querySelector(".message-role");
    const bubble = fragment.querySelector(".message-bubble");
    const sources = fragment.querySelector(".message-sources");

    article.classList.add(message.role);
    role.textContent = message.role === "user" ? "You" : "Assistant";
    bubble.textContent = message.content;

    if (message.citations?.length) {
      for (const citation of message.citations) {
        const chip = document.createElement("div");
        chip.className = "source-chip";
        chip.textContent = citation;
        sources.appendChild(chip);
      }
    }

    messageList.appendChild(fragment);
  }

  messageList.scrollTop = messageList.scrollHeight;
}

function updateThreadTitle(thread, fallback) {
  if (thread.messages.length === 1 && thread.messages[0].role === "user") {
    thread.title = thread.messages[0].content.slice(0, 36) || fallback;
  }
}

function setComposerBusy(isBusy) {
  messageInput.disabled = isBusy;
  sendButton.disabled = isBusy;
  sendButton.textContent = isBusy ? "Thinking..." : "Send";
}

async function fetchConfig() {
  try {
    const response = await fetch("/config");
    const data = await response.json();
    providerBadge.textContent = data.llm_configured
      ? `${data.provider}: ${data.model || "configured"}`
      : "Retrieval-only mode";
    collectionChip.textContent = data.collection;
  } catch {
    providerBadge.textContent = "Config unavailable";
    collectionChip.textContent = "Collection unknown";
  }
}

async function sendMessage(promptText) {
  const thread = activeThread();
  if (!thread) {
    return;
  }

  const message = promptText.trim();
  if (!message) {
    return;
  }

  const history = thread.messages.map(({ role, content }) => ({ role, content }));
  thread.messages.push({ role: "user", content: message });
  updateThreadTitle(thread, "New Thread");
  saveThreads();
  renderThreads();
  renderMessages();

  messageInput.value = "";
  setComposerBusy(true);

  try {
    const response = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        history,
        top_k: 4,
        max_tokens: 512,
      }),
    });

    if (!response.ok) {
      throw new Error(`Request failed with ${response.status}`);
    }

    const data = await response.json();
    thread.messages.push({
      role: "assistant",
      content: data.answer,
      citations: data.citations || [],
    });
    saveThreads();
    renderThreads();
    renderMessages();
  } catch (error) {
    thread.messages.push({
      role: "assistant",
      content: `Request failed: ${error.message}`,
      citations: [],
    });
    saveThreads();
    renderThreads();
    renderMessages();
  } finally {
    setComposerBusy(false);
    messageInput.focus();
  }
}

newThreadButton.addEventListener("click", () => {
  const thread = createThread("New Thread");
  threads.unshift(thread);
  saveThreads();
  setActiveThread(thread.id);
});

composerForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  await sendMessage(messageInput.value);
});

messageInput.addEventListener("keydown", async (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    await sendMessage(messageInput.value);
  }
});

for (const card of document.querySelectorAll(".starter-card")) {
  card.addEventListener("click", async () => {
    await sendMessage(card.dataset.prompt || "");
  });
}

renderThreads();
renderMessages();
fetchConfig();
