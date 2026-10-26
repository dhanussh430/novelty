import io
import time

import pytest

from novelty import features as F, pipeline, report, similarity as S, sources, suggestions

IDEA = ("A smart water bottle that tracks hydration using a capacitive level sensor and sends personalised "
        "reminders to a mobile app, adjusting the daily target based on ambient temperature.")


# ============================================================ features
def test_idea_features_label():
    assert F.format_idea_features(["a sensor", "mobile app"]) == "Idea Features: a sensor; mobile app"
    assert F.format_idea_features([]) == "Idea Features: none detected"


def test_extract_features_and_keywords():
    feats = F.extract_features(IDEA)
    assert feats and any("sensor" in f for f in feats) and any("mobile app" in f for f in feats)
    assert F.extract_features("") == []
    kws = F.extract_keywords(IDEA)
    assert "hydration" in kws and "the" not in kws
    qs = F.build_queries(feats, kws)
    assert 1 <= len(qs) <= 3 and len(set(qs)) == len(qs)


def test_merge_features_adds_not_replaces():
    merged = F.merge_features(["using n8n automation"], ["capacitive level sensor", "mobile app", "N8N automation"])
    assert merged[0] == "using n8n automation" and "mobile app" in merged and len(merged) == 3


# ============================================================ parsers (no network)
def test_openalex_parse():
    data = {"results": [{"display_name": "Hydration sensing", "publication_year": 2020, "doi": "https://doi.org/10.1/x",
                         "authorships": [{"author": {"display_name": "A B"}}],
                         "abstract_inverted_index": {"Smart": [0], "bottle": [1]},
                         "primary_location": {"source": {"display_name": "J"}}}]}
    d = sources.parse_openalex(data)[0]
    assert d["abstract"] == "Smart bottle" and d["identifier"] == "10.1/x" and d["authors"] == ["A B"] and d["year"] == 2020


def test_crossref_parse():
    data = {"message": {"items": [{"title": ["T"], "DOI": "10.2/y", "URL": "http://dx.doi.org/10.2/y",
                                   "author": [{"given": "C", "family": "D"}], "issued": {"date-parts": [[2019, 5]]},
                                   "abstract": "<jats:p>Abs <b>x</b></jats:p>"}]}}
    d = sources.parse_crossref(data)[0]
    assert d["abstract"] == "Abs x" and d["year"] == 2019 and d["authors"] == ["C D"]


def test_semantic_scholar_parse():
    d = sources.parse_semantic_scholar({"data": [{"title": "T", "abstract": "A", "year": 2021, "authors": [{"name": "Z"}],
                                                  "externalIds": {"DOI": "10.3/z"}, "url": "http://s2/x", "venue": "V"}]})[0]
    assert d["identifier"] == "10.3/z" and d["source"] == "Semantic Scholar" and d["year"] == 2021


ARXIV = """<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/2101.00001v1</id>
<published>2021-01-01T00:00:00Z</published><title>Smart  bottle</title><summary>Hydration sensing.</summary>
<author><name>Ann Lee</name></author></entry></feed>"""


def test_arxiv_parse():
    d = sources.parse_arxiv(ARXIV)[0]
    assert d["title"] == "Smart bottle" and d["year"] == 2021 and d["authors"] == ["Ann Lee"] and d["identifier"] == "2101.00001v1"
    with pytest.raises(sources.SourceError):
        sources.parse_arxiv("<not xml")


def test_europepmc_parse_paper_and_patent():
    data = {"resultList": {"result": [
        {"id": "123", "source": "MED", "title": "Paper", "authorString": "Doe J, Roe A.", "pubYear": "2020", "abstractText": "abs", "doi": "10.9/p"},
        {"id": "WO2010123456", "source": "PAT", "title": "Patent", "pubYear": "2010", "abstractText": "pabs"}]}}
    p, pat = sources.parse_europepmc(data)
    assert p["kind"] == "paper" and p["identifier"] == "10.9/p" and p["authors"] == ["Doe J", "Roe A"]
    assert pat["kind"] == "patent" and pat["identifier"] == "WO2010123456" and pat["url"].endswith("/PAT/WO2010123456")


def test_doaj_and_zenodo_parse():
    d = sources.parse_doaj({"results": [{"bibjson": {"title": "T", "abstract": "A", "year": "2018", "author": [{"name": "N"}],
                                                     "link": [{"url": "http://x"}], "identifier": [{"type": "doi", "id": "10.5/q"}]}}]})[0]
    assert d["year"] == 2018 and d["identifier"] == "10.5/q" and d["url"] == "http://x"
    z = sources.parse_zenodo({"hits": {"hits": [{"metadata": {"title": "Z", "description": "<p>desc</p>", "creators": [{"name": "C"}],
                                                              "publication_date": "2022-03-01", "doi": "10.5281/z"},
                                                 "links": {"html": "http://zenodo/1"}}]}})[0]
    assert z["abstract"] == "desc" and z["year"] == 2022



def test_lens_parse():
    d = sources.parse_lens({"data": [{"lens_id": "abc", "jurisdiction": "US", "doc_number": "123", "kind": "B2",
                                      "date_published": "2020-02-02", "abstract": [{"text": "abs"}],
                                      "biblio": {"invention_title": [{"text": "Title", "lang": "en"}],
                                                 "parties": {"inventors": [{"extracted_name": {"value": "Inv"}}]}}}]})[0]
    assert d["identifier"] == "US123B2" and d["title"] == "Title" and d["authors"] == ["Inv"] and d["year"] == 2020


# ============================================================ errors / resilience / speed
def test_friendly_messages():
    assert "503" in sources.friendly("HTTP 503") and "throttling" in sources.friendly("HTTP 503")
    assert "Rate-limited" in sources.friendly("HTTP 429")
    assert "Network" in sources.friendly("ConnectionError: Connection aborted")
    assert "Timed out" in sources.friendly("ReadTimeout: x")


class FakeResp:
    def __init__(self, code, payload=None):
        self.status_code, self._p = code, payload

    def json(self):
        if self._p is None:
            raise ValueError("no json")
        return self._p




def _d(kind, title, ident, source="X", abstract="abs"):
    return sources._doc(kind, title, [], 2020, abstract, "http://u", ident, source)


def test_search_all_survives_failures_and_reports_states(monkeypatch):
    def boom(*a, **k):
        raise sources.SourceError("HTTP 503")
    monkeypatch.setitem(sources.REGISTRY["OpenAlex"], "fn", boom)
    monkeypatch.setitem(sources.REGISTRY["Crossref"], "fn", lambda q, n, c: [_d("paper", "P", "d", "Crossref")])
    monkeypatch.setitem(sources.REGISTRY["Google Patents"], "fn", lambda q, n, c: (_ for _ in ()).throw(ValueError("weird")))
    docs, st = sources.search_all(["a b c d"], enabled=["OpenAlex", "Crossref", "Google Patents"])
    by = {s["source"]: s for s in st}
    assert len(docs) == 1
    assert by["OpenAlex"]["state"] == "failed" and "503" in by["OpenAlex"]["message"] and not by["OpenAlex"]["ok"]
    assert by["Crossref"]["state"] == "ok" and by["Crossref"]["count"] == 1
    assert by["Google Patents"]["state"] == "failed"


def test_sources_run_in_parallel(monkeypatch):
    def slow(q, n, c):
        time.sleep(0.4)
        return [_d("paper", f"T{q}", q)]
    names = ["OpenAlex", "Crossref", "Semantic Scholar", "arXiv", "Europe PMC"]
    for n in names:
        monkeypatch.setitem(sources.REGISTRY[n], "fn", slow)
    t0 = time.time()
    docs, st = sources.search_all(["alpha beta gamma delta"], enabled=names)
    assert time.time() - t0 < 1.2          # sequential would take >= 2.0 s
    assert all(s["state"] == "ok" for s in st)


def test_deadline_does_not_hang(monkeypatch):
    monkeypatch.setitem(sources.REGISTRY["Zenodo"], "fn", lambda q, n, c: time.sleep(3) or [])
    monkeypatch.setitem(sources.REGISTRY["DOAJ"], "fn", lambda q, n, c: [_d("paper", "ok", "1")])
    t0 = time.time()
    docs, st = sources.search_all(["alpha beta"], enabled=["Zenodo", "DOAJ"], deadline=0.5)
    assert time.time() - t0 < 2.0 and len(docs) == 1
    assert {s["source"]: s["state"] for s in st} == {"Zenodo": "failed", "DOAJ": "ok"}


def test_cache_reuses_successful_results(monkeypatch):
    calls = []
    monkeypatch.setitem(sources.REGISTRY["DOAJ"], "fn", lambda q, n, c: calls.append(1) or [_d("paper", "t", "1")])
    sources.search_all(["alpha beta"], enabled=["DOAJ"])
    sources.search_all(["alpha beta"], enabled=["DOAJ"])
    assert len(calls) == 1


def test_lens_skipped_without_token_and_thorough_uses_more_queries(monkeypatch):
    seen = []
    monkeypatch.setitem(sources.REGISTRY["OpenAlex"], "fn", lambda q, n, c: seen.append(q) or [])
    docs, st = sources.search_all(["one two three four five six", "one two three four", "one two"], enabled=["OpenAlex", "Lens.org"])
    assert seen == ["one two three four"]                       # fast mode: a single query
    assert {s["source"]: s["state"] for s in st}["Lens.org"] == "skipped"
    seen.clear()
    sources.clear_cache()
    sources.search_all(["one two three four five six", "one two three four", "one two"], enabled=["OpenAlex"], thorough=True)
    assert len(seen) == 3


def test_no_patentsview_anywhere():
    assert "PatentsView" not in sources.REGISTRY


def test_dedupe_prefers_abstract():
    a = sources._doc("paper", "Same Title", [], 2020, "", "u", "10.1/a", "OpenAlex")
    b = sources._doc("paper", "Same title!", [], 2020, "has abstract", "u", "10.1/b", "Crossref")
    out = sources.dedupe([a, b])
    assert len(out) == 1 and out[0]["abstract"] == "has abstract"


# ============================================================ similarity
def _docs():
    return [sources._doc("paper", "Hydration tracking bottle with capacitive level sensor", ["X"], 2020,
                         "A smart bottle sends reminders to a mobile app using a sensor.", "http://a", "1", "OpenAlex"),
            sources._doc("patent", "Concrete mixing machine", [], 2015, "Mixes cement and gravel.", "http://b", "US9", "Google Patents")]


def test_ranking_orders_relevant_first():
    feats = F.extract_features(IDEA)
    r = S.rank(IDEA, feats, _docs())
    assert r[0]["title"].startswith("Hydration") and r[0]["similarity"] > r[1]["similarity"]
    assert 0 <= r[1]["similarity"] <= 100 and r[0]["rank"] == 1 and r[0]["matched_features"]
    assert S.rank(IDEA, feats, []) == []


# ============================================================ pipeline / report / suggestions
def fake_search(queries, **kw):
    return _docs(), [{"source": "Fake", "kind": "paper", "ok": True, "state": "ok", "count": 2, "seconds": 0.1, "message": "OK"}]


def test_pipeline_and_report():
    res = pipeline.run_analysis(IDEA, "Bottle", search_fn=fake_search)
    assert res["ranked"] and res["suggestions"] and res["title"] == "Bottle" and "elapsed" in res
    pdf = report.build_pdf(res)
    assert pdf.startswith(b"%PDF") and len(pdf) > 3000
    pypdf = pytest.importorskip("pypdf")
    text = " ".join(p.extract_text() for p in pypdf.PdfReader(io.BytesIO(pdf)).pages)
    for needle in ("Idea Features:", "Bottle", "Similarity Analysis", "Innovation Suggestions", "Limitations", "US9"):
        assert needle in text


def test_custom_features_are_added_not_replacing():
    res = pipeline.run_analysis(IDEA, custom_features=["using n8n automation"], search_fn=fake_search)
    assert res["features"][0] == "using n8n automation" and len(res["features"]) > 2
    only = pipeline.run_analysis(IDEA, custom_features=["using n8n automation"], only_custom=True, search_fn=fake_search)
    assert only["features"] == ["using n8n automation"]


def test_report_reflects_latest_analysis():
    r1 = pipeline.run_analysis(IDEA, "FirstTitle", search_fn=fake_search)
    r2 = pipeline.run_analysis("A solar powered irrigation controller that schedules watering using soil moisture probes", "SecondTitle", search_fn=fake_search)
    assert r1["run_id"] != r2["run_id"]
    pypdf = pytest.importorskip("pypdf")
    t = " ".join(p.extract_text() for p in pypdf.PdfReader(io.BytesIO(report.build_pdf(r2))).pages)
    assert "SecondTitle" in t and "FirstTitle" not in t


def test_pipeline_handles_no_results_and_search_crash():
    res = pipeline.run_analysis(IDEA, search_fn=lambda q, **k: ([], []))
    assert res["ranked"] == [] and res["top_similarity"] == 0
    pdf = report.build_pdf(res)
    assert pdf.startswith(b"%PDF")

    def crash(q, **k):
        raise RuntimeError("x")
    res = pipeline.run_analysis(IDEA, search_fn=crash)
    assert not res["statuses"][0]["ok"]


def test_patent_summary_states_and_pdf_explains_missing_patents():
    def papers_only(q, **k):
        return [_d("paper", "Smart bottle hydration sensor", "1", "OpenAlex")], [
            {"source": "OpenAlex", "kind": "paper", "ok": True, "state": "ok", "count": 1, "seconds": 0.1, "message": "OK"},
            {"source": "Google Patents", "kind": "patent", "ok": False, "state": "failed", "count": 0, "seconds": 0.2,
             "message": sources.friendly("HTTP 503")}]
    res = pipeline.run_analysis(IDEA, search_fn=papers_only)
    assert pipeline.patent_summary(res) == ("unavailable", 0)
    pdf = report.build_pdf(res)
    pypdf = pytest.importorskip("pypdf")
    text = " ".join(p.extract_text() for p in pypdf.PdfReader(io.BytesIO(pdf)).pages)
    assert "Reasons" in text and "503" in text and "espacenet" in text.lower()
    res2 = pipeline.run_analysis(IDEA, search_fn=lambda q, **k: ([_d("paper", "x hydration", "1")], [
        {"source": "Google Patents", "kind": "patent", "ok": True, "state": "ok", "count": 0, "seconds": 0, "message": "OK"}]))
    assert pipeline.patent_summary(res2) == ("none", 0)


def test_retry_patents_merges_and_refreshes_status():
    def first(q, **k):
        return [_d("paper", "Smart bottle hydration sensor", "1", "OpenAlex")], [
            {"source": "Google Patents", "kind": "patent", "ok": False, "state": "failed", "count": 0, "seconds": 0, "message": "HTTP 503"}]
    res = pipeline.run_analysis(IDEA, search_fn=first)
    assert pipeline.patent_summary(res)[0] == "unavailable"
    seen = {}

    def second(q, **k):
        seen.update(k)
        return [_d("patent", "Hydration bottle sensor patent", "US1B2", "Google Patents")], [
            {"source": "Google Patents", "kind": "patent", "ok": True, "state": "ok", "count": 1, "seconds": 0.5, "message": "OK"}]
    res2 = pipeline.retry_patents(res, search_fn=second)
    assert seen["enabled"] and all(sources.REGISTRY[n]["kind"] == "patent" for n in seen["enabled"])
    assert pipeline.patent_summary(res2) == ("found", 1) and res2["run_id"] != res["run_id"]
    assert [s for s in res2["statuses"] if s["source"] == "Google Patents"][0]["state"] == "ok"
    assert len([s for s in res2["statuses"] if s["source"] == "Google Patents"]) == 1
    assert len(pipeline.papers(res2)) == 1


def test_unicode_in_report_does_not_crash():
    def uni(q, **k):
        return [sources._doc("paper", "Étude <b>αβγ</b> & “quotes” — 中文", ["Ünï"], 2021, "abs ≥ 3 → ok & <x>", "http://a?b=1&c=2", "d", "OpenAlex")], []
    assert report.build_pdf(pipeline.run_analysis(IDEA, search_fn=uni)).startswith(b"%PDF")


def test_suggestions_flag_verification():
    res = pipeline.run_analysis(IDEA, search_fn=fake_search)
    assert any(s["needs_verification"] for s in res["suggestions"]) and any(not s["needs_verification"] for s in res["suggestions"])
    assert suggestions._hit("air", "ai") is False and suggestions._hit("ai", "ai")


def test_empty_idea_rejected():
    with pytest.raises(ValueError):
        pipeline.run_analysis("   ")


# ============================================================ user-supplied patents
CSV = """search URL: https://patents.google.com/?q=bottle
retrieved on 2026
id,title,assignee,inventor/author,priority date,filing/creation date,publication date,grant date,result link,representative figure link
US10123456B2,Smart water bottle with hydration sensor,Acme,Joe,2017-01-01,2017-01-02,2019-05-02,2019-05-02,https://patents.google.com/patent/US10123456B2/en,
"""


def test_parse_google_patents_csv():
    docs = sources.parse_patent_csv(CSV)
    assert len(docs) == 1 and docs[0]["identifier"] == "US10123456B2" and docs[0]["year"] == 2019 and docs[0]["kind"] == "patent"
    with pytest.raises(ValueError):
        sources.parse_patent_csv("nothing,useful\n1,2")


def test_add_documents_reranks_and_changes_run_id():
    res = pipeline.run_analysis(IDEA, "B", search_fn=lambda q, **k: ([], []))
    assert not pipeline.patents(res)
    res2 = pipeline.add_documents(res, sources.parse_patent_csv(CSV))
    assert len(pipeline.patents(res2)) == 1 and res2["run_id"] != res["run_id"] and res2["top_similarity"] > 0
    assert report.build_pdf(res2).startswith(b"%PDF")


def test_manual_patent_and_links():
    d = sources.make_patent("US1B2", "Water bottle sensor", "abs")
    assert d["url"].endswith("US1B2/en")
    with pytest.raises(ValueError):
        sources.make_patent("", "")
    links = sources.patent_search_links(["water bottle sensor app", "water bottle sensor"])
    names = {x["name"] for x in links}
    assert len(links) >= 12 and any("InPASS" in n for n in names) and any("Espacenet" in n for n in names)
    assert any("PATENTSCOPE" in n for n in names) and any("USPTO" in n for n in names)
    assert all(x["url"].startswith("https://") for x in links)
    g = [x for x in links if x["name"] == "Google Patents"][0]
    assert g["prefilled"] and g["url"].endswith("water+bottle+sensor")
    assert [x for x in links if "InPASS" in x["name"]][0]["url"] == "https://iprsearch.ipindia.gov.in/publicsearch"


def test_fallback_query_only_when_a_source_answered():
    calls = []

    def all_down(q, **k):
        calls.append(q)
        return [], [{"source": "OpenAlex", "kind": "paper", "ok": False, "state": "failed", "count": 0, "seconds": 0, "message": "net"}]
    res = pipeline.run_analysis(IDEA, search_fn=all_down)
    assert len(calls) == 1 and len(res["statuses"]) == 1            # no pointless second round

    calls.clear()

    def empty_then_hit(q, **k):
        calls.append(q)
        if len(calls) == 1:
            return [], [{"source": "OpenAlex", "kind": "paper", "ok": True, "state": "ok", "count": 0, "seconds": 0, "message": "OK"}]
        return [_d("paper", "Hydration bottle sensor", "1", "OpenAlex")], [{"source": "OpenAlex", "kind": "paper", "ok": True, "state": "ok", "count": 1, "seconds": 0, "message": "OK"}]
    res = pipeline.run_analysis(IDEA, search_fn=empty_then_hit)
    assert len(calls) == 2 and len(res["ranked"]) == 1 and len(res["statuses"]) == 1 and res["statuses"][0]["count"] == 1
