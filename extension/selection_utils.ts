export type CandidateProduct = { image: string; alt_text: string };

export function tokenizeText(text: string): Set<string> {
  const matches = text.toLowerCase().match(/[a-z0-9]{3,}/g) || [];
  return new Set(matches);
}

export function createCandidate(
  src: string,
  altText: string,
  baseUrl: string
): CandidateProduct | null {
  const trimmedSrc = (src || "").trim();
  if (!trimmedSrc) {
    return null;
  }

  let absoluteImage = trimmedSrc;
  try {
    absoluteImage = new URL(trimmedSrc, baseUrl).toString();
  } catch {
    absoluteImage = trimmedSrc;
  }

  const cleanedAlt = (altText || "").trim() || "Unnamed product";
  return {
    image: absoluteImage,
    alt_text: cleanedAlt,
  };
}

export function inferSelectedCandidateFromText(
  candidates: CandidateProduct[],
  selectionText: string
): CandidateProduct | null {
  const cleanedSelection = (selectionText || "").trim();
  if (cleanedSelection.length < 2) {
    return null;
  }

  const selectionTokens = tokenizeText(cleanedSelection);
  if (selectionTokens.size === 0) {
    return null;
  }

  let best: { score: number; candidate: CandidateProduct } | null = null;
  for (const candidate of candidates) {
    const altTokens = tokenizeText(candidate.alt_text || "");
    if (altTokens.size === 0) {
      continue;
    }

    let score = 0;
    for (const token of selectionTokens) {
      if (altTokens.has(token)) {
        score += 1;
      }
    }

    if (!best || score > best.score) {
      best = { score, candidate };
    }
  }

  if (!best || best.score === 0) {
    return null;
  }

  return best.candidate;
}

export function resolveSelectedCandidate(
  candidates: CandidateProduct[],
  explicitSelectedCandidate: CandidateProduct | null,
  selectionText: string
): CandidateProduct | null {
  if (explicitSelectedCandidate) {
    return explicitSelectedCandidate;
  }

  return inferSelectedCandidateFromText(candidates, selectionText);
}
