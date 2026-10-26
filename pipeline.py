"""End-to-end analysis: extract -> search (parallel) -> rank -> suggest. Returns one plain dict (JSON-serialisable)."""
import copy
import datetime
import time
import uuid

from . import features as F
from . import similarity as S
from . import feature_ideas, priorwork, sources, suggestions


def run_analysis(idea, title="", custom_features=None, enabled=None, per_source=10, mailto="", lens_token="",
                 thorough=False, only_custom=False, search_fn=None, max_features=12):
    t0 = time.time()
    idea = " ".join((idea or "").split())
    if not idea:
        raise ValueError("Invention description is empty.")
    custom = [" ".join(f.split()) for f in (custom_features or []) if f and f.strip()]
    auto = F.extract_features(idea, max_features)
    feats = custom if (custom and only_custom) else F.merge_features(custom, auto, max_features + len(custom))
    keywords = F.extract_keywords(idea)
    queries = F.build_queries(feats, keywords)
    enabled = list(sources.DEFAULT_ENABLED if enabled is None else enabled)
    if lens_token and "Lens.org" not in enabled:
        enabled.append("Lens.org")
    search_fn = search_fn or sources.search_all
    kwargs = dict(enabled=enabled, per_source=per_source, mailto=mailto, lens_token=lens_token, thorough=thorough)

    def _safe(qs):
        try:
            return search_fn(qs, **kwargs)
        except Exception as e:  # defensive: UI must never crash on a source failure
            return [], [{"source": "search", "kind": "-", "ok": False, "state": "failed", "count": 0, "seconds": 0.0,
                         "message": f"{type(e).__name__}: {e}"}]

    docs, statuses = _safe(queries)
    # Fallback with a simpler query ONLY when some source answered but nothing matched (not when everything is down)
    if not docs and len(keywords) >= 2 and any(s["ok"] for s in statuses):
        fb = [" ".join(keywords[:3])]
        if fb[0] not in queries:
            queries = queries + fb
            docs, st2 = _safe(fb)
            best = {s["source"]: s for s in statuses}
            for s in st2:  # keep, per source, the row that did better
                old = best.get(s["source"])
                if old is None or (s["ok"], s["count"]) > (old["ok"], old["count"]):
                    best[s["source"]] = s
            statuses = list(best.values())

    ranked = S.rank(idea, feats, docs)
    top = ranked[0]["similarity"] if ranked else 0.0
    result = {
        "run_id": uuid.uuid4().hex[:8],
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed": round(time.time() - t0, 1),
        "title": title.strip() or "Untitled invention",
        "idea": idea,
        "features": feats,
        "keywords": keywords,
        "queries": queries,
        "statuses": statuses,
        "ranked": ranked,
        "top_similarity": top,
        "overlap_level": S.overlap_level(top),
        "novelty": S.novelty_assessment(ranked, feats, statuses),
        "feature_ideas": feature_ideas.generate(idea, feats),
        "suggestions": suggestions.generate(idea, feats, ranked),
        "disclaimer": S.DISCLAIMER,
        "settings": {"per_source": per_source, "enabled": enabled, "thorough": thorough},
    }
    result["prior_work"] = priorwork.analyze(result)
    return result


def papers(result):
    return [d for d in result["ranked"] if d["kind"] == "paper"]


def patents(result):
    return [d for d in result["ranked"] if d["kind"] == "patent"]


def patent_summary(result):
    """('found', n) | ('none', 0) sources answered but nothing matched | ('unavailable', 0) no source answered."""
    n = len(patents(result))
    if n:
        return "found", n
    live = [s for s in result["statuses"] if s.get("kind") == "patent" and s.get("state") != "skipped"
            and s["source"] != "User import"]
    return ("none", 0) if any(s["ok"] for s in live) else ("unavailable", 0)


def add_documents(result, new_docs, statuses=None):
    """Return a NEW result (new run_id) with extra documents merged, re-ranked and re-suggested.
    `statuses`: fresh status rows that replace older rows of the same source (used by patent retry)."""
    base = [dict(d) for d in result["ranked"]]
    merged = sources.dedupe(base + list(new_docs))
    out = copy.deepcopy(result)
    out["run_id"] = uuid.uuid4().hex[:8]
    out["generated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    out["ranked"] = S.rank(out["idea"], out["features"], merged)
    out["top_similarity"] = out["ranked"][0]["similarity"] if out["ranked"] else 0.0
    out["overlap_level"] = S.overlap_level(out["top_similarity"])
    out["novelty"] = S.novelty_assessment(out["ranked"], out["features"], out["statuses"])
    out["suggestions"] = suggestions.generate(out["idea"], out["features"], out["ranked"])
    if statuses is None:
        out["statuses"] = out["statuses"] + [{"source": "User import", "kind": "patent", "ok": True, "state": "ok",
                                              "count": len(new_docs), "seconds": 0.0,
                                              "message": "records supplied by the user"}]
    else:
        names = {s["source"] for s in statuses}
        out["statuses"] = [s for s in out["statuses"] if s["source"] not in names] + list(statuses)
    out["prior_work"] = priorwork.analyze(out)
    return out


def retry_patents(result, enabled=None, per_source=10, mailto="", lens_token="", search_fn=None):
    """Re-query ONLY the patent sources and merge what comes back into the current analysis."""
    enabled = list(sources.DEFAULT_ENABLED if enabled is None else enabled)
    if lens_token and "Lens.org" not in enabled:
        enabled.append("Lens.org")
    pat = [s for s in enabled if sources.REGISTRY.get(s, {}).get("kind") == "patent"]
    if not pat:
        raise ValueError("No patent source is enabled in Settings.")
    docs, st = (search_fn or sources.search_all)(result["queries"], enabled=pat, per_source=per_source, mailto=mailto,
                                                 lens_token=lens_token, thorough=False)
    return add_documents(result, docs, statuses=st)
