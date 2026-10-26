"""Rule-based innovation suggestions. Everything derived from heuristics is flagged for verification."""
from collections import Counter

from .features import stem, stems, tokenize

DOMAIN_IDEAS = [
    (("sensor", "iot", "monitor", "track", "detect"), [
        ("Multi-sensor fusion with self-calibration", "Combining several signal types and compensating drift can improve accuracy and set the design apart from single-sensor approaches."),
        ("Edge-side anomaly detection", "Processing locally reduces latency, bandwidth and privacy exposure; check whether prior art already claims on-device analysis for this use case.")]),
    (("learn", "neural", "predict", "model", "algorithm", "ai", "intelligen"), [
        ("Personalised / federated model adaptation", "Adapting the model per user without sending raw data centrally could be a distinguishing technical effect."),
        ("Explainable output with confidence scoring", "Reporting why a decision was made and how certain it is adds practical value and a possible technical differentiator.")]),
    (("battery", "energy", "solar", "power", "charg"), [
        ("Energy-harvesting or adaptive duty-cycling", "Dynamically lowering consumption based on context can be a concrete, measurable improvement.")]),
    (("app", "mobile", "software", "platform", "cloud", "dashboard"), [
        ("Closed-loop feedback with user-specific thresholds", "Linking sensing to automated, personalised actions (not just display) may add a functional step beyond reporting.")]),
    (("health", "patient", "medical", "wearable", "hydrat", "clinic"), [
        ("Clinical-grade validation protocol", "Evidence against a recognised reference method strengthens both product value and any technical-effect argument.")]),
    (("farm", "crop", "soil", "agricult", "irrigat", "plant"), [
        ("Weather- and soil-aware predictive scheduling", "Fusing local sensing with forecasts is a common but combination-specific improvement; verify the exact combination.")]),
    (("robot", "drone", "autonom", "vehicle"), [
        ("Fail-safe fallback behaviour with runtime self-checks", "Safety-oriented mechanisms are often claimable as distinct technical features.")]),
    (("blockchain", "ledger", "token", "crypto"), [
        ("Verifiable audit trail with privacy-preserving proofs", "Combining traceability with selective disclosure may differentiate from plain ledger storage.")]),
    (("water", "liquid", "fluid", "filter", "bottle"), [
        ("Contamination or quality sensing integrated with the core function", "Adding quality sensing to the main function can create a distinct combination; check existing patents.")]),
]

GENERAL = [
    ("Quantify key parameters", "State measurable ranges, thresholds or performance figures so the idea can be distinguished from prior art on concrete terms."),
    ("Document the technical problem and measured improvement", "Prototype data showing an improvement over the closest prior art supports any later inventive-step argument."),
    ("Keep dated records and avoid early public disclosure", "Record conception and prototype dates; public disclosure before filing can harm patentability in many jurisdictions."),
    ("Commission a professional search", "Use classification-based (CPC/IPC) and full-text searching, and consult a registered patent attorney before filing."),
]


def _hit(token: str, key: str) -> bool:
    """Short keys (ai, app, iot) must match whole words to avoid false positives like 'air'."""
    return token in (key, key + "s") if len(key) <= 3 else token.startswith(key)


def generate(idea: str, features: list, ranked: list, top_n: int = 10) -> list:
    out = []
    idea_stems = set(stems(idea))
    idea_tokens = tokenize(idea)

    # 1. Gaps: features poorly covered by retrieved documents
    top = ranked[:top_n]
    if top:
        for f in features:
            best = max((d["feature_scores"].get(f, 0.0) for d in top), default=0.0)
            if best < 0.5:
                out.append({"title": f"Possible differentiator: {f}", "type": "gap", "needs_verification": True,
                            "rationale": f"No retrieved document covered this feature strongly (best match {best:.0%}). "
                                         "Absence in a limited, abstract-level search is not proof of novelty - verify with a deeper search."})
    else:
        out.append({"title": "No documents were retrieved", "type": "gap", "needs_verification": True,
                    "rationale": "Differentiators cannot be inferred without results. Check source status, broaden wording, or search manually."})

    # 2. Terms common in prior art but missing from the idea
    cnt = Counter()
    for d in top:
        cnt.update(set(stems(f"{d['title']} {d.get('abstract', '')}")))
    common = [s for s, c in cnt.most_common(40) if c >= 2 and s not in idea_stems][:5]
    if common:
        out.append({"title": "Concepts frequent in prior art but absent from your description", "type": "prior-art terms",
                    "needs_verification": True,
                    "rationale": "Related documents repeatedly mention: " + ", ".join(common) +
                                 ". Decide whether to incorporate them or deliberately avoid/differentiate from them."})

    # 3. Domain-driven improvements
    n = 0
    for keys, ideas in DOMAIN_IDEAS:
        if any(_hit(t, k) for t in idea_tokens for k in keys):
            for title, why in ideas:
                if n < 6:
                    out.append({"title": title, "type": "domain idea", "needs_verification": True, "rationale": why})
                    n += 1

    # 4. Practical guidance (no verification needed)
    for title, why in GENERAL:
        out.append({"title": title, "type": "general practice", "needs_verification": False, "rationale": why})
    return out
