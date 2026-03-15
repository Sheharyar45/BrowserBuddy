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
  routing_method?: string;
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

function formatAgentText(text: string): string {
  const urlRegex = /(https?:\/\/[^\s]+)/g;
  const parts = text.split(urlRegex);
  return parts
    .map((part, i) => {
      if (i % 2 === 1) {
        let url = part;
        const trailingMatch = url.match(/([.,;:!?)]+)$/);
        let trailing = "";
        if (trailingMatch) {
          trailing = trailingMatch[1];
          url = url.slice(0, -trailing.length);
        }
        const display = url.length > 60 ? url.slice(0, 57) + "..." : url;
        return `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer" style="color:#2563eb;word-break:break-all;text-decoration:underline;">${escapeHtml(display)}</a>${escapeHtml(trailing)}`;
      }
      return escapeHtml(part).replace(/\n/g, "<br>");
    })
    .join("");
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
  const formatted = sender === "Agent" ? formatAgentText(text) : escapeHtml(text).replace(/\n/g, "<br>");
  line.innerHTML = `<strong>${sender}:</strong> ${formatted}`;
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

let loadingEl: HTMLDivElement | null = null;

function showLoading(): void {
  hideLoading();
  loadingEl = document.createElement("div");
  loadingEl.style.cssText =
    "margin-bottom:10px;padding:12px;border-radius:10px;border:1px dashed #93c5fd;" +
    "background:#f0f7ff;color:#64748b;font-size:12px;text-align:center;";
  loadingEl.textContent = "Thinking\u2026";
  chatEl.appendChild(loadingEl);
  chatEl.scrollTop = chatEl.scrollHeight;
}

function hideLoading(): void {
  if (loadingEl) {
    loadingEl.remove();
    loadingEl = null;
  }
}

const TOOL_DISPLAY_NAMES: Record<string, { label: string; icon: string; color: string; bg: string }> = {
  summarize_page: { label: "Summarize", icon: "\uD83D\uDCDD", color: "#0369a1", bg: "#e0f2fe" },
  shopping_search: { label: "Shopping Search", icon: "\uD83D\uDED2", color: "#7c3aed", bg: "#ede9fe" },
  image_similarity: { label: "Image Similarity", icon: "\uD83D\uDD0D", color: "#0d9488", bg: "#ccfbf1" },
  generate_content: { label: "Content Generator", icon: "\u270D\uFE0F", color: "#c2410c", bg: "#fff7ed" },
};

function toolBadgeHtml(toolName: string): string {
  const info = TOOL_DISPLAY_NAMES[toolName];
  if (!info) return "";
  return (
    `<span style="display:inline-block;font-size:10px;font-weight:600;color:${info.color};` +
    `background:${info.bg};padding:2px 8px;border-radius:6px;margin-left:6px;vertical-align:middle;">` +
    `${info.icon} ${info.label}</span>`
  );
}

function appendToolCard(toolName: string, data: any): void {
  if (!data) return;
  if (data?.error && !data?.results?.length) {
    appendMessage("Agent", `Error (${toolName}): ${data.error}`);
    return;
  }

  const card = document.createElement("div");
  card.style.cssText =
    "margin-bottom:10px;padding:10px;border-radius:10px;border:1px solid #d7ebff;" +
    "background:#ffffff;box-shadow:0 3px 10px rgba(59,130,246,0.08);font-size:12px;color:#0f172a;";

  if (toolName === "image_similarity") {
    const identified = data.identified_item || "Similar Items";
    const method = data.method || "";
    let html = `<div style="font-weight:700;color:#0b3a66;font-size:13px;margin-bottom:8px;">\uD83D\uDD0D ${escapeHtml(identified)}${toolBadgeHtml(toolName)}`;
    if (method)
      html += ` <span style="font-size:10px;font-weight:400;color:#64748b;background:#f1f5f9;padding:2px 6px;border-radius:4px;">${escapeHtml(method)}</span>`;
    html += `</div>`;
    const items: any[] = data.results || [];
    if (!items.length) html += `<div style="color:#94a3b8;">No similar items found.</div>`;
    for (const item of items) {
      html += `<div style="padding:6px 0;border-top:1px solid #f0f4f8;">`;
      html += item.url
        ? `<a href="${escapeHtml(item.url)}" target="_blank" rel="noopener" style="color:#2563eb;font-weight:600;font-size:12px;text-decoration:none;">${escapeHtml(item.title || "Result")}</a>`
        : `<div style="font-weight:600;">${escapeHtml(item.title || "Result")}</div>`;
      if (item.price)
        html += ` <span style="color:#059669;font-weight:600;font-size:11px;">${escapeHtml(String(item.price))}</span>`;
      if (item.snippet)
        html += `<div style="color:#64748b;font-size:11px;margin-top:2px;line-height:1.4;">${escapeHtml(String(item.snippet).slice(0, 150))}</div>`;
      html += `</div>`;
    }
    if (data.note)
      html += `<div style="color:#94a3b8;font-size:10px;margin-top:6px;font-style:italic;">${escapeHtml(data.note)}</div>`;
    card.innerHTML = html;

  } else if (toolName === "shopping_search") {
    const query = data.query || "Products";
    const isVision = data.vision_enhanced;
    let html = `<div style="font-weight:700;color:#0b3a66;font-size:13px;margin-bottom:8px;">\uD83D\uDED2 ${escapeHtml(query)}${toolBadgeHtml(toolName)}`;
    if (isVision)
      html += ` <span style="font-size:10px;font-weight:400;color:#7c3aed;background:#ede9fe;padding:2px 6px;border-radius:4px;">Vision Enhanced</span>`;
    html += `</div>`;
    const items: any[] = data.results || [];
    if (!items.length) html += `<div style="color:#94a3b8;">No results found.</div>`;
    for (const item of items) {
      html += `<div style="padding:6px 0;border-top:1px solid #f0f4f8;">`;
      html += item.url
        ? `<a href="${escapeHtml(item.url)}" target="_blank" rel="noopener" style="color:#2563eb;font-weight:600;font-size:12px;text-decoration:none;">${escapeHtml(item.title || "Product")}</a>`
        : `<div style="font-weight:600;">${escapeHtml(item.title || "Product")}</div>`;
      if (item.price)
        html += ` <span style="display:inline-block;color:#059669;font-weight:700;font-size:11px;background:#ecfdf5;padding:1px 5px;border-radius:4px;margin-top:2px;">${escapeHtml(String(item.price))}</span>`;
      if (item.snippet)
        html += `<div style="color:#64748b;font-size:11px;margin-top:2px;line-height:1.4;">${escapeHtml(String(item.snippet).slice(0, 150))}</div>`;
      html += `</div>`;
    }
    if (data.note)
      html += `<div style="color:#94a3b8;font-size:10px;margin-top:6px;font-style:italic;">${escapeHtml(data.note)}</div>`;
    card.innerHTML = html;

  } else if (toolName === "summarize_page") {
    const summary = data.summary || "";
    const keyPoints: string[] = data.key_points || [];
    const method = data.method || "";
    let html = `<div style="font-weight:700;color:#0b3a66;font-size:13px;margin-bottom:8px;">\uD83D\uDCDD Summary${toolBadgeHtml(toolName)}`;
    if (method)
      html += ` <span style="font-size:10px;font-weight:400;color:#64748b;background:#f1f5f9;padding:2px 6px;border-radius:4px;">${escapeHtml(method)}</span>`;
    html += `</div>`;
    html += `<div style="color:#0f172a;line-height:1.5;white-space:pre-wrap;">${formatAgentText(summary)}</div>`;
    if (keyPoints.length) {
      html += `<div style="margin-top:8px;font-weight:600;color:#0b3a66;font-size:11px;">Key Points:</div>`;
      for (const kp of keyPoints) {
        html += `<div style="color:#334155;font-size:11px;line-height:1.4;padding-left:8px;">\u2022 ${escapeHtml(kp)}</div>`;
      }
    }
    card.innerHTML = html;

  } else if (toolName === "generate_content") {
    const content = data.content || "";
    const method = data.method || "";
    let html = `<div style="font-weight:700;color:#0b3a66;font-size:13px;margin-bottom:8px;">\u270D\uFE0F Generated${toolBadgeHtml(toolName)}`;
    if (method)
      html += ` <span style="font-size:10px;font-weight:400;color:#64748b;background:#f1f5f9;padding:2px 6px;border-radius:4px;">${escapeHtml(method)}</span>`;
    html += `</div>`;
    html += `<div style="color:#0f172a;line-height:1.5;white-space:pre-wrap;font-size:12px;">${formatAgentText(content)}</div>`;
    card.innerHTML = html;

  } else {
    card.innerHTML = `<div style="white-space:pre-wrap;">${formatAgentText(JSON.stringify(data, null, 2))}</div>`;
  }

  chatEl.appendChild(card);
  chatEl.scrollTop = chatEl.scrollHeight;
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

  return /(cheaper|price|buy|purchase|shop|deal|discount|alternative|similar|like this|match|same style|find this|near me|nearby|places)/i.test(p);
}

sendBtn.addEventListener("click", async () => {
  const prompt = promptEl.value.trim();
  if (!prompt) {
    return;
  }

  appendMessage("User", prompt);
  promptEl.value = "";
  sendBtn.disabled = true;
  showLoading();

  try {
    const tab = await getCurrentTab();
    const tabUrl = tab.url || null;

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

    hideLoading();
    lastSessionId = result.session_id || null;
    lastTabUrl = tabUrl;

    // Render structured tool cards when available; fall back to text.
    const hasCards =
      Array.isArray(result.tool_results) &&
      result.tool_results.length > 0 &&
      Array.isArray(result.tools_used) &&
      result.tools_used.length > 0 &&
      result.tool_results.some((r: any) => r && !r.error);

    if (hasCards) {
      const tools = result.tools_used!;
      const results = result.tool_results!;

      // Show routing info banner
      const routeInfo = document.createElement("div");
      const toolLabels = tools
        .map((t: string) => {
          const info = TOOL_DISPLAY_NAMES[t];
          return info ? `${info.icon} ${info.label}` : t;
        })
        .join(" → ");
      routeInfo.style.cssText =
        "margin-bottom:6px;padding:5px 10px;border-radius:8px;" +
        "background:#f0f9ff;color:#0c4a6e;font-size:10px;font-weight:500;";
      routeInfo.textContent = `Tool${tools.length > 1 ? "s" : ""} used: ${toolLabels}`;
      chatEl.appendChild(routeInfo);

      for (let i = 0; i < tools.length; i++) {
        appendToolCard(tools[i], results[i]);
      }
    } else {
      appendMessage("Agent", result.response || "No response received.");
    }
  } catch (error) {
    hideLoading();
    const message = error instanceof Error ? error.message : "Unexpected error";
    appendMessage("Agent", `Error: ${message}`);
  } finally {
    sendBtn.disabled = false;
  }
});

promptEl.addEventListener("keydown", (e: KeyboardEvent) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendBtn.click();
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
