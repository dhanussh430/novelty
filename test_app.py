import os

from streamlit.testing.v1 import AppTest

from novelty import sources
from tests.test_all import _docs

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
OK = [{"source": "Fake", "kind": "paper", "ok": True, "state": "ok", "count": 2, "seconds": 0.1, "message": "OK"}]
BAD = OK + [{"source": "Google Patents", "kind": "patent", "ok": False, "state": "failed", "count": 0, "seconds": 0.2,
             "message": "Temporarily unavailable (HTTP 503)"}]


def _analyze(at):
    at.text_area(key="idea_text").set_value("A smart water bottle that tracks hydration using a capacitive level sensor and sends reminders to a mobile app.")
    at.text_input(key="title_text").set_value("Bottle")
    [b for b in at.button if "Analyze" in b.label][0].click().run()


def test_app_end_to_end(monkeypatch):
    monkeypatch.setattr(sources, "search_all", lambda q, **k: (_docs(), OK))
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    _analyze(at)
    assert not at.exception, at.exception
    assert at.session_state["analysis"]["title"] == "Bottle"
    assert at.session_state["pdf_cache"][1].startswith(b"%PDF")
    assert any(m.label == "Novelty score" and "/100" in str(m.value) for m in at.metric)
    assert any("Novelty assessment" in str(sh.value) for sh in at.subheader)
    # patent cards are shown like papers, with a details button
    assert any("Load full patent details" in b.label for b in at.button)


def test_app_shows_friendly_state_and_retry_when_patents_unavailable(monkeypatch):
    calls = {"n": 0}

    def search(q, **k):
        calls["n"] += 1
        if k["enabled"] and all(sources.REGISTRY[n]["kind"] == "patent" for n in k["enabled"]):
            return [sources._doc("patent", "Hydration bottle sensor patent", [], 2019, "a bottle with a hydration sensor", "http://p", "US1B2", "Google Patents")], [
                {"source": "Google Patents", "kind": "patent", "ok": True, "state": "ok", "count": 1, "seconds": 0.3, "message": "OK"}]
        return [d for d in _docs() if d["kind"] == "paper"], BAD
    monkeypatch.setattr(sources, "search_all", search)
    at = AppTest.from_file(APP, default_timeout=60).run()
    _analyze(at)
    assert not at.exception, at.exception
    assert not any(m.label == "Patents found" for m in at.metric)           # no patent metric in the Overview
    assert at.session_state["analysis"]["prior_work"]["available"]          # worldwide analysis still shown in Patents tab
    retry = [b for b in at.button if "Retry patent" in b.label][0]
    retry.click().run()
    assert not at.exception, at.exception
    from novelty import pipeline
    assert pipeline.patent_summary(at.session_state["analysis"]) == ("found", 1)


def test_patent_card_loads_full_details(monkeypatch):
    from novelty import patent_page as pp
    from tests.test_patent_page import HTML, Resp
    pat = sources._doc("patent", "Hydration bottle sensor", ["Joe"], 2019, "bottle with hydration sensor", "http://p", "US1234567B2", "Google Patents")
    monkeypatch.setattr(sources, "search_all", lambda q, **k: ([pat], OK))
    monkeypatch.setattr(pp.sources.requests, "get", lambda *a, **k: Resp(200, HTML))
    at = AppTest.from_file(APP, default_timeout=60).run()
    _analyze(at)
    [b for b in at.button if "Load full patent details" in b.label][0].click().run()
    assert not at.exception, at.exception
    assert at.session_state["details"]["US1234567B2"]["title"] == "Smart bottle with hydration sensor"
    # failure path: friendly warning, no crash
    sources.clear_cache()
    at.session_state["details"].clear()
    monkeypatch.setattr(pp.sources.requests, "get", lambda *a, **k: Resp(503))
    [b for b in at.button if "Load full patent details" in b.label][0].click().run()
    assert not at.exception and "US1234567B2_err" in at.session_state["details"]
