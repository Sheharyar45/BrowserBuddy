const BACKEND_BASE_URL = "http://127.0.0.1:8000";
const BACKEND_QUERY_URL = `${BACKEND_BASE_URL}/agent/query`;

chrome.runtime.onMessage.addListener((message: any, _sender: any, sendResponse: (response?: any) => void) => {
  if (message?.type === "AGENT_QUERY") {
    void (async () => {
      try {
        const response = await fetch(BACKEND_QUERY_URL, {
          method: "POST",
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify(message.payload)
        });

        if (!response.ok) {
          const text = await response.text();
          sendResponse({ ok: false, error: `Backend error ${response.status}: ${text}` });
          return;
        }

        const data = await response.json();
        sendResponse({ ok: true, data });
      } catch (error) {
        const errorMessage = error instanceof Error ? error.message : "Unknown network error";
        sendResponse({ ok: false, error: errorMessage });
      }
    })();

    return true;
  }

  if (message?.type === "AGENT_GET_CONTEXT") {
    void (async () => {
      try {
        const sessionId = message?.payload?.session_id;
        if (!sessionId) {
          sendResponse({ ok: false, error: "Missing session_id" });
          return;
        }

        const response = await fetch(`${BACKEND_BASE_URL}/context/${encodeURIComponent(sessionId)}`);
        if (!response.ok) {
          const text = await response.text();
          sendResponse({ ok: false, error: `Backend error ${response.status}: ${text}` });
          return;
        }

        const data = await response.json();
        sendResponse({ ok: true, data });
      } catch (error) {
        const errorMessage = error instanceof Error ? error.message : "Unknown network error";
        sendResponse({ ok: false, error: errorMessage });
      }
    })();

    return true;
  }

  return false;
});
