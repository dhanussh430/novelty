"""'Who has worked on this before?' - a worldwide analysis built ONLY from the documents actually retrieved."""
from collections import Counter

from . import similarity as S

COUNTRIES = {
    "US": "United States", "CN": "China", "IN": "India", "GB": "United Kingdom", "DE": "Germany", "FR": "France",
    "JP": "Japan", "KR": "South Korea", "CA": "Canada", "AU": "Australia", "IT": "Italy", "ES": "Spain",
    "NL": "Netherlands", "BR": "Brazil", "RU": "Russia", "SE": "Sweden", "CH": "Switzerland", "SG": "Singapore",
    "TW": "Taiwan", "HK": "Hong Kong", "IR": "Iran", "TR": "Turkey", "PL": "Poland", "BE": "Belgium", "DK": "Denmark",
    "NO": "Norway", "FI": "Finland", "AT": "Austria", "IL": "Israel", "SA": "Saudi Arabia", "AE": "United Arab Emirates",
    "EG": "Egypt", "ZA": "South Africa", "MX": "Mexico", "PT": "Portugal", "GR": "Greece", "IE": "Ireland",
    "NZ": "New Zealand", "MY": "Malaysia", "PK": "Pakistan", "BD": "Bangladesh", "TH": "Thailand", "ID": "Indonesia",
    "VN": "Vietnam", "CZ": "Czechia", "HU": "Hungary", "UA": "Ukraine", "RO": "Romania", "LK": "Sri Lanka",
}


def _top(counter, n):
    return [(k, c) for k, c in counter.most_common(n)]


def analyze(result: dict, top_n: int = 15) -> dict:
    ranked = result.get("ranked", [])
    if not ranked:
        return {"available": False, "paragraphs": [
            "No documents were retrieved, so there is nothing to analyse yet. Check your internet connection, press Analyze "
            "again, or broaden the description."]}
    rel = ranked[:top_n]
    papers = [d for d in ranked if d["kind"] == "paper"]
    patents = [d for d in ranked if d["kind"] == "patent"]
    srcs = sorted({d["source"] for d in ranked})
    dated = [d for d in rel if d.get("year")]
    earliest = min(dated, key=lambda d: (d["year"], -d["similarity"])) if dated else None
    latest = max(dated, key=lambda d: (d["year"], d["similarity"])) if dated else None
    authors = Counter(a.strip() for d in rel for a in d["authors"] if a and a.strip())
    insts = Counter(i for d in rel for i in d.get("institutions", []))
    countries = Counter(COUNTRIES.get(c, c) for d in rel for c in d.get("countries", []))
    venues = Counter(d["venue"] for d in rel if d.get("venue"))
    timeline = dict(sorted(Counter(d["year"] for d in ranked if d.get("year")).items()))
    closest = ranked[:5]

    P = [f"**Scope:** {len(ranked)} documents were analysed ({len(papers)} research papers, {len(patents)} patents) from "
         f"{len(srcs)} sources: {', '.join(srcs)}."]
    if earliest:
        who = ", ".join(earliest["authors"][:3]) or "authors not listed"
        P.append(f"**Earliest closely related work found:** \"{earliest['title']}\" ({earliest['year']}) by {who} "
                 f"[{earliest['source']}]. This suggests work in this area has existed since at least {earliest['year']}.")
    if latest and latest is not earliest:
        P.append(f"**Most recent closely related work found:** \"{latest['title']}\" ({latest['year']}) [{latest['source']}].")
    P.append("**Closest existing work (by text similarity):** " + " ".join(
        f"{i}) \"{d['title'][:90]}\" ({d['year'] or 'n/a'}, {d['similarity']}%)." for i, d in enumerate(closest[:3], 1)))
    if countries:
        P.append("**Countries active in this area (from author affiliations):** " + ", ".join(f"{k} ({v})" for k, v in _top(countries, 6)) + ".")
    if insts:
        P.append("**Institutions involved:** " + "; ".join(k for k, _ in _top(insts, 6)) + ".")
    repeat = [(a, c) for a, c in _top(authors, 6) if c >= 2]
    if repeat:
        P.append("**Researchers appearing in several close documents:** " + ", ".join(f"{a} ({c})" for a, c in repeat) + ".")
    elif closest:
        P.append("**Authors of the closest works:** " + "; ".join(", ".join(d["authors"][:2]) or "n/a" for d in closest[:3]) + ".")
    if timeline:
        peak = max(timeline, key=timeline.get)
        P.append(f"**Activity over time:** documents span {min(timeline)}-{max(timeline)}; the busiest year was {peak} "
                 f"({timeline[peak]} documents).")
    P.append(f"**What this means for your project:** {S.overlap_level(ranked[0]['similarity'])}. This is a text-based "
             "reading of the retrieved documents, not a legal opinion; confirm with the patent databases listed below.")
    if not patents:
        P.append("**Patents:** no patent records were retrieved automatically, so the analysis above is based on research literature. "
                 "Use the official patent databases below to confirm whether this idea is already patented anywhere in the world.")
    return {"available": True, "paragraphs": P, "n_docs": len(ranked), "n_papers": len(papers), "n_patents": len(patents),
            "sources": srcs, "earliest": earliest, "latest": latest, "closest": closest,
            "authors": _top(authors, 8), "institutions": _top(insts, 8), "countries": _top(countries, 8),
            "venues": _top(venues, 6), "timeline": timeline}
