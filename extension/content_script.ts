type PageContext = {
  url: string;
  title: string;
  text: string;
  images: string[];
};


function extractPageContext(): PageContext {
  const text = (document.body?.innerText || "").slice(0, 10000);

  const images = Array.from(document.querySelectorAll("img"))
    .map((img) => img.getAttribute("src") || "")
    .filter(Boolean)
    .map((src) => new URL(src, window.location.href).toString())
    .slice(0, 5);

  return {
    url: window.location.href,
    title: document.title,
    text,
    images
  };
}

chrome.runtime.onMessage.addListener((message: any, _sender: any, sendResponse: (response?: any) => void) => {
  if (message?.type === "GET_PAGE_CONTEXT") {
    sendResponse({ context: extractPageContext() });
  }
});
