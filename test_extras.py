import io
import os

import pytest
from streamlit.testing.v1 import AppTest

from novelty import feature_ideas, pipeline, priorwork, report, sources
from tests.test_all import IDEA, _d

OA = {"results": [
    {"display_name": "Smart hydration bottle sensing", "publication_year": 2018, "doi": "https://doi.org/10.1/a",
     "authorships": [{"author": {"display_name": "Ann Lee"}, "institutions": [{"display_name": "IIT Madras", "country_code": "IN"}], "countries": ["IN"]},
                     {"author": {"display_name": "Bo Chen"}, "institutions": [{"display_name": "Tsinghua University", "country_code": "CN"}]}],
     "abstract_inverted_index": {"smart": [0], "bottle": [1], "sensor": [2]}, "primary_location": {"source": {"display_name": "Sensors Journal"}}},
    {"display_name": "Hydration tracking with mobile app", "publication_year": 2021, "doi": "https://doi.org/10.1/b",
     "authorships": [{"author": {"display_name": "Ann Lee"}, "institutions": [{"display_name": "IIT Madras", "country_code": "IN"}]}],
     "abstract_inverted_index": {"hydration": [0], "mobile": [1], "app": [2]}, "primary_location": {"source": {"display_name": "Sensors Journal"}}}]}


def _search(q, **k):
    docs = sources.parse_openalex(OA)
    st = [{"source": "OpenAlex", "kind": "paper", "ok": True, "state": "ok", "count": 2, "seconds": 0.3, "message": "OK"},
          {"source": "Google Patents", "kind": "patent", "ok": False, "state": "failed", "count": 0, "seconds": 0.5,
           "message": "Temporarily unavailable (HTTP 503)"}]
    return docs, st


def test_openalex_affiliations_parsed():
    d = sources.parse_openalex(OA)[0]
    assert d["institutions"] == ["IIT Madras", "Tsinghua University"] and d["countries"] == ["IN", "CN"]


def test_prior_work_uses_only_retrieved_data():
    res = pipeline.run_analysis(IDEA, "B", search_fn=_search)
    pw = res["prior_work"]
    assert pw["available"] and pw["n_docs"] == 2 and pw["n_patents"] == 0
    assert pw["earliest"]["year"] == 2018 and pw["latest"]["year"] == 2021
    assert ("India", 2) in pw["countries"] and ("China", 1) in pw["countries"]
    assert pw["institutions"][0] == ("IIT Madras", 2) and ("Ann Lee", 2) in pw["authors"]
    assert pw["timeline"] == {2018: 1, 2021: 1}
    text = " ".join(pw["paragraphs"])
    assert "Earliest closely related work" in text and "2018" in text and "no patent records were retrieved" in text
    assert "Smart hydration bottle sensing" in text


def test_prior_work_with_nothing_retrieved_is_honest():
    res = pipeline.run_analysis(IDEA, search_fn=lambda q, **k: ([], []))
    assert res["prior_work"]["available"] is False and "nothing to analyse" in res["prior_work"]["paragraphs"][0]


def test_add_documents_refreshes_prior_work():
    res = pipeline.run_analysis(IDEA, search_fn=_search)
    res2 = pipeline.add_documents(res, [_d("patent", "Hydration bottle sensor mobile app", "US5B2", "Google Patents")])
    assert res2["prior_work"]["n_patents"] == 1 and "no patent records were retrieved" not in " ".join(res2["prior_work"]["paragraphs"])


def test_feature_ideas_detects_present_and_missing():
    ideas = feature_ideas.generate("A bottle that sends encrypted data through an API and shows a dashboard", ["sensor"])
    by = {i["category"]: i for i in ideas}
    assert by["Security & privacy"]["status"].startswith("Already") and not by["Security & privacy"]["needs_verification"]
    assert by["Open API & integrations"]["status"].startswith("Already")
    assert by["Energy efficiency & sustainability"]["status"] == "Can be added" and by["Energy efficiency & sustainability"]["needs_verification"]
    assert all(i["how"] and i["benefit"] and i["effort"] in ("Low", "Medium", "High") for i in ideas)
    assert ideas[0]["status"] == "Can be added"                       # suggestions are listed first
    assert any(i["category"].startswith("Domain idea") for i in feature_ideas.generate("a battery powered sensor for hydration", []))


def test_pdf_explains_missing_patents_with_worldwide_analysis_and_databases():
    res = pipeline.run_analysis(IDEA, "Bottle", search_fn=_search)
    pypdf = pytest.importorskip("pypdf")
    text = " ".join(p.extract_text() for p in pypdf.PdfReader(io.BytesIO(report.build_pdf(res))).pages)
    for needle in ("Worldwide prior-work analysis", "InPASS", "Espacenet", "PATENTSCOPE", "Ideas for other important features",
                   "Earliest closely related work", "Novelty indicator"):
        assert needle in text, needle


APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")


def test_app_overview_features_and_patents_tabs(monkeypatch):
    monkeypatch.setattr(sources, "search_all", _search)
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.text_area(key="idea_text").set_value("A smart water bottle that tracks hydration using a capacitive level sensor and sends reminders to a mobile app.")
    [b for b in at.button if "Analyze" in b.label][0].click().run()
    assert not at.exception, at.exception
    labels = [m.label for m in at.metric]
    assert "Patents found" not in labels and "Novelty score" in labels and "Papers found" in labels      # patent metric removed
    status = [df.value for df in at.dataframe if "Source" in df.value.columns and "Status" in df.value.columns][0]
    assert list(status["Source"]) == ["OpenAlex"] and set(status["Status"]) == {"✅"}                     # ticks only
    assert any("How other important features can be included" in str(h.value) for h in at.subheader)
    assert any("Who has worked on this before" in e.label for e in at.expander)
    assert any("Security" in e.label for e in at.expander)
    dbs = [df.value for df in at.dataframe if "Database" in df.value.columns][0]
    assert len(dbs) >= 12 and any("InPASS" in n for n in dbs["Database"])
    assert any("Retry patent search" in b.label for b in at.button)
