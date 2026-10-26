import pytest

from novelty import patent_search as ps, pipeline, report, similarity as S, sources
from tests.test_all import IDEA, _d, fake_search

GOOD = {"results": {"cluster": [{"result": [
    {"patent": {"title": "Wireless <b>charging</b> pad for smartphone", "snippet": "A wireless charging pad with an inductive coil for a smartphone.",
                "publication_number": "US111B2", "inventor": "Ann Roe", "assignee": "Acme", "publication_date": "2019-05-02",
                "filing_date": "2017-01-01", "priority_date": "2016-01-01"}},
    {"patent": {"title": "Concrete mixer", "snippet": "Mixes cement.", "publication_number": "US222B2", "publication_date": "2010-01-01"}},
    {"patent": {"title": "Wireless charging pad for smartphone", "snippet": "duplicate", "publication_number": "US111B2"}}]}]}}


class Resp:
    def __init__(self, code=200, payload=None, bad_json=False):
        self.status_code, self._p, self._bad = code, payload, bad_json

    def json(self):
        if self._bad:
            raise ValueError("bad")
        return self._p


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(ps.time, "sleep", lambda s: None)


def test_query_building_and_endpoint_format():
    assert ps.build_search_query("A wireless charging pad for the smartphone wireless") == "wireless charging pad smartphone"
    assert ps.build_search_query("the of") == "the of"
    url = ps.endpoint("charging smartphone wireless pad", 30)
    assert url.startswith("https://patents.google.com/xhr/query?url=q%3Dcharging%2Bsmartphone%2Bwireless%2Bpad%26num%3D30%26page%3D1")


def test_relevance_score_prefers_matching_patents():
    q = "wireless charging pad smartphone"
    hi = ps.relevance_score(q, {"title": "Wireless charging pad", "snippet": "charging a smartphone wirelessly"})
    lo = ps.relevance_score(q, {"title": "Concrete mixer", "snippet": "mixes cement"})
    assert hi > 50 > 12 > lo >= 0 and ps.relevance_score("", {"title": "x"}) == 0.0


def test_extract_raw_patents_all_shapes():
    import json
    assert len(ps.extract_raw_patents(GOOD)) == 3
    assert len(ps.extract_raw_patents(json.dumps(GOOD))) == 3                       # JSON string
    assert len(ps.extract_raw_patents({"content": json.dumps(GOOD)})) == 3          # wrapped in "content"
    assert len(ps.extract_raw_patents({"results": json.dumps(GOOD["results"])})) == 3
    assert ps.extract_raw_patents({"results": [{"title": "a"}, "junk"]}) == [{"title": "a"}]
    assert ps.extract_raw_patents({"results": {}}) == []
    with pytest.raises(ValueError):
        ps.extract_raw_patents([1, 2])


def test_build_docs_dedupes_filters_and_keeps_details():
    raw = ps.extract_raw_patents(GOOD)
    docs, total = ps.build_docs(raw, "wireless charging pad smartphone", 10)
    assert total == 2 and len(docs) == 1                                             # duplicate removed, mixer filtered out
    d = docs[0]
    assert d["title"] == "Wireless charging pad for smartphone" and d["identifier"] == "US111B2" and d["kind"] == "patent"
    assert d["assignee"] == "Acme" and d["filing_date"] == "2017-01-01" and d["year"] == 2019 and d["relevance"] >= 12
    assert d["url"] == "https://patents.google.com/patent/US111B2/en" and d["authors"] == ["Ann Roe"]


def test_search_returns_docs_and_note(monkeypatch):
    monkeypatch.setattr(sources.requests, "get", lambda *a, **k: Resp(200, GOOD))
    monkeypatch.setattr(ps.requests, "get", lambda *a, **k: Resp(200, GOOD))
    docs, note = ps.search_google_patents("wireless charging pad smartphone", 10, {})
    assert len(docs) == 1 and "relevance filter" in note


def test_503_retries_once_then_succeeds(monkeypatch):
    seq = [Resp(503), Resp(200, GOOD)]
    calls = []
    monkeypatch.setattr(ps.requests, "get", lambda *a, **k: calls.append(1) or seq.pop(0))
    docs, _ = ps.search_google_patents("wireless charging pad smartphone", 10, {})
    assert len(calls) == 2 and len(docs) == 1


def test_503_twice_is_reported_not_faked(monkeypatch):
    calls = []
    monkeypatch.setattr(ps.requests, "get", lambda *a, **k: calls.append(1) or Resp(503))
    with pytest.raises(sources.SourceError, match="HTTP 503"):
        ps.search_google_patents("wireless charging pad smartphone", 10, {})
    assert len(calls) == 2


def test_bad_json_and_http_errors(monkeypatch):
    monkeypatch.setattr(ps.requests, "get", lambda *a, **k: Resp(200, bad_json=True))
    with pytest.raises(sources.SourceError, match="not valid JSON"):
        ps.search_google_patents("wireless charging", 10, {})
    monkeypatch.setattr(ps.requests, "get", lambda *a, **k: Resp(403))
    with pytest.raises(sources.SourceError, match="HTTP 403"):
        ps.search_google_patents("wireless charging", 10, {})


def test_shorter_query_tried_when_first_is_empty(monkeypatch):
    urls = []

    def fake(url, **k):
        urls.append(url)
        return Resp(200, {"results": {"cluster": []}}) if len(urls) == 1 else Resp(200, GOOD)
    monkeypatch.setattr(ps.requests, "get", fake)
    docs, _ = ps.search_google_patents("wireless charging pad smartphone overheating", 10, {})
    assert len(urls) == 2 and len(docs) == 1 and "overheating" not in urls[1]


def test_irrelevant_records_give_note_not_fake_rows(monkeypatch):
    only_mixer = {"results": {"cluster": [{"result": [{"patent": {"title": "Concrete mixer", "snippet": "cement", "publication_number": "US2B2"}}]}]}}
    monkeypatch.setattr(ps.requests, "get", lambda *a, **k: Resp(200, only_mixer))
    docs, note = ps.search_google_patents("wireless charging pad smartphone", 10, {})
    assert docs == [] and "none passed the relevance threshold" in note


def test_status_row_shows_note_through_search_all(monkeypatch):
    monkeypatch.setattr(ps.requests, "get", lambda *a, **k: Resp(200, GOOD))
    docs, st = sources.search_all(["wireless charging pad smartphone overheating", "wireless charging pad smartphone"],
                                  enabled=["Google Patents"])
    row = st[0]
    assert row["state"] == "ok" and row["count"] == 1 and "relevance filter" in row["message"] and docs[0]["assignee"] == "Acme"


# ---------------------------------------------------------------- novelty score
def _ranked(sim_docs):
    feats = ["alpha sensor", "beta module"]
    docs = [_d("paper", t, str(i)) for i, t in enumerate(sim_docs)]
    return feats, docs


def test_novelty_none_without_documents():
    n = S.novelty_assessment([], ["a"])
    assert n["score"] is None and n["confidence"] == "None"


def test_novelty_low_when_close_match_and_high_when_unrelated():
    idea = "wireless charging pad with inductive coil for smartphone and overheating protection sensor"
    feats = ["wireless charging pad", "inductive coil", "overheating protection"]
    close = [sources._doc("patent", "Wireless charging pad with inductive coil and overheating protection sensor", [], 2020,
                          "Smartphone wireless charging pad, inductive coil, overheating protection.", "u", "US1", "Google Patents")]
    far = [sources._doc("paper", "Deep sea fish migration", [], 2020, "Marine biology of fish.", "u", "10.1/z", "OpenAlex")]
    low = S.novelty_assessment(S.rank(idea, feats, close), feats)
    high = S.novelty_assessment(S.rank(idea, feats, far), feats)
    assert low["score"] < 45 < 70 <= high["score"] <= 100
    assert "NOT a legal" in low["disclaimer"] and high["confidence"] == "Low"
    assert any("No patent records" in n for n in high["notes"])


def test_novelty_confidence_rises_with_evidence():
    feats = ["alpha sensor"]
    docs = []
    for i in range(25):
        docs.append(sources._doc("patent" if i < 5 else "paper", f"doc {i} unrelated topic", [], 2020, "text", "u", f"id{i}",
                                 ["OpenAlex", "Crossref", "Google Patents"][i % 3]))
    n = S.novelty_assessment(S.rank("alpha sensor device", feats, docs), feats)
    assert n["confidence"] == "High" and n["components"]["documents"] == 25


def test_pipeline_report_and_add_documents_carry_novelty():
    res = pipeline.run_analysis(IDEA, "Bottle", search_fn=fake_search)
    assert res["novelty"]["score"] is not None
    pypdf = pytest.importorskip("pypdf")
    import io
    text = " ".join(p.extract_text() for p in pypdf.PdfReader(io.BytesIO(report.build_pdf(res))).pages)
    assert "Novelty indicator" in text
    res2 = pipeline.add_documents(res, [_d("patent", "Hydration bottle sensor mobile app", "US5B2", "Google Patents")])
    assert res2["novelty"] != res["novelty"] or res2["novelty"]["components"]["documents"] == res["novelty"]["components"]["documents"] + 1
    empty = pipeline.run_analysis(IDEA, search_fn=lambda q, **k: ([], []))
    assert empty["novelty"]["score"] is None and report.build_pdf(empty).startswith(b"%PDF")
