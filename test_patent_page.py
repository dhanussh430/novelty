import os

import pytest
from streamlit.testing.v1 import AppTest

from novelty import patent_page as pp, pipeline, report, sources
from tests.test_all import IDEA, fake_search

# Stand-in page that follows Google Patents' markup conventions (NOT the real US9060213B2 page).
HTML = """<html><head><title>US1234567B2 - Smart bottle with hydration sensor - Google Patents</title>
<meta name="DC.title" content="Smart bottle with hydration sensor">
<meta name="DC.description" content="Meta abstract text.">
<meta name="DC.contributor" scheme="inventor" content="Jane Roe">
<meta name="DC.date" scheme="dateSubmitted" content="2016-03-04">
<meta name="DC.date" scheme="issue" content="2019-05-02">
<meta name="citation_pdf_url" content="https://patentimages.storage.googleapis.com/x/US1234567B2.pdf"></head><body>
<dl><dd itemprop="inventor">Jane Roe</dd><dd itemprop="inventor">John Doe</dd><dd itemprop="assigneeOriginal">Acme Corp</dd>
<dd><time itemprop="priorityDate" datetime="2015-03-05">2015-03-05</time></dd>
<dd><time itemprop="filingDate" datetime="2016-03-04">2016-03-04</time></dd>
<dd><time itemprop="publicationDate" datetime="2019-05-02">2019-05-02</time></dd></dl>
<section itemprop="abstract"><h2>Abstract</h2><div class="abstract">A smart bottle measures hydration with a capacitive level sensor and reports to a mobile app.</div></section>
<section itemprop="claims"><h2>Claims (3)</h2>
<div class="claims"><div class="claim"><div class="claim-text">1. A bottle comprising: a capacitive level sensor; and
<div class="claim-text">a transmitter sending data to a mobile app.</div></div></div>
<div class="claim claim-dependent"><div class="claim-text">2. The bottle of claim 1, further comprising a temperature sensor.</div></div>
<div class="claim"><div class="claim-text">3. A method of tracking hydration, comprising reading the sensor.</div></div></div></section>
<section itemprop="description"><h2>Description</h2><div class="description">The invention relates to bottles.</div></section>
<ul><li><span itemprop="Code">A47G19/2227</span> <span itemprop="Description">Drinking vessels</span></li>
<li><span itemprop="Code">G01F23/26</span> <span itemprop="Description">Level measurement by capacitance</span></li></ul>
<table><tr itemprop="backwardReferences"><td><span itemprop="publicationNumber">US111A</span></td><td itemprop="priorityDate">2000-01-01</td>
<td itemprop="assigneeOriginal">Old Co</td><td itemprop="title">Early bottle</td></tr></table>
<table><tr itemprop="similarDocuments"><td><span itemprop="publicationNumber">US222B2</span></td><td itemprop="publicationDate">2018-02-02</td>
<td itemprop="assigneeOriginal">Sim Inc</td><td itemprop="title">Similar hydration device</td></tr></table>
<table><tr itemprop="forwardReferences"><td><span itemprop="publicationNumber">US333B1</span></td><td itemprop="title">Later bottle</td></tr></table>
<a itemprop="pdfLink" href="https://x/y.pdf">PDF</a></body></html>"""


def test_normalize_ref_variants():
    assert pp.normalize_ref("https://patents.google.com/patent/US9060213B2/en") == ("US9060213B2", "https://patents.google.com/patent/US9060213B2/en")
    assert pp.normalize_ref("https://patents.google.com/patent/US9060213B2/en......")[0] == "US9060213B2"
    assert pp.normalize_ref(" us 9,060,213 b2 ")[0] == "US9060213B2"
    assert pp.normalize_ref("9060213")[0] == "US9060213"
    for bad in ("", "hello world", "https://evil.com/patent/US1B2/en", "https://patents.google.com/about"):
        with pytest.raises(ValueError):
            pp.normalize_ref(bad)


def test_parse_patent_page_fields():
    i = pp.parse_patent_page(HTML, "US1234567B2", "u")
    assert i["title"] == "Smart bottle with hydration sensor"
    assert i["abstract"].startswith("A smart bottle measures hydration")
    assert i["inventors"] == ["Jane Roe", "John Doe"] and i["assignees"] == ["Acme Corp"]
    assert (i["priority_date"], i["filing_date"], i["publication_date"]) == ("2015-03-05", "2016-03-04", "2019-05-02")
    assert len(i["claims"]) == 3 and i["claims"][0].startswith("1. A bottle") and "transmitter" in i["claims"][0]
    assert len(i["independent_claims"]) == 2 and not any(c.startswith("2.") for c in i["independent_claims"])
    assert [c["code"] for c in i["cpc"]] == ["A47G19/2227", "G01F23/26"] and i["cpc"][1]["description"].startswith("Level")
    assert i["citations"][0]["number"] == "US111A" and i["similar"][0]["title"] == "Similar hydration device"
    assert i["cited_by"][0]["number"] == "US333B1" and i["pdf_url"].endswith("US1234567B2.pdf")


def test_parse_falls_back_to_meta_and_title_tag():
    i = pp.parse_patent_page('<html><head><title>US9B2 - Fancy widget - Google Patents</title>'
                             '<meta name="DC.description" content="Only a meta abstract."></head></html>', "US9B2")
    assert i["title"] == "Fancy widget" and i["abstract"] == "Only a meta abstract."


def test_blocked_or_empty_pages_raise_clear_errors():
    with pytest.raises(sources.SourceError, match="bot-check"):
        pp.parse_patent_page("<html><body>Our systems have detected unusual traffic</body></html>")
    with pytest.raises(sources.SourceError, match="did not contain patent data"):
        pp.parse_patent_page("<html><body>nothing here</body></html>")


class Resp:
    def __init__(self, code, text=""):
        self.status_code, self.text = code, text


def test_fetch_patent_success_cache_and_errors(monkeypatch):
    calls = []
    monkeypatch.setattr(sources.requests, "get", lambda url, **k: calls.append(url) or Resp(200, HTML))
    a = pp.fetch_patent("https://patents.google.com/patent/US1234567B2/en")
    b = pp.fetch_patent("US1234567B2")
    assert a["title"] == b["title"] and len(calls) == 1 and calls[0].endswith("/patent/US1234567B2/en")
    sources.clear_cache()
    monkeypatch.setattr(sources.requests, "get", lambda *a, **k: Resp(404))
    with pytest.raises(sources.SourceError) as e:
        pp.fetch_patent("US1234567B2")
    assert "not found" in pp.explain_error(e.value)
    monkeypatch.setattr(sources.requests, "get", lambda *a, **k: Resp(503))
    with pytest.raises(sources.SourceError) as e:
        pp.fetch_patent("US7654321B2")
    assert "503" in pp.explain_error(e.value)


def test_documents_and_analysis_integration():
    info = pp.parse_patent_page(HTML, "US1234567B2", "https://patents.google.com/patent/US1234567B2/en")
    doc = pp.to_document(info)
    assert doc["kind"] == "patent" and doc["year"] == 2019 and "Claim:" in doc["abstract"] and doc["identifier"] == "US1234567B2"
    rel = pp.related_documents(info)
    assert {r["identifier"] for r in rel} == {"US111A", "US222B2", "US333B1"} and all(r["kind"] == "patent" for r in rel)
    res = pipeline.run_analysis(IDEA, "B", search_fn=fake_search)
    res2 = pipeline.add_documents(res, [doc], statuses=[{"source": "Google Patents (page lookup)", "kind": "patent", "ok": True,
                                                         "state": "ok", "count": 1, "seconds": 0, "message": "fetched"}])
    assert pipeline.patent_summary(res2)[0] == "found"
    assert any(d["identifier"] == "US1234567B2" for d in pipeline.patents(res2))
    assert report.build_pdf(res2).startswith(b"%PDF")


APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")


def test_app_lookup_before_and_after_analysis(monkeypatch):
    monkeypatch.setattr(pp.sources.requests, "get", lambda *a, **k: Resp(200, HTML))
    monkeypatch.setattr(sources, "search_all", lambda q, **k: ([], []))
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.text_input(key="lookup_ref").set_value("https://patents.google.com/patent/US1234567B2/en")
    [b for b in at.button if b.key == "lookup_btn"][0].click().run()
    assert not at.exception, at.exception
    assert at.session_state["lookup"]["title"] == "Smart bottle with hydration sensor"
    # bad input -> friendly error, no crash
    at.text_input(key="lookup_ref").set_value("nonsense")
    [b for b in at.button if b.key == "lookup_btn"][0].click().run()
    assert not at.exception and at.session_state["lookup_error"]
    # fetch again, analyse, then add to analysis
    at.text_input(key="lookup_ref").set_value("US1234567B2")
    [b for b in at.button if b.key == "lookup_btn"][0].click().run()
    at.text_area(key="idea_text").set_value("A smart water bottle that tracks hydration using a capacitive level sensor and sends reminders to a mobile app.")
    [b for b in at.button if "Analyze" in b.label][0].click().run()
    assert not at.exception, at.exception
    [b for b in at.button if b.key == "lookup_add"][0].click().run()
    assert not at.exception, at.exception
    assert any(d["identifier"] == "US1234567B2" for d in pipeline.patents(at.session_state["analysis"]))
    [b for b in at.button if b.key == "lookup_add_rel"][0].click().run()
    assert not at.exception and len(pipeline.patents(at.session_state["analysis"])) == 4
