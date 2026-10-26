"""Google Patents search - adapted from the project owner's own search code.

Differences kept on purpose: (1) pure-Python TF-IDF (same formula as scikit-learn, no extra dependency) and
(2) a failed search is reported as a status/notice - it never creates a fake "patent" row.
"""
import json
import math
import re
import time
from collections import Counter
from html import unescape
from urllib.parse import quote, urlencode

import requests

from .sources import TIMEOUT, SourceError, _doc, _year

HEADERS = {
    "User-Agent": "Mozilla/5.0 AI-Novelty-Analyzer/1.0",
    "Accept": "application/json, text/plain, */*",
}
STOPWORDS = {
    "a", "an", "the", "for", "using", "with", "and", "or", "of", "to", "in", "on", "by", "based", "system",
    "method", "solution", "new", "improved", "that", "this", "from",
}
# compact English stop-word list (used only by the TF-IDF part of the relevance score)
ENGLISH_STOP = set("""a about above after again against all am an and any are as at be because been before being below between
both but by can could did do does doing down during each few for from further had has have having he her here hers him his
how i if in into is it its itself just me more most my no nor not of off on once only or other our out over own same she should
so some such than that the their them then there these they this those through to too under until up very was we were what when
where which while who whom why will with would you your""".split())
MIN_RELEVANCE = 12.0
_TOKEN = re.compile(r"(?u)\b\w\w+\b")


def clean(value):
    if not value:
        return ""
    if isinstance(value, dict):
        value = value.get("value", "")
    if isinstance(value, list):
        value = " ".join(str(x) for x in value)
    value = re.sub(r"<[^>]+>", " ", str(value))
    return " ".join(unescape(value).split())


def get_value(item, *keys):
    for key in keys:
        if item.get(key):
            return clean(item[key])
    return ""


def important_terms(text):
    words = re.findall(r"[a-zA-Z0-9]+", (text or "").lower())
    return [w for w in words if w not in STOPWORDS and len(w) > 1]


def build_search_query(query):
    """Keep distinctive terms (e.g. n8n), drop generic words, remove duplicates."""
    terms = important_terms(query)
    if not terms:
        return (query or "").strip()
    return " ".join(dict.fromkeys(terms))


def _grams(text):
    toks = [t for t in _TOKEN.findall((text or "").lower()) if t not in ENGLISH_STOP]
    return Counter(toks + [f"{a} {b}" for a, b in zip(toks, toks[1:])])


def _pair_tfidf(a, b):
    """Cosine of TF-IDF vectors (unigrams+bigrams, smooth idf, l2 norm) fitted on the two texts."""
    ca, cb = _grams(a), _grams(b)
    if not ca or not cb:
        return 0.0
    idf = {w: math.log(3 / (1 + (w in ca) + (w in cb))) + 1 for w in set(ca) | set(cb)}
    va = {w: c * idf[w] for w, c in ca.items()}
    vb = {w: c * idf[w] for w, c in cb.items()}
    na = math.sqrt(sum(x * x for x in va.values()))
    nb = math.sqrt(sum(x * x for x in vb.values()))
    return sum(x * vb.get(w, 0.0) for w, x in va.items()) / (na * nb) if na and nb else 0.0


def relevance_score(query, patent):
    """65% important-keyword coverage + 35% TF-IDF similarity (ranking heuristic, not a legal score)."""
    title = clean(patent.get("title", ""))
    desc = clean(patent.get("snippet", "") or patent.get("abstract", "") or patent.get("description", ""))
    text = f"{title} {desc}".lower()
    terms = set(important_terms(query))
    if not text.strip() or not terms:
        return 0.0
    coverage = sum(1 for t in terms if t in text) / len(terms)
    return round((0.65 * coverage + 0.35 * _pair_tfidf(query, text)) * 100, 2)


def endpoint(focused_query, num):
    inner = urlencode({"q": focused_query, "num": num, "page": 1})
    return "https://patents.google.com/xhr/query?url=" + quote(inner, safe="") + "&exp="


def extract_raw_patents(data):
    """Understand every response shape Google has been seen to return."""
    if isinstance(data, str):
        data = json.loads(data)
    if not isinstance(data, dict):
        raise ValueError("Unexpected response format.")
    if isinstance(data.get("content"), str):
        try:
            data = json.loads(data["content"])
        except (ValueError, TypeError):
            pass
    results = data.get("results", {})
    if isinstance(results, str):
        try:
            results = json.loads(results)
        except (ValueError, TypeError):
            results = {}
    raw = []
    if isinstance(results, dict):
        for cluster in results.get("cluster", []) or []:
            if not isinstance(cluster, dict):
                continue
            for entry in cluster.get("result", []) or []:
                patent = entry.get("patent", {}) if isinstance(entry, dict) else {}
                if isinstance(patent, dict) and patent:
                    raw.append(patent)
    elif isinstance(results, list):
        raw.extend(p for p in results if isinstance(p, dict))
    return raw


def fetch_raw(focused_query, num):
    """One request, retried ONCE after 1 s on HTTP 429/503 or a transient network/format problem."""
    url = endpoint(focused_query, num)
    last = "no response"
    for attempt in range(2):
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code in (429, 503):
                last = f"HTTP {r.status_code}"
                if attempt == 0:
                    time.sleep(1)
                    continue
                break
            if r.status_code >= 400:
                raise SourceError(f"HTTP {r.status_code}")
            return extract_raw_patents(r.json())
        except requests.RequestException as e:
            last = f"{type(e).__name__}: {e}"
        except (ValueError, TypeError):
            last = "response was not valid JSON (the service may be blocking automated requests)"
        if attempt == 0:
            time.sleep(1)
    raise SourceError(last)


def build_docs(raw, query, limit):
    """Raw Google records -> de-duplicated, relevance-filtered documents. Returns (docs, total_raw_unique)."""
    out, seen = [], set()
    for p in raw:
        num = get_value(p, "publication_number", "publicationNumber", "id")
        title = get_value(p, "title")
        if not title:
            continue
        key = num or title.lower()
        if key in seen:
            continue
        seen.add(key)
        snippet = get_value(p, "snippet", "abstract", "description")
        inventor = get_value(p, "inventor", "inventors")
        assignee = get_value(p, "assignee", "assignees")
        pub = get_value(p, "publication_date", "publicationDate")
        prio = get_value(p, "priority_date", "priorityDate")
        filed = get_value(p, "filing_date", "filingDate")
        url = (f"https://patents.google.com/patent/{quote(num, safe='')}/en" if num
               else f"https://patents.google.com/?q={quote(query)}")
        d = _doc("patent", title, [inventor] if inventor else [], _year(pub or prio or filed), snippet, url, num,
                 "Google Patents", assignee)
        d.update({"assignee": assignee, "publication_date": pub, "filing_date": filed, "priority_date": prio,
                  "relevance": relevance_score(query, {"title": title, "snippet": snippet})})
        out.append(d)
    out.sort(key=lambda d: -d["relevance"])
    return [d for d in out if d["relevance"] >= MIN_RELEVANCE][:limit], len(out)


def search_google_patents(query, limit, ctx):
    """Returns (documents, note). Raises SourceError when Google cannot be reached."""
    focused = build_search_query(query)
    if not focused:
        return [], None
    words = focused.split()
    num = min(max(int(limit), 1) * 3, 75)
    raw, used = [], focused
    for q in ([focused] + ([" ".join(words[:3])] if len(words) > 3 else [])):
        raw, used = fetch_raw(q, num), q
        if raw:
            break
    if not raw:
        return [], None
    docs, total = build_docs(raw, used, limit)
    if not docs:
        return [], (f"returned {total} records but none passed the relevance threshold "
                    "(this does not mean no relevant patents exist)")
    if total > len(docs):
        return docs, f"{total} records returned, {len(docs)} passed the relevance filter"
    return docs, None
