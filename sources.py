"""Live search of research papers and patents. Sources run IN PARALLEL and every failure is reported, never raised.

Papers : OpenAlex, Crossref, Semantic Scholar, arXiv, Europe PMC, DOAJ, Zenodo   (all keyless)
Patents: Google Patents (keyless, unofficial), Europe PMC patents (keyless, life-science focus),
         Lens.org (optional token)
NOTE: the PatentsView API was shut down by the USPTO on 20 March 2026 and is intentionally not used.
No sample/fabricated records exist anywhere in this module.
"""
import html
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FutTimeout
from urllib.parse import quote, quote_plus

import requests

TIMEOUT = (6, 12)          # (connect, read) seconds per request
CACHE_TTL = 1800           # seconds a successful result is reused
UA = "AI-Novelty-Analyzer/2.0"
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/124.0 Safari/537.36")
_CACHE = {}


class SourceError(Exception):
    pass


def clear_cache():
    _CACHE.clear()


def friendly(err: str) -> str:
    """Turn raw technical errors into readable explanations."""
    e = err or ""
    if "HTTP 503" in e:
        return "Temporarily unavailable (HTTP 503: the service is overloaded or throttling automated requests; retry in a minute)"
    if "HTTP 429" in e:
        return "Rate-limited (HTTP 429: too many requests; retry shortly)"
    if "HTTP 403" in e or "HTTP 401" in e:
        return f"Access refused ({e}): the service blocks automated requests or needs credentials"
    if "HTTP 404" in e:
        return "Endpoint not found (HTTP 404)"
    if "Timeout" in e or "timed out" in e:
        return "Timed out waiting for the service"
    if "ConnectionError" in e or "Connection aborted" in e or "NameResolution" in e:
        return "Network connection failed or was aborted (check internet / firewall)"
    return e[:160]


def _clean(text) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", str(text))
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _get(url, params=None, headers=None, retries=1):
    """GET with fast failure: only connection-level errors are retried; HTTP errors fail immediately."""
    last = "unknown error"
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=TIMEOUT)
        except requests.RequestException as e:
            last = f"{type(e).__name__}: {e}"
            if attempt < retries:
                time.sleep(0.3)
            continue
        if r.status_code >= 400:
            raise SourceError(f"HTTP {r.status_code}")
        return r
    raise SourceError(last)


def _json(r):
    try:
        return r.json()
    except ValueError:
        raise SourceError("response was not valid JSON (the service may be blocking automated requests)")


def _year(value):
    m = re.match(r"\s*(\d{4})", str(value or ""))
    return int(m.group(1)) if m else None


def _doc(kind, title, authors, year, abstract, url, identifier, source, venue=""):
    return {
        "kind": kind, "title": _clean(title) or "(untitled)", "authors": [a for a in authors if a],
        "year": year if isinstance(year, int) else None, "abstract": _clean(abstract), "url": url or "",
        "identifier": identifier or "", "source": source, "venue": _clean(venue),
    }


# ================================================================ PAPERS
def rebuild_abstract(inverted):
    if not inverted:
        return ""
    pos = {}
    for word, idxs in inverted.items():
        for i in idxs:
            pos[i] = word
    return " ".join(pos[i] for i in sorted(pos))


def parse_openalex(data) -> list:
    out = []
    for w in (data or {}).get("results", []) or []:
        doi = (w.get("doi") or "").replace("https://doi.org/", "")
        loc = w.get("primary_location") or {}
        url = (w.get("doi") or loc.get("landing_page_url") or w.get("id") or "")
        auths = w.get("authorships", []) or []
        authors = [(a.get("author") or {}).get("display_name", "") for a in auths]
        venue = ((loc.get("source") or {}).get("display_name")) or ""
        insts, countries = [], []
        for a in auths:
            for i in a.get("institutions", []) or []:
                if i.get("display_name"):
                    insts.append(i["display_name"])
                if i.get("country_code"):
                    countries.append(i["country_code"])
            countries.extend(a.get("countries", []) or [])
        d = _doc("paper", w.get("display_name") or w.get("title"), authors, w.get("publication_year"),
                 rebuild_abstract(w.get("abstract_inverted_index")), url, doi, "OpenAlex", venue)
        d["institutions"] = list(dict.fromkeys(insts))
        d["countries"] = list(dict.fromkeys(countries))
        out.append(d)
    return out


def search_openalex(query, limit, ctx):
    params = {"search": query, "per-page": max(1, min(limit, 50))}
    if ctx.get("mailto"):
        params["mailto"] = ctx["mailto"]
    return parse_openalex(_json(_get("https://api.openalex.org/works", params=params, headers={"User-Agent": UA})))


def parse_crossref(data) -> list:
    out = []
    for it in ((data or {}).get("message") or {}).get("items", []) or []:
        title = (it.get("title") or [""])[0]
        authors = [" ".join(x for x in (a.get("given"), a.get("family")) if x) or a.get("name", "")
                   for a in it.get("author", []) or []]
        parts = ((it.get("issued") or {}).get("date-parts") or [[None]])[0]
        year = parts[0] if parts and isinstance(parts[0], int) else None
        doi = it.get("DOI", "")
        out.append(_doc("paper", title, authors, year, it.get("abstract", ""),
                        it.get("URL") or (f"https://doi.org/{doi}" if doi else ""), doi, "Crossref",
                        (it.get("container-title") or [""])[0]))
    return out


def search_crossref(query, limit, ctx):
    mailto = ctx.get("mailto", "")
    params = {"query": query, "rows": max(1, min(limit, 50)),
              "select": "DOI,title,author,issued,abstract,URL,container-title"}
    if mailto:
        params["mailto"] = mailto
    return parse_crossref(_json(_get("https://api.crossref.org/works", params=params,
                                     headers={"User-Agent": f"{UA} (mailto:{mailto or 'none'})"})))


def parse_semantic_scholar(data) -> list:
    out = []
    for p in (data or {}).get("data", []) or []:
        doi = (p.get("externalIds") or {}).get("DOI", "")
        out.append(_doc("paper", p.get("title"), [a.get("name", "") for a in p.get("authors", []) or []],
                        p.get("year"), p.get("abstract"), p.get("url") or (f"https://doi.org/{doi}" if doi else ""),
                        doi, "Semantic Scholar", p.get("venue") or ""))
    return out


def search_semantic_scholar(query, limit, ctx):
    params = {"query": query, "limit": max(1, min(limit, 50)),
              "fields": "title,abstract,year,authors,externalIds,url,venue"}
    return parse_semantic_scholar(_json(_get("https://api.semanticscholar.org/graph/v1/paper/search",
                                             params=params, headers={"User-Agent": UA}, retries=0)))


_ATOM = {"a": "http://www.w3.org/2005/Atom"}


def parse_arxiv(xml_text) -> list:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise SourceError(f"invalid XML from arXiv: {e}")
    out = []
    for e in root.findall("a:entry", _ATOM):
        link = (e.findtext("a:id", "", _ATOM) or "").strip()
        authors = [(a.findtext("a:name", "", _ATOM) or "").strip() for a in e.findall("a:author", _ATOM)]
        out.append(_doc("paper", e.findtext("a:title", "", _ATOM), authors, _year(e.findtext("a:published", "", _ATOM)),
                        e.findtext("a:summary", "", _ATOM), link, link.rsplit("/abs/", 1)[-1], "arXiv", "arXiv preprint"))
    return out


def search_arxiv(query, limit, ctx):
    q = " AND ".join(f"all:{w}" for w in query.split()[:3])
    params = {"search_query": q, "max_results": max(1, min(limit, 50)), "sortBy": "relevance"}
    return parse_arxiv(_get("https://export.arxiv.org/api/query", params=params, headers={"User-Agent": UA}).text)


def parse_europepmc(data) -> list:
    out = []
    for r in ((data or {}).get("resultList") or {}).get("result", []) or []:
        src, rid = r.get("source", ""), r.get("id", "")
        if not rid:
            continue
        is_pat = src == "PAT"
        authors = [a.strip(" .") for a in (r.get("authorString") or "").split(",")][:6]
        doi = r.get("doi", "")
        url = f"https://europepmc.org/article/{src}/{rid}"
        out.append(_doc("patent" if is_pat else "paper", r.get("title"), authors, _year(r.get("pubYear")),
                        r.get("abstractText"), url, rid if is_pat else (doi or rid),
                        "Europe PMC Patents" if is_pat else "Europe PMC", r.get("journalTitle") or ""))
    return out


def _epmc(query, limit, flt):
    params = {"query": f"({query}) {flt}", "format": "json", "resultType": "core", "pageSize": max(1, min(limit, 100))}
    return parse_europepmc(_json(_get("https://www.ebi.ac.uk/europepmc/webservices/rest/search", params=params,
                                      headers={"User-Agent": UA})))


def search_europepmc(query, limit, ctx):
    return _epmc(query, limit, "NOT SRC:PAT")


def search_europepmc_patents(query, limit, ctx):
    return _epmc(query, limit, "AND SRC:PAT")


def parse_doaj(data) -> list:
    out = []
    for r in (data or {}).get("results", []) or []:
        b = r.get("bibjson") or {}
        doi = next((i.get("id", "") for i in b.get("identifier", []) or [] if (i.get("type") or "").lower() == "doi"), "")
        url = next((l.get("url", "") for l in b.get("link", []) or [] if l.get("url")), "") or (f"https://doi.org/{doi}" if doi else "")
        out.append(_doc("paper", b.get("title"), [a.get("name", "") for a in b.get("author", []) or []], _year(b.get("year")),
                        b.get("abstract"), url, doi, "DOAJ", (b.get("journal") or {}).get("title", "")))
    return out


def search_doaj(query, limit, ctx):
    r = _get("https://doaj.org/api/search/articles/" + quote(query, safe=""),
             params={"pageSize": max(1, min(limit, 100))}, headers={"User-Agent": UA})
    return parse_doaj(_json(r))


def parse_zenodo(data) -> list:
    out = []
    for h in ((data or {}).get("hits") or {}).get("hits", []) or []:
        m = h.get("metadata") or {}
        out.append(_doc("paper", m.get("title"), [c.get("name", "") for c in m.get("creators", []) or []],
                        _year(m.get("publication_date")), m.get("description"),
                        (h.get("links") or {}).get("html", ""), m.get("doi") or h.get("doi", ""), "Zenodo", "Zenodo"))
    return out


def search_zenodo(query, limit, ctx):
    params = {"q": query, "size": max(1, min(limit, 100)), "type": "publication", "sort": "bestmatch"}
    return parse_zenodo(_json(_get("https://zenodo.org/api/records", params=params, headers={"User-Agent": UA}, retries=0)))


# ================================================================ PATENTS
def search_google_patents(query, limit, ctx):
    from . import patent_search          # imported lazily (patent_search itself imports helpers from this module)
    return patent_search.search_google_patents(query, limit, ctx)


def parse_lens(data) -> list:
    out = []
    for p in (data or {}).get("data", []) or []:
        b = p.get("biblio") or {}
        title = next((t.get("text", "") for t in b.get("invention_title", []) or [] if t.get("lang") == "en"), "") or \
            next((t.get("text", "") for t in b.get("invention_title", []) or []), "")
        abstract = next((a.get("text", "") for a in p.get("abstract", []) or []), "")
        inv = [((i.get("extracted_name") or {}).get("value", "")) for i in (b.get("parties") or {}).get("inventors", []) or []]
        num = f"{p.get('jurisdiction', '')}{p.get('doc_number', '')}{p.get('kind', '')}"
        out.append(_doc("patent", title, inv[:5], _year(p.get("date_published")), abstract,
                        f"https://www.lens.org/lens/patent/{p.get('lens_id', '')}", num, "Lens.org"))
    return out


def search_lens(query, limit, ctx):
    import json
    body = {"query": {"query_string": {"query": query, "fields": ["title", "abstract"], "default_operator": "or"}},
            "size": max(1, min(limit, 100)),
            "include": ["lens_id", "jurisdiction", "doc_number", "kind", "date_published", "biblio", "abstract"]}
    try:
        r = requests.post("https://api.lens.org/patent/search", data=json.dumps(body), timeout=TIMEOUT,
                          headers={"Authorization": f"Bearer {ctx.get('lens_token', '')}", "Content-Type": "application/json", "User-Agent": UA})
    except requests.RequestException as e:
        raise SourceError(f"{type(e).__name__}: {e}")
    if r.status_code >= 400:
        raise SourceError(f"HTTP {r.status_code}")
    return parse_lens(_json(r))


# ================================================================ REGISTRY + orchestration
def _words(n):
    return lambda q: " ".join(q.split()[:n])


# order = display order. "multi": max queries in thorough mode. "prep": query shaping per source.
REGISTRY = {
    "OpenAlex":         {"kind": "paper",  "fn": search_openalex,         "multi": 3},
    "Crossref":         {"kind": "paper",  "fn": search_crossref,         "multi": 3},
    "Semantic Scholar": {"kind": "paper",  "fn": search_semantic_scholar, "multi": 2},
    "arXiv":            {"kind": "paper",  "fn": search_arxiv,            "multi": 2, "prep": _words(3)},
    "Europe PMC":       {"kind": "paper",  "fn": search_europepmc,        "multi": 2},
    "DOAJ":             {"kind": "paper",  "fn": search_doaj,             "multi": 2},
    "Zenodo":           {"kind": "paper",  "fn": search_zenodo,           "multi": 2},
    "Google Patents":   {"kind": "patent", "fn": search_google_patents,   "multi": 1, "prep": _words(4)},
    "Europe PMC Patents": {"kind": "patent", "fn": search_europepmc_patents, "multi": 2, "prep": _words(3)},
    "Lens.org":         {"kind": "patent", "fn": search_lens,             "multi": 1, "needs": "lens_token"},
}
DEFAULT_ENABLED = [n for n, s in REGISTRY.items() if not s.get("needs")]


def names(kind):
    return [n for n, s in REGISTRY.items() if s["kind"] == kind and not s.get("needs")]


def _norm_title(t):
    return re.sub(r"[^a-z0-9]", "", (t or "").lower())


def dedupe(docs) -> list:
    best = {}
    for d in docs:
        key = (d["kind"], (d["identifier"] or "").lower() or _norm_title(d["title"]))
        cur = best.get(key)
        if cur is None or len(d["abstract"]) > len(cur["abstract"]):
            best[key] = d
    by_title = {}
    for d in best.values():
        k = (d["kind"], _norm_title(d["title"]))
        if k not in by_title or len(d["abstract"]) > len(by_title[k]["abstract"]):
            by_title[k] = d
    return list(by_title.values())


def _run_job(name, query, per_source, ctx):
    """Returns (docs, note, error, seconds, from_cache)."""
    spec = REGISTRY[name]
    q = spec["prep"](query) if spec.get("prep") else query
    key = (name, q, per_source)
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < CACHE_TTL:
        return hit[1][0], hit[1][1], None, 0.0, True
    t0 = time.time()
    try:
        res = spec["fn"](q, per_source, ctx)
        docs, note = res if isinstance(res, tuple) else (res, None)
        _CACHE[key] = (time.time(), (docs, note))
        return docs, note, None, time.time() - t0, False
    except SourceError as e:
        return [], None, str(e), time.time() - t0, False
    except Exception as e:  # never crash the app
        return [], None, f"{type(e).__name__}: {e}", time.time() - t0, False


def search_all(queries, enabled=None, per_source=10, mailto="", lens_token="", thorough=False, deadline=25):
    """Run every (source, query) job in parallel. Returns (documents, statuses)."""
    enabled = list(DEFAULT_ENABLED if enabled is None else enabled)
    ctx = {"mailto": mailto, "lens_token": lens_token}
    queries = [q for q in queries if q]
    jobs, statuses = [], {}
    single = [queries[1] if len(queries) > 1 else queries[0]] if queries else []
    for name, spec in REGISTRY.items():
        if name not in enabled:
            continue
        if spec.get("needs") and not ctx.get(spec["needs"]):
            statuses[name] = {"source": name, "kind": spec["kind"], "ok": False, "state": "skipped", "count": 0,
                              "seconds": 0.0, "message": "skipped (optional token not provided)"}
            continue
        qs = queries[:spec["multi"]] if thorough else single
        for q in qs:
            jobs.append((name, q))
    results = {n: {"docs": [], "errors": [], "notes": [], "ok": 0, "jobs": 0, "sec": 0.0} for n, _ in jobs}
    all_docs = []
    if jobs:
        ex = ThreadPoolExecutor(max_workers=min(16, len(jobs)))
        futs = {ex.submit(_run_job, n, q, per_source, ctx): (n, q) for n, q in jobs}
        done = set()
        try:
            for f in as_completed(futs, timeout=deadline):
                done.add(f)
                n, _ = futs[f]
                docs, note, err, sec, _cached = f.result()
                r = results[n]
                r["jobs"] += 1
                r["sec"] = max(r["sec"], sec)
                if err:
                    r["errors"].append(friendly(err))
                else:
                    r["ok"] += 1
                    r["docs"].extend(docs)
                    if note:
                        r["notes"].append(note)
        except FutTimeout:
            pass
        for f, (n, _) in futs.items():
            if f not in done:
                results[n]["jobs"] += 1
                results[n]["errors"].append("Timed out waiting for the service")
                results[n]["sec"] = float(deadline)
        ex.shutdown(wait=False, cancel_futures=True)
    for name, spec in REGISTRY.items():
        if name not in results:
            continue
        r = results[name]
        n_docs = len(r["docs"])
        all_docs.extend(r["docs"])
        errs = sorted(set(r["errors"]))
        if r["ok"] == 0:
            state, msg = "failed", "; ".join(errs) or "no response"
        elif errs:
            state, msg = "partial", "partial: " + "; ".join(errs)
        else:
            notes = "; ".join(sorted(set(r["notes"])))
            state = "ok"
            if n_docs:
                msg = "OK" + (f" ({notes})" if notes else "")
            else:
                msg = notes or "Connected, but no matching records for these search terms"
        statuses[name] = {"source": name, "kind": spec["kind"], "ok": r["ok"] > 0, "state": state,
                          "count": n_docs, "seconds": round(r["sec"], 1), "message": msg}
    ordered = [statuses[n] for n in REGISTRY if n in statuses]
    return dedupe(all_docs), ordered


# ================================================================ user-supplied patents (real data, never invented)
PATENT_DATABASES = [
    # name, region, URL ({q} = your search terms where the site supports it), note
    ("Google Patents", "Worldwide", "https://patents.google.com/?q={q}", "Full-text search across many patent offices; free"),
    ("Espacenet (European Patent Office)", "Worldwide", "https://worldwide.espacenet.com/patent/search?q={q}", "Official EPO database of worldwide patent documents"),
    ("WIPO PATENTSCOPE", "Worldwide", "https://patentscope.wipo.int/search/en/search.jsf", "Official WIPO database, includes international (PCT) applications"),
    ("The Lens", "Worldwide", "https://www.lens.org/lens/search/patent/list?q={q}", "Free patent and scholarly search with legal-status data"),
    ("FreePatentsOnline", "Worldwide", "https://www.freepatentsonline.com/result.html?query_txt={q}", "Free full-text search of US and European patents"),
    ("USPTO Patent Public Search", "United States", "https://ppubs.uspto.gov/pubwebapp/", "Official US Patent and Trademark Office search"),
    ("InPASS - Indian Patent Office", "India", "https://iprsearch.ipindia.gov.in/publicsearch", "Official Indian Patent Advanced Search System"),
    ("DEPATISnet (German Patent Office)", "Germany", "https://depatisnet.dpma.de/", "Official DPMA database"),
    ("J-PlatPat (Japan Patent Office)", "Japan", "https://www.j-platpat.inpit.go.jp/", "Official Japanese patent platform"),
    ("KIPRIS (Korean IP Office)", "South Korea", "https://www.kipris.or.kr/", "Official Korean IP search service"),
    ("CNIPA Patent Search", "China", "https://pss-system.cponline.cnipa.gov.cn/", "Official Chinese patent search and analysis system"),
    ("AusPat (IP Australia)", "Australia", "https://pericles.ipaustralia.gov.au/ols/auspat/", "Official Australian patent search"),
    ("Canadian Patents Database (CIPO)", "Canada", "https://www.ic.gc.ca/opic-cipo/cpd/eng/introduction.html", "Official Canadian patent database"),
]


def patent_search_links(queries) -> list:
    """Official / established patent databases, with your search terms pre-filled where the site supports it."""
    terms = " ".join(queries[1].split()[:4]) if len(queries) > 1 else (queries[0] if queries else "")
    q = quote_plus(terms)
    return [{"name": n, "region": r, "url": u.replace("{q}", q), "note": note, "prefilled": "{q}" in u}
            for n, r, u, note in PATENT_DATABASES]


def make_patent(number, title, abstract="", url="", assignee="", date=""):
    number = (number or "").strip()
    if not (number or (title or "").strip()):
        raise ValueError("A patent number or title is required.")
    link = url.strip() or (f"https://patents.google.com/patent/{number.replace(' ', '')}/en" if number else "")
    return _doc("patent", title or number, [assignee] if assignee else [], _year(date), abstract, link, number,
                "User import", assignee)


def parse_patent_csv(text) -> list:
    """Parse a Google Patents 'Download (CSV)' export or any CSV with id/title(/abstract/assignee/date/link) columns."""
    import csv
    import io
    lines = (text or "").lstrip("\ufeff").splitlines()
    start = next((i for i, l in enumerate(lines[:15]) if "title" in l.lower() and ("id" in l.lower() or "number" in l.lower())), None)
    if start is None:
        raise ValueError("Could not find a header row with 'id' and 'title' columns.")
    rows = csv.DictReader(io.StringIO("\n".join(lines[start:])))

    def pick(row, *names):
        low = {(k or "").strip().lower(): v for k, v in row.items()}
        for n in names:
            if low.get(n):
                return low[n].strip()
        return ""
    out = []
    for row in rows:
        num = pick(row, "id", "publication number", "number", "patent number")
        title = pick(row, "title")
        if not (num or title):
            continue
        out.append(make_patent(num, title, pick(row, "abstract"), pick(row, "result link", "link", "url"),
                               pick(row, "assignee"), pick(row, "publication date", "date", "filing/creation date")))
    return out
