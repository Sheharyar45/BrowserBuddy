import { createCandidate, resolveSelectedCandidate, type CandidateProduct } from "./selection_utils";

type PageContext = {
  url: string;
  title: string;
  text: string;
  images: string[];
  candidate_products: CandidateProduct[];
  selected_candidate: CandidateProduct | null;
};

const SELECTED_ATTR = "data-browserbuddy-selected-candidate";
let selectedCandidate: CandidateProduct | null = null;

function clearSelectedCandidateMarker(): void {
  const previouslySelected = document.querySelectorAll(`img[${SELECTED_ATTR}="1"]`);
  previouslySelected.forEach((el) => {
    el.removeAttribute(SELECTED_ATTR);
    (el as HTMLElement).style.outline = "";
    (el as HTMLElement).style.outlineOffset = "";
  });
}

function setSelectedCandidateFromImage(img: HTMLImageElement): void {
  const src = (img.getAttribute("src") || "").trim();
  if (!src) {
    return;
  }

  clearSelectedCandidateMarker();

  const image = new URL(src, window.location.href).toString();
  const alt_text =
    (img.getAttribute("alt") || img.getAttribute("aria-label") || img.getAttribute("title") || "").trim() ||
    "Unnamed product";

  selectedCandidate = { image, alt_text };

  img.setAttribute(SELECTED_ATTR, "1");
  img.style.outline = "3px solid #60a5fa";
  img.style.outlineOffset = "2px";
}

document.addEventListener(
  "click",
  (event: MouseEvent) => {
    const target = event.target as HTMLElement | null;
    if (!target) {
      return;
    }

    const img = target.closest("img") as HTMLImageElement | null;
    if (!img) {
      return;
    }

    setSelectedCandidateFromImage(img);
  },
  true
);


function extractPageContext(): PageContext {
  const text = (document.body?.innerText || "").slice(0, 10000);

  const imageElements = Array.from(document.querySelectorAll("img"));

  const images = imageElements
    .map((img) => img.getAttribute("src") || "")
    .filter(Boolean)
    .map((src) => new URL(src, window.location.href).toString())
    .slice(0, 50);

  const candidateProducts = imageElements
    .map((img) => {
      const src = (img.getAttribute("src") || "").trim();
      const alt = (img.getAttribute("alt") || img.getAttribute("aria-label") || img.getAttribute("title") || "").trim();
      return createCandidate(src, alt, window.location.href);
    })
    .filter((item): item is CandidateProduct => Boolean(item))
    .slice(0, 50);

  const selectionText = (window.getSelection?.()?.toString() || "").trim();
  const effectiveSelectedCandidate = resolveSelectedCandidate(candidateProducts, selectedCandidate, selectionText);

  return {
    url: window.location.href,
    title: document.title,
    text,
    images,
    candidate_products: candidateProducts,
    selected_candidate: effectiveSelectedCandidate,
  };
}

chrome.runtime.onMessage.addListener((message: any, _sender: any, sendResponse: (response?: any) => void) => {
  if (message?.type === "GET_PAGE_CONTEXT") {
    sendResponse({ context: extractPageContext() });
  }
});
