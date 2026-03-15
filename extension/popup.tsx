import { createCandidate, resolveSelectedCandidate, type CandidateProduct } from "./selection_utils";

type WebPageContext = {
  url: string;
  title: string;
  text: string;
  images: string[];
  candidate_products: CandidateProduct[];
  selected_candidate: CandidateProduct | null;
};

type RawScriptingContext = {
  url: string;
  title: string;
  text: string;
  images: string[];
  candidate_products_raw: Array<{ src: string; alt_text: string }>;
  selected_candidate_raw: { src: string; alt_text: string } | null;
  selection_text: string;
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
  tools_used?: string[];
  tool_results?: any[];
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
let lastTabUrl: string | null = null;

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function appendMessage(sender: "User" | "Agent", text: string): void {
  const line = document.createElement("div");
  line.style.marginBottom = "10px";
  line.style.padding = "9px";
  line.style.borderRadius = "10px";
  line.style.border = sender === "User" ? "1px solid #9dd0ff" : "1px solid #d7ebff";
  line.style.background = sender === "User" ? "#eaf5ff" : "#ffffff";
  line.style.color = "#0f172a";
  line.style.boxShadow = "0 3px 10px rgba(59,130,246,0.08)";
  line.style.whiteSpace = "pre-wrap";
  line.style.wordBreak = "break-word";
  line.innerHTML = `<strong>${sender}:</strong> ${escapeHtml(text).replace(/\n/g, "<br>")}`;
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
      images: ["https://picsum.photos/300/300"],
      candidate_products: [
        { image: "https://picsum.photos/300/300", alt_text: "Demo sweater" },
      ],
      selected_candidate: { image: "https://picsum.photos/300/300", alt_text: "Demo sweater" },
    });
  }

  const extractViaScripting = (): Promise<WebPageContext> => {
    return new Promise((resolve, reject) => {
      chrome.scripting.executeScript(
        {
          target: { tabId },
          func: () => {
            const text = (document.body?.innerText || "").slice(0, 10000);
            const imageElements = Array.from(document.querySelectorAll("img"));

            const images = imageElements
              .map((img) => (img as HTMLImageElement).src || "")
              .filter(Boolean)
              .slice(0, 50);

            const candidate_products_raw = imageElements
              .map((img) => {
                const element = img as HTMLImageElement;
                const src = element.src || "";
                if (!src) {
                  return null;
                }

                const alt_text =
                  (element.getAttribute("alt") ||
                    element.getAttribute("aria-label") ||
                    element.getAttribute("title") ||
                    "").trim() || "Unnamed product";

                return { src, alt_text };
              })
              .filter(Boolean)
              .slice(0, 50) as Array<{ src: string; alt_text: string }>;

            const selection_text = (window.getSelection?.()?.toString() || "").trim();
            let selected_candidate_raw: { src: string; alt_text: string } | null = null;

            // If user clicked a product in an injected content script, honor that marker.
            if (!selected_candidate_raw) {
              const marked = document.querySelector('img[data-browserbuddy-selected-candidate="1"]') as HTMLImageElement | null;
              if (marked?.src) {
                selected_candidate_raw = {
                  src: marked.src,
                  alt_text: (marked.getAttribute("alt") || marked.getAttribute("aria-label") || marked.getAttribute("title") || "").trim() || "Unnamed product",
                };
              }
            }

            return {
              url: window.location.href,
              title: document.title,
              text,
              images,
              candidate_products_raw,
              selected_candidate_raw,
              selection_text,
            };
          }
        },
        (results: Array<{ result?: RawScriptingContext }>) => {
          if (chrome.runtime.lastError) {
            reject(new Error(chrome.runtime.lastError.message));
            return;
          }

          const raw = results?.[0]?.result;
          if (!raw) {
            reject(new Error("Failed to capture page context"));
            return;
          }

          const candidate_products = raw.candidate_products_raw
            .map((item) => createCandidate(item.src, item.alt_text, raw.url))
            .filter((item): item is CandidateProduct => Boolean(item));

          const explicitSelected = raw.selected_candidate_raw
            ? createCandidate(raw.selected_candidate_raw.src, raw.selected_candidate_raw.alt_text, raw.url)
            : null;

          const selected_candidate = resolveSelectedCandidate(
            candidate_products,
            explicitSelected,
            raw.selection_text || ""
          );

          resolve({
            url: raw.url,
            title: raw.title,
            text: raw.text,
            images: raw.images,
            candidate_products,
            selected_candidate,
          });
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

function queryAgent(payload: { prompt: string; context?: WebPageContext; session_id?: string }): Promise<AgentResponse> {
  if (!hasChromeRuntime) {
    const contextTitle = payload.context?.title || "(no context)";
    return Promise.resolve({
      session_id: payload.session_id,
      response: `Preview response for: "${payload.prompt}" on page "${contextTitle}"`
    });
  }

  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(
      {
        type: "AGENT_QUERY",
        payload
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
        images: ["https://picsum.photos/300/300"],
        candidate_products: [
          { image: "https://picsum.photos/300/300", alt_text: "Demo sweater" },
        ],
        selected_candidate: { image: "https://picsum.photos/300/300", alt_text: "Demo sweater" },
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

function shouldRefreshContextForPrompt(prompt: string): boolean {
  const p = prompt.trim().toLowerCase();
  if (!p) {
    return false;
  }

  // Refresh context when user likely asks for product/similarity actions,
  // so new mouse-selected candidate reaches backend even in existing session.
  return /(cheaper|price|buy|purchase|shop|deal|discount|alternative|similar|like this|match|same style|find this)/i.test(p);
}

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
    const tabUrl = tab.url || null;

    // If the user navigated to a different page while the popup is open,
    // start a fresh session so we don't reuse the wrong stored context.
    if (lastSessionId && lastTabUrl && tabUrl && tabUrl !== lastTabUrl) {
      lastSessionId = null;
    }

    let result: AgentResponse;
    if (lastSessionId && !shouldRefreshContextForPrompt(prompt)) {
      result = await queryAgent({ prompt, session_id: lastSessionId });
    } else {
      const context = await requestPageContext(tab.id as number);
      result = await queryAgent({ prompt, context, session_id: lastSessionId || undefined });
    }

    lastSessionId = result.session_id || null;
    lastTabUrl = tabUrl;

    // Show tool badges if available
    if (result.tools_used && result.tools_used.length > 0) {
      const toolBadges = result.tools_used.map((t: string) => `[${t}]`).join(" ");
      appendMessage("Agent", `Tools used: ${toolBadges}`);
    }

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
