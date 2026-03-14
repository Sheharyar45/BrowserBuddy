type WebPageContext = {
  url: string;
  title: string;
  text: string;
  images: string[];
};

type AgentResponse = {
  session_id?: string;
  received_context?: {
    url?: string;
    title?: string;
    text_chars?: number;
    text_preview?: string;
    image_count?: number;
    images_preview?: string[];
  };
  stored_context_check?: {
    has_text?: boolean;
    stored_text_chars?: number;
    has_images?: boolean;
    stored_image_count?: number;
  };
  response: string;
};

type StoredContextResponse = {
  session_id: string;
  context: WebPageContext;
};

const app = document.getElementById("app");
const hasChromeRuntime =
  typeof chrome !== "undefined" &&
  typeof chrome.runtime !== "undefined" &&
  typeof chrome.tabs !== "undefined";

if (!app) {
  throw new Error("Popup root element not found");
}

app.innerHTML = `
  <div style="display:flex;flex-direction:column;height:100%;padding:12px;gap:10px;">
    <div style="display:flex;justify-content:space-between;align-items:center;">
      <h2 style="margin:0;font-size:16px;color:#0b3a66;letter-spacing:0.2px;">BrowserBuddy</h2>
      <span id="mode" style="font-size:11px;padding:4px 10px;border-radius:999px;background:#dbeeff;color:#0b3a66;border:1px solid #b9defd;box-shadow:0 2px 8px rgba(59,130,246,0.12);">
        ${hasChromeRuntime ? "Extension" : "Preview"}
      </span>
    </div>
    <div id="chat" style="flex:1;overflow:auto;background:#ffffff;border:1px solid #cfe6ff;border-radius:12px;padding:10px;font-size:12px;color:#0f172a;box-shadow:0 8px 24px rgba(59,130,246,0.08);"></div>
    <textarea id="prompt" placeholder="Ask about this page..." style="resize:none;height:70px;border-radius:10px;border:1px solid #b9defd;background:#ffffff;color:#0f172a;padding:10px;outline:none;box-shadow:inset 0 1px 2px rgba(15,23,42,0.04);"></textarea>
    <button id="send" style="height:38px;border:1px solid #7fc0ff;border-radius:10px;background:linear-gradient(180deg,#7fc0ff 0%,#58aefc 100%);color:#ffffff;font-weight:700;cursor:pointer;box-shadow:0 6px 16px rgba(56,139,246,0.25);">Send</button>
    <button id="viewContext" style="height:34px;border:1px solid #b9defd;border-radius:10px;background:#ffffff;color:#0b3a66;font-weight:600;cursor:pointer;">View Stored Context</button>
  </div>
`;

const chatEl = document.getElementById("chat") as HTMLDivElement;
const promptEl = document.getElementById("prompt") as HTMLTextAreaElement;
const sendBtn = document.getElementById("send") as HTMLButtonElement;
const viewContextBtn = document.getElementById("viewContext") as HTMLButtonElement;
let lastSessionId: string | null = null;

function appendMessage(sender: "User" | "Agent", text: string): void {
  const line = document.createElement("div");
  line.style.marginBottom = "10px";
  line.style.padding = "9px";
  line.style.borderRadius = "10px";
  line.style.border = sender === "User" ? "1px solid #9dd0ff" : "1px solid #d7ebff";
  line.style.background = sender === "User" ? "#eaf5ff" : "#ffffff";
  line.style.color = "#0f172a";
  line.style.boxShadow = "0 3px 10px rgba(59,130,246,0.08)";
  line.innerHTML = `<strong>${sender}:</strong> ${text}`;
  chatEl.appendChild(line);
  chatEl.scrollTop = chatEl.scrollHeight;
}

function appendContextDebug(result: AgentResponse): void {
  if (!result.stored_context_check && !result.received_context) {
    return;
  }

  const block = document.createElement("div");
  block.style.marginBottom = "10px";
  block.style.padding = "9px";
  block.style.borderRadius = "10px";
  block.style.border = "1px dashed #93c5fd";
  block.style.background = "#f8fbff";
  block.style.color = "#0f172a";
  block.style.whiteSpace = "pre-wrap";

  const received = result.received_context || {};
  const stored = result.stored_context_check || {};

  block.innerHTML = [
    `<strong>Context Debug</strong>`,
    `session: ${result.session_id || "n/a"}`,
    `received text chars: ${received.text_chars ?? 0}`,
    `received image count: ${received.image_count ?? 0}`,
    `stored has text: ${stored.has_text ? "yes" : "no"}`,
    `stored text chars: ${stored.stored_text_chars ?? 0}`,
    `stored has images: ${stored.has_images ? "yes" : "no"}`,
    `stored image count: ${stored.stored_image_count ?? 0}`,
    `text preview: ${(received.text_preview || "").slice(0, 120) || "(empty)"}`,
    `first image: ${received.images_preview?.[0] || "(none)"}`
  ].join("<br>");

  chatEl.appendChild(block);
  chatEl.scrollTop = chatEl.scrollHeight;
}

function getCurrentTab(): Promise<{ id?: number; url?: string }> {
  if (!hasChromeRuntime) {
    return Promise.reject(new Error("Preview mode does not have browser tab access"));
  }

  return new Promise((resolve, reject) => {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs: Array<{ id?: number; url?: string }>) => {
      const tab = tabs[0];
      if (!tab?.id) {
        reject(new Error("No active tab found"));
        return;
      }
      resolve(tab);
    });
  });
}

function requestPageContext(tabId: number): Promise<WebPageContext> {
  if (!hasChromeRuntime) {
    return Promise.resolve({
      url: "https://example.com/sweater",
      title: "Demo Sweater Product Page",
      text: "This is a demo context used in popup preview mode.",
      images: ["https://picsum.photos/300/300"]
    });
  }

  const extractViaScripting = (): Promise<WebPageContext> => {
    return new Promise((resolve, reject) => {
      chrome.scripting.executeScript(
        {
          target: { tabId },
          func: () => {
            const text = (document.body?.innerText || "").slice(0, 10000);
            const images = Array.from(document.querySelectorAll("img"))
              .map((img) => (img as HTMLImageElement).src || "")
              .filter(Boolean)
              .slice(0, 5);

            return {
              url: window.location.href,
              title: document.title,
              text,
              images
            };
          }
        },
        (results: Array<{ result?: WebPageContext }>) => {
          if (chrome.runtime.lastError) {
            reject(new Error(chrome.runtime.lastError.message));
            return;
          }

          const context = results?.[0]?.result;
          if (!context) {
            reject(new Error("Failed to capture page context"));
            return;
          }

          resolve(context);
        }
      );
    });
  };

  return new Promise((resolve, reject) => {
    chrome.tabs.sendMessage(tabId, { type: "GET_PAGE_CONTEXT" }, (response: { context?: WebPageContext }) => {
      if (chrome.runtime.lastError) {
        // Most common cause: content script not injected (tab opened before extension install/reload)
        // or the page does not allow content scripts. Try a scripting fallback.
        extractViaScripting().then(resolve).catch((err) => {
          const reason = chrome.runtime.lastError?.message || "No receiver in tab";
          reject(new Error(`${reason}. Fallback failed: ${err instanceof Error ? err.message : String(err)}`));
        });
        return;
      }

      if (!response?.context) {
        reject(new Error("Failed to capture page context"));
        return;
      }

      resolve(response.context as WebPageContext);
    });
  });
}

function queryAgent(prompt: string, context: WebPageContext): Promise<AgentResponse> {
  if (!hasChromeRuntime) {
    return Promise.resolve({
      response: `Preview response for: "${prompt}" on page "${context.title}"`
    });
  }

  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(
      {
        type: "AGENT_QUERY",
        payload: { prompt, context }
      },
      (response: { ok?: boolean; error?: string; data?: AgentResponse }) => {
        if (chrome.runtime.lastError) {
          reject(new Error(chrome.runtime.lastError.message));
          return;
        }

        if (!response?.ok) {
          reject(new Error(response?.error || "Agent request failed"));
          return;
        }

        resolve(response.data as AgentResponse);
      }
    );
  });
}

function getStoredContext(sessionId: string): Promise<StoredContextResponse> {
  if (!hasChromeRuntime) {
    return Promise.resolve({
      session_id: sessionId,
      context: {
        url: "https://example.com/sweater",
        title: "Demo Sweater Product Page",
        text: "Preview mode mock stored context.",
        images: ["https://picsum.photos/300/300"]
      }
    });
  }

  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(
      {
        type: "AGENT_GET_CONTEXT",
        payload: { session_id: sessionId }
      },
      (response: { ok?: boolean; error?: string; data?: StoredContextResponse }) => {
        if (chrome.runtime.lastError) {
          reject(new Error(chrome.runtime.lastError.message));
          return;
        }

        if (!response?.ok || !response.data) {
          reject(new Error(response?.error || "Failed to fetch stored context"));
          return;
        }

        resolve(response.data);
      }
    );
  });
}

appendMessage(
  "Agent",
  hasChromeRuntime
    ? "Ready. Ask me about this page."
    : "Running in preview mode. API calls are mocked."
);

sendBtn.addEventListener("click", async () => {
  const prompt = promptEl.value.trim();
  if (!prompt) {
    return;
  }

  appendMessage("User", prompt);
  promptEl.value = "";
  sendBtn.disabled = true;

  try {
    const tab = await getCurrentTab();
    const context = await requestPageContext(tab.id as number);
    const result = await queryAgent(prompt, context);
    lastSessionId = result.session_id || null;
    appendMessage("Agent", result.response || "No response received.");
    appendContextDebug(result);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unexpected error";
    appendMessage("Agent", `Error: ${message}`);
  } finally {
    sendBtn.disabled = false;
  }
});

viewContextBtn.addEventListener("click", async () => {
  if (!lastSessionId) {
    appendMessage("Agent", "No session yet. Send a prompt first.");
    return;
  }

  viewContextBtn.disabled = true;
  try {
    const data = await getStoredContext(lastSessionId);
    appendMessage(
      "Agent",
      `Stored context for ${data.session_id}: text chars=${data.context.text.length}, images=${data.context.images.length}`
    );
    appendMessage("Agent", `Stored text preview: ${data.context.text.slice(0, 220) || "(empty)"}`);
    appendMessage("Agent", `Stored first image: ${data.context.images[0] || "(none)"}`);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unexpected error";
    appendMessage("Agent", `Error: ${message}`);
  } finally {
    viewContextBtn.disabled = false;
  }
});
