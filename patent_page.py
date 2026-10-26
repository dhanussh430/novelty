"""Fetch ONE patent from its Google Patents page (e.g. https://patents.google.com/patent/US9060213B2/en)
and extract real details: title, abstract, claims, inventors, assignee, dates, CPC classes, citations, similar documents.

Nothing is invented: if the page cannot be fetched or does not look like a patent page, a clear error is raised.
"""
import re
import time
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from . import sources
from .sources import SourceError

_DEPENDENT = re.compile(r"\b(?:of|in|to|by|with|from)\s+(?:any\s+(?:one\s+)?of\s+)?(?:the\s+)?(?:preceding\s+)?claims?\s+\d+|"
                        r"according to (?:any of )?claims?\s+\d+|as claimed in|as recited in claim|as defined in claim|"
                        r"as set forth in claim", re.I)
_CLAIM_START = re.compile(r"^\s*(\d{1,3})\s*[\.\)]\s+")


def normalize_ref(text: str):
    """Accept a Google Patents link or a publication number -> (NUMBER, canonical URL). Raises ValueError."""
    t = (text or "").strip().strip("<>\"'").rstrip(".,;")
    if not t:
        raise ValueError("Enter a Google Patents link or a publication number such as US9060213B2.")
    if re.match(r"https?://", t, re.I):
        u = urlparse(t)
        if (u.hostname or "").lower() != "patents.google.com":
            raise ValueError("Only patents.google.com links are supported.")
        m = re.search(r"/patent/([A-Za-z0-9]+)", u.path)
        if not m:
            raise ValueError("That link does not look like a Google Patents patent page (…/patent/US9060213B2/en).")
        num = m.group(1).upper()
    else:
        num = re.sub(r"[\s\-,/]", "", t).upper()
        if re.fullmatch(r"\d{6,9}", num):          # bare US number
            num = "US" + num
    if not re.fullmatch(r"[A-Z]{2}\d{4,}[A-Z0-9]{0,3}", num):
        raise ValueError("Could not read a publication number. Use a format like US9060213B2 or EP1234567A1.")
    return num, f"https://patents.google.com/patent/{num}/en"


def _txt(el):
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)) if el else ""


def _metas(soup, name, scheme=None):
    out = []
    for m in soup.find_all("meta", attrs={"name": name}):
        if scheme and (m.get("scheme") or "").lower() != scheme:
            continue
        if m.get("content"):
            out.append(m["content"].strip())
    return out


def _main(soup, itemprop):
    """Elements with this itemprop that are NOT inside a citation / similar-documents table row."""
    return [e for e in soup.find_all(attrs={"itemprop": itemprop}) if e.find_parent("tr") is None]


def _uniq(seq):
    seen, out = set(), []
    for x in seq:
        if x and x.lower() not in seen:
            seen.add(x.lower())
            out.append(x)
    return out


def _date(soup, itemprop, *meta_schemes):
    els = _main(soup, itemprop)
    if els:
        el = els[0]
        v = (el.get("datetime") or _txt(el))
        if v:
            return v.strip()
    for sch in meta_schemes:
        vals = _metas(soup, "DC.date", sch)
        if vals:
            return vals[0]
    return ""


def _related(soup, props):
    rows, seen = [], set()
    for prop in props:
        for tr in soup.find_all("tr", attrs={"itemprop": prop}):
            num = _txt(tr.find(attrs={"itemprop": "publicationNumber"}))
            if not num or num in seen:
                continue
            seen.add(num)
            rows.append({"number": num, "title": _txt(tr.find(attrs={"itemprop": "title"})),
                         "date": _txt(tr.find(attrs={"itemprop": "publicationDate"})) or _txt(tr.find(attrs={"itemprop": "priorityDate"})),
                         "assignee": _txt(tr.find(attrs={"itemprop": "assigneeOriginal"})),
                         "url": f"https://patents.google.com/patent/{num}/en"})
    return rows


def parse_patent_page(html: str, number: str = "", url: str = "") -> dict:
    soup = BeautifulSoup(html or "", "html.parser")

    title = (_metas(soup, "DC.title") or [""])[0]
    if not title:
        els = _main(soup, "title")
        title = _txt(els[0]) if els else ""
    if not title and soup.title:
        parts = [p.strip() for p in _txt(soup.title).split(" - ")]
        if len(parts) >= 3:
            title = " - ".join(parts[1:-1])
        elif len(parts) == 2 and not parts[1].lower().startswith("google"):
            title = parts[1]
    title = re.sub(r"^\s*[A-Z]{2}\d+[A-Z0-9]*\s*-\s*", "", title).strip()

    ab = soup.select_one("section[itemprop=abstract]")
    abstract = _txt(ab.select_one(".abstract") or ab) if ab else ""
    abstract = re.sub(r"^Abstract\s*", "", abstract)
    if not abstract:
        abstract = (_metas(soup, "DC.description") or [""])[0]

    claims, seen_n = [], set()
    sec = soup.select_one("section[itemprop=claims]")
    if sec:
        for el in sec.select(".claim-text"):
            t = _txt(el)
            m = _CLAIM_START.match(t)
            if m and m.group(1) not in seen_n:
                seen_n.add(m.group(1))
                claims.append(t)
        if not claims and _txt(sec):
            claims = [re.sub(r"^Claims\s*(\(\d+\))?\s*", "", _txt(sec))]
    independent = [c for c in claims if not _DEPENDENT.search(c[:260])] or claims[:1]

    desc_el = soup.select_one("section[itemprop=description]")
    description = re.sub(r"^Description\s*", "", _txt(desc_el)) if desc_el else ""

    inventors = _uniq([_txt(e) for e in _main(soup, "inventor")] + _metas(soup, "DC.contributor", "inventor"))
    assignees = _uniq([_txt(e) for e in _main(soup, "assigneeOriginal")] +
                      [_txt(e) for e in _main(soup, "assigneeCurrent")] + _metas(soup, "DC.contributor", "assignee"))

    cpc, seen_c = [], set()
    for code in soup.find_all(attrs={"itemprop": "Code"}):
        c = _txt(code)
        if re.fullmatch(r"[A-HY]\d{2}[A-Z]\d+/\d+", c) and c not in seen_c:
            seen_c.add(c)
            parent = code.parent
            d = parent.find(attrs={"itemprop": "Description"}) if parent else None
            cpc.append({"code": c, "description": _txt(d)})

    pdf = (_metas(soup, "citation_pdf_url") or [""])[0]
    if not pdf:
        a = soup.find("a", attrs={"itemprop": "pdfLink"})
        pdf = a.get("href", "") if a else ""

    if not (title or abstract or claims):
        low = (html or "").lower()
        if "unusual traffic" in low or "captcha" in low or "sorry" in low[:3000]:
            raise SourceError("Google returned a bot-check page instead of the patent (blocked temporarily; retry later)")
        raise SourceError("the page did not contain patent data (wrong number, or the layout changed)")

    return {
        "number": number, "url": url or (f"https://patents.google.com/patent/{number}/en" if number else ""),
        "title": title or number, "abstract": abstract, "claims": claims, "independent_claims": independent,
        "description": description[:6000], "inventors": inventors, "assignees": assignees,
        "priority_date": _date(soup, "priorityDate"), "filing_date": _date(soup, "filingDate", "datesubmitted"),
        "publication_date": _date(soup, "publicationDate", "issue"), "cpc": cpc[:25], "pdf_url": pdf,
        "citations": _related(soup, ["backwardReferences", "backwardReferencesOrig", "backwardReferencesFamily"])[:40],
        "cited_by": _related(soup, ["forwardReferences", "forwardReferencesOrig", "forwardReferencesFamily"])[:40],
        "similar": _related(soup, ["similarDocuments"])[:40],
        "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def fetch_patent(ref: str) -> dict:
    """Fetch + parse. Raises ValueError (bad input) or SourceError (network / blocked / not a patent page)."""
    number, url = normalize_ref(ref)
    key = ("patent-page", number)
    hit = sources._CACHE.get(key)
    if hit and time.time() - hit[0] < sources.CACHE_TTL:
        return hit[1]
    headers = {"User-Agent": sources.BROWSER_UA, "Accept": "text/html,application/xhtml+xml",
               "Accept-Language": "en-US,en;q=0.9", "Referer": "https://patents.google.com/"}
    r = sources._get(url, headers=headers, retries=1)
    info = parse_patent_page(r.text, number, url)
    sources._CACHE[key] = (time.time(), info)
    return info


def explain_error(e) -> str:
    s = str(e)
    if "HTTP 404" in s:
        return "Patent not found (HTTP 404). Check the publication number, including the kind code, e.g. US9060213B2."
    return sources.friendly(s)


def to_document(info: dict) -> dict:
    """Convert to a ranking document; claim 1 is appended to the abstract so similarity also sees the claim wording."""
    text = info["abstract"]
    if info["independent_claims"]:
        text = f"{text} Claim: {info['independent_claims'][0][:700]}".strip()
    who = info["inventors"][:5] or info["assignees"][:1]
    year = None
    for d in (info["publication_date"], info["filing_date"], info["priority_date"]):
        m = re.match(r"(\d{4})", d or "")
        if m:
            year = int(m.group(1))
            break
    return sources._doc("patent", info["title"], who, year, text, info["url"], info["number"],
                        "Google Patents (page)", ", ".join(info["assignees"][:1]))


def related_documents(info: dict, limit: int = 20) -> list:
    """Real records from the page's citation / cited-by / similar tables (title only - no abstracts on those rows)."""
    out, seen = [], {info["number"]}
    for group in ("similar", "citations", "cited_by"):
        for r in info.get(group, []):
            if r["number"] in seen or not r["title"]:
                continue
            seen.add(r["number"])
            out.append(sources._doc("patent", r["title"], [r["assignee"]] if r["assignee"] else [], sources._year(r["date"]),
                                    "", r["url"], r["number"], "Google Patents (related)", r["assignee"]))
            if len(out) >= limit:
                return out
    return out
