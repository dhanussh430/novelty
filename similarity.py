"""Text-similarity ranking. This measures WORDING overlap only - it is NOT a legal novelty determination."""
import math
from collections import Counter

from .features import stem, stems, tokenize

FEATURE_MATCH_THRESHOLD = 0.6
W_COSINE, W_COVERAGE = 0.5, 0.5

DISCLAIMER = ("Similarity percentages measure textual/keyword overlap between your description and the title/abstract "
              "(or snippet) of retrieved documents. They are NOT a legal assessment of novelty, inventive step or "
              "patentability. Novelty is established only by a full prior-art search and examination by a patent "
              "office or qualified patent attorney.")


def overlap_level(score: float) -> str:
    if score >= 60:
        return "High text overlap - review these documents closely"
    if score >= 35:
        return "Moderate text overlap - partial overlap with existing documents"
    if score > 0:
        return "Low text overlap among retrieved documents (does not prove novelty)"
    return "No overlap found in retrieved documents (does not prove novelty)"


def _tfidf(token_lists):
    n = len(token_lists)
    df = Counter()
    for toks in token_lists:
        df.update(set(toks))
    idf = {w: math.log((1 + n) / (1 + c)) + 1 for w, c in df.items()}
    vecs = []
    for toks in token_lists:
        v = {w: (1 + math.log(c)) * idf[w] for w, c in Counter(toks).items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        vecs.append({w: x / norm for w, x in v.items()})
    return vecs


def _cos(a, b):
    if len(a) > len(b):
        a, b = b, a
    return sum(x * b.get(w, 0.0) for w, x in a.items())


def feature_scores(features, doc_stems):
    out = {}
    ds = set(doc_stems)
    for f in features:
        fs = {stem(t) for t in tokenize(f)}
        out[f] = (len(fs & ds) / len(fs)) if fs else 0.0
    return out


def rank(idea: str, features: list, docs: list) -> list:
    """Return docs enriched with similarity data, sorted best-first."""
    if not docs:
        return []
    doc_texts = [f"{d.get('title', '')}. {d.get('abstract', '')}" for d in docs]
    idea_stems = stems(idea)
    doc_stems = [stems(t) for t in doc_texts]
    vecs = _tfidf([idea_stems] + doc_stems)
    idea_set = set(idea_stems)
    ranked = []
    for d, ds, v in zip(docs, doc_stems, vecs[1:]):
        cos = max(0.0, min(1.0, _cos(vecs[0], v)))
        fscores = feature_scores(features, ds)
        coverage = (sum(fscores.values()) / len(fscores)) if fscores else 0.0
        matched = [f for f, s in fscores.items() if s >= FEATURE_MATCH_THRESHOLD]
        missing = [f for f, s in fscores.items() if s < FEATURE_MATCH_THRESHOLD]
        shared = sorted(idea_set & set(ds), key=lambda s: (-len(s), s))[:10]
        score = 100 * (W_COSINE * cos + W_COVERAGE * coverage) if features else 100 * cos
        has_abs = bool(d.get("abstract"))
        parts = [f"Shares {len(matched)} of {len(features)} idea features."]
        if matched:
            parts.append("Overlapping: " + "; ".join(matched[:5]) + ".")
        if missing:
            parts.append("Not evidenced in this document's text: " + "; ".join(missing[:5]) + ".")
        if shared:
            parts.append("Shared terms: " + ", ".join(shared[:8]) + ".")
        if not has_abs:
            parts.append("No abstract available - compared on title only, so the score may understate real overlap.")
        item = dict(d)
        item.update({
            "similarity": round(score, 1), "cosine": round(cos * 100, 1), "coverage": round(coverage * 100, 1),
            "matched_features": matched, "missing_features": missing, "shared_terms": shared,
            "feature_scores": {k: round(v, 2) for k, v in fscores.items()},
            "explanation": " ".join(parts), "has_abstract": has_abs,
        })
        ranked.append(item)
    ranked.sort(key=lambda x: (-x["similarity"], -x["cosine"], x["title"]))
    for i, r in enumerate(ranked, 1):
        r["rank"] = i
    return ranked


NOVELTY_NOTE = ("The novelty score is an INDICATIVE heuristic built from text similarity and feature coverage of the "
                "documents retrieved. It is NOT a legal novelty or patentability opinion and can overstate novelty when "
                "few documents were retrieved.")


def novelty_assessment(ranked: list, features: list, statuses=None, top_n: int = 10) -> dict:
    """Indicative novelty score 0-100 (higher = fewer close matches found).

    score = 100 x ( 0.4 x (1 - best similarity) + 0.2 x (1 - mean of top-5 similarities) + 0.4 x share of features
                    NOT clearly covered (best coverage < 50%) by any of the top documents )
    """
    if not ranked:
        return {"score": None, "label": "Cannot be assessed - no documents were retrieved", "confidence": "None",
                "components": {}, "notes": ["Check the Source status table, then retry or broaden the wording."],
                "disclaimer": NOVELTY_NOTE}
    sims = [d["similarity"] / 100 for d in ranked]
    top = sims[0]
    top5 = sum(sims[:5]) / min(5, len(sims))
    top_docs = ranked[:top_n]
    uncovered = [f for f in features if max((d["feature_scores"].get(f, 0.0) for d in top_docs), default=0.0) < 0.5]
    gap = (len(uncovered) / len(features)) if features else 0.0
    if features:
        score = 100 * (0.4 * (1 - top) + 0.2 * (1 - top5) + 0.4 * gap)
    else:
        score = 100 * (0.7 * (1 - top) + 0.3 * (1 - top5))
    score = round(max(0.0, min(100.0, score)), 1)
    label = ("High apparent novelty (few close matches found)" if score >= 70 else
             "Moderate apparent novelty (partial overlap with existing work)" if score >= 45 else
             "Low apparent novelty (close existing documents found)")
    n_pat = sum(1 for d in ranked if d["kind"] == "patent")
    n_src = len({d["source"] for d in ranked})
    points = (len(ranked) >= 20) + (n_pat >= 3) + (n_src >= 3)
    confidence = ["Low", "Low", "Medium", "High"][points]
    notes = []
    if n_pat == 0:
        notes.append("No patent records were available, so the score reflects research papers only.")
    if len(ranked) < 10:
        notes.append("Fewer than 10 documents were retrieved; the score may overstate novelty.")
    if uncovered:
        notes.append(f"{len(uncovered)} of {len(features)} features were not clearly covered by the top documents.")
    return {"score": score, "label": label, "confidence": confidence, "disclaimer": NOVELTY_NOTE, "notes": notes,
            "uncovered_features": uncovered,
            "components": {"best_similarity_pct": round(top * 100, 1), "top5_mean_similarity_pct": round(top5 * 100, 1),
                           "uncovered_feature_share_pct": round(gap * 100, 1), "documents": len(ranked), "patents": n_pat}}
