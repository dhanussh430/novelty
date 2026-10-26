"""AI Novelty Analyzer - run with:  streamlit run app.py"""
import json

import pandas as pd
import streamlit as st

from novelty import patent_page, pipeline, report, sources
from novelty import features as feat, similarity as sim
from novelty.features import format_idea_features

def _stretch():
    """Full-width tables on every Streamlit version (use_container_width is removed in recent releases)."""
    try:
        major, minor = (int(x) for x in st.__version__.split(".")[:2])
        return {"width": "stretch"} if (major, minor) >= (1, 50) else {"use_container_width": True}
    except Exception:
        return {"use_container_width": True}


STRETCH = _stretch()

st.set_page_config(page_title="AI Novelty Analyzer", page_icon="💡", layout="wide")

EXAMPLE = ("A smart water bottle that tracks hydration using a capacitive level sensor and sends personalised reminders "
           "to a mobile app, adjusting the daily target based on ambient temperature and the user's activity level "
           "measured by a wearable accelerometer.")
STATE_LABEL = {"ok": "✅ OK", "partial": "⚠️ Partial", "failed": "❌ Unavailable", "skipped": "⏭️ Skipped"}

st.session_state.setdefault("history", [])
st.session_state.setdefault("analysis", None)
st.session_state.setdefault("idea_text", "")
st.session_state.setdefault("details", {})


def _load_example():
    st.session_state["idea_text"] = EXAMPLE
    st.session_state["title_text"] = "Smart hydration bottle"


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.header("⚙️ Settings")
    mode = st.radio("Analysis mode", ["⚡ Fast (recommended)", "🔬 Thorough"],
                    help="Fast: one query per source (a few seconds). Thorough: more queries per source (slower, more results).")
    enabled = []
    st.markdown("**Paper sources**")
    for name in sources.names("paper"):
        if st.checkbox(name, True, key=f"src_{name}"):
            enabled.append(name)
    st.markdown("**Patent sources**")
    for name in sources.names("patent"):
        if st.checkbox(name, True, key=f"src_{name}"):
            enabled.append(name)
    per_source = st.slider("Results per source", 5, 25, 10)
    mailto = st.text_input("Contact email (optional, speeds up OpenAlex/Crossref)", "")
    lens_token = st.text_input("Lens.org API token (optional, adds patents)", "", type="password")
    st.caption("Sources run in parallel. If one is down the others still work.")
    st.divider()
    st.subheader("🕘 Session history")
    if not st.session_state["history"]:
        st.caption("No analyses yet.")
    for h in reversed(st.session_state["history"][-8:]):
        nov = f" - novelty {h['nov']}" if h.get("nov") is not None else ""
        st.caption(f"{h['time']} - {h['title']} - similarity {h['top']}%{nov}")

# ------------------------------------------------------------------ input
st.title("💡 AI Novelty Analyzer")
st.caption("Live prior-art search (papers + patents), feature-level similarity analysis, innovation ideas and a PDF report.")
st.warning("Results show **text similarity only**. They do **not** establish legal novelty or patentability.")

title = st.text_input("Invention title", key="title_text", placeholder="e.g. Smart hydration bottle")
idea = st.text_area("Describe your invention (what it is, how it works, what is special)", key="idea_text", height=170)
custom = st.text_area("Optional: extra technical features, one per line (added to the automatically extracted ones)", height=80)
only_custom = st.checkbox("Use ONLY my features (skip automatic extraction)", False)
c1, c2, _ = st.columns([1, 1, 4])
c1.button("Load example", on_click=_load_example)
go = c2.button("🔍 Analyze", type="primary")

if go:
    if len((idea or "").split()) < 8:
        st.error("Please describe the invention in at least 8 words.")
    elif not enabled and not lens_token:
        st.error("Enable at least one source in the sidebar.")
    else:
        with st.spinner(f"Searching {len(enabled)} sources in parallel..."):
            res = pipeline.run_analysis(
                idea, title, [l for l in custom.splitlines() if l.strip()], enabled, per_source, mailto, lens_token,
                thorough=mode.startswith("🔬"), only_custom=only_custom)
        st.session_state["analysis"] = res
        st.session_state["pdf_cache"] = None
        st.session_state["history"].append({"time": res["generated_at"][11:16], "title": res["title"],
                                            "top": res["top_similarity"], "nov": (res.get("novelty") or {}).get("score")})

res = st.session_state["analysis"]

# ------------------------------------------------------------------ patent lookup (works before or after an analysis)
with st.expander("🔎 Patent Lookup - paste a Google Patents link or publication number",
                 expanded=bool(st.session_state.get("lookup") or st.session_state.get("lookup_error"))):
    st.caption("Fetches the real patent page (title, abstract, claims, inventors, dates, classes, citations, similar patents).")
    lc1, lc2 = st.columns([5, 1])
    ref = lc1.text_input("Patent link or number", key="lookup_ref", label_visibility="collapsed",
                         placeholder="https://patents.google.com/patent/US9060213B2/en   or   US9060213B2")
    if lc2.button("Fetch", key="lookup_btn"):
        st.session_state["lookup"], st.session_state["lookup_error"] = None, None
        try:
            with st.spinner("Fetching patent page..."):
                st.session_state["lookup"] = patent_page.fetch_patent(ref)
        except ValueError as e:
            st.session_state["lookup_error"] = str(e)
        except sources.SourceError as e:
            st.session_state["lookup_error"] = (patent_page.explain_error(e) + " You can open the link in your browser, or add the "
                                                "patent manually in the Patents tab.")
    if st.session_state.get("lookup_error"):
        st.error(st.session_state["lookup_error"])
    info = st.session_state.get("lookup")
    if info:
        st.subheader(info["title"])
        st.markdown(f"**{info['number']}**  ·  [Open on Google Patents]({info['url']})" +
                    (f"  ·  [PDF]({info['pdf_url']})" if info["pdf_url"] else ""))
        m1, m2, m3 = st.columns(3)
        m1.markdown("**Inventors**  \n" + (", ".join(info["inventors"][:6]) or "n/a"))
        m2.markdown("**Assignee**  \n" + (", ".join(info["assignees"][:3]) or "n/a"))
        m3.markdown(f"**Priority:** {info['priority_date'] or 'n/a'}  \n**Filed:** {info['filing_date'] or 'n/a'}  \n"
                    f"**Published:** {info['publication_date'] or 'n/a'}")
        st.markdown("**Abstract**")
        st.write(info["abstract"] or "_No abstract found on the page._")
        if info["independent_claims"]:
            st.markdown(f"**Independent claim(s)** ({len(info['independent_claims'])} of {len(info['claims'])} claims)")
            for c in info["independent_claims"][:3]:
                st.write(c)
        with st.expander(f"All claims ({len(info['claims'])})"):
            for c in info["claims"]:
                st.write(c)
        if info["cpc"]:
            with st.expander(f"Classifications ({len(info['cpc'])})"):
                st.dataframe(pd.DataFrame(info["cpc"]), **STRETCH, hide_index=True)
        if info["description"]:
            with st.expander("Description (preview)"):
                st.write(info["description"][:2500] + ("..." if len(info["description"]) > 2500 else ""))
        for label, key in (("Patent citations", "citations"), ("Cited by", "cited_by"), ("Similar documents", "similar")):
            if info[key]:
                with st.expander(f"{label} ({len(info[key])})"):
                    st.dataframe(pd.DataFrame(info[key]), **STRETCH, hide_index=True,
                                 column_config={"url": st.column_config.LinkColumn("link")})
        idea_now = (res or {}).get("idea") or " ".join((idea or "").split())
        if len(idea_now.split()) >= 8:
            feats_now = (res or {}).get("features") or feat.extract_features(idea_now)
            r0 = sim.rank(idea_now, feats_now, [patent_page.to_document(info)])[0]
            st.info(f"**Text similarity with your invention: {r0['similarity']}%** - {sim.overlap_level(r0['similarity'])}\n\n"
                    f"{r0['explanation']}")
        else:
            st.caption("Write your invention description above to see its similarity with this patent.")
        b1, b2 = st.columns(2)
        rel = patent_page.related_documents(info)
        if res is None:
            st.caption("Run **Analyze** first to add this patent to your analysis and report.")
        else:
            if b1.button("➕ Add this patent to my analysis", key="lookup_add"):
                stat = [{"source": "Google Patents (page lookup)", "kind": "patent", "ok": True, "state": "ok", "count": 1,
                         "seconds": 0.0, "message": f"fetched {info['number']}"}]
                st.session_state["analysis"] = pipeline.add_documents(res, [patent_page.to_document(info)], statuses=stat)
                st.session_state["pdf_cache"] = None
                st.rerun()
            if rel and b2.button(f"➕ Add its {len(rel)} related patents", key="lookup_add_rel"):
                stat = [{"source": "Google Patents (related)", "kind": "patent", "ok": True, "state": "ok", "count": len(rel),
                         "seconds": 0.0, "message": f"citations / similar documents of {info['number']} (titles only)"}]
                st.session_state["analysis"] = pipeline.add_documents(res, rel, statuses=stat)
                st.session_state["pdf_cache"] = None
                st.rerun()

if not res:
    st.info("Enter a description and click **Analyze**.")
    st.stop()

papers, patents = pipeline.papers(res), pipeline.patents(res)
p_state, p_count = pipeline.patent_summary(res)
tabs = st.tabs(["📊 Overview", "🧩 Features", "📚 Papers", "📜 Patents", "⚖️ Similarity", "🚀 Suggestions", "📥 Report"])


def patent_notice(key):
    """Honest, friendly explanation + retry when no patents came back (shown in the Patents tab only)."""
    if p_state == "found":
        return
    if p_state == "none":
        st.info("Patent databases responded, but nothing matched these search terms. Try broader wording, or check the "
                "official databases below.")
    else:
        st.warning("The live patent databases did not respond this time (temporary problem on their side, not in your setup).")
        for stt in res["statuses"]:
            if stt.get("kind") == "patent" and not stt["ok"] and stt.get("state") != "skipped":
                st.caption(f"• {stt['source']}: {stt['message']}")
    if st.button("🔁 Retry patent search", key=key):
        try:
            with st.spinner("Retrying patent sources..."):
                st.session_state["analysis"] = pipeline.retry_patents(res, enabled, per_source, mailto, lens_token)
            st.session_state["pdf_cache"] = None
            st.rerun()
        except ValueError as e:
            st.error(str(e))


def prior_work_panel(expanded):
    pw = res.get("prior_work") or {}
    with st.expander("🌍 Who has worked on this before? Worldwide analysis of the retrieved documents", expanded=expanded):
        if not pw.get("available"):
            st.info(pw.get("paragraphs", ["Nothing to analyse yet."])[0])
            return
        for para in pw["paragraphs"]:
            st.markdown(para)
        st.markdown("**Closest existing works**")
        st.dataframe(pd.DataFrame([{"Rank": d["rank"], "Title": d["title"], "Year": d["year"], "Type": d["kind"],
                                    "Authors": ", ".join(d["authors"][:3]), "Source": d["source"],
                                    "Similarity %": d["similarity"], "Link": d["url"]} for d in pw["closest"]]),
                     hide_index=True, **STRETCH, column_config={"Link": st.column_config.LinkColumn("Link")})
        c1, c2, c3 = st.columns(3)
        if pw["countries"]:
            c1.markdown("**Countries**")
            c1.dataframe(pd.DataFrame(pw["countries"], columns=["Country", "Documents"]), hide_index=True, **STRETCH)
        if pw["institutions"]:
            c2.markdown("**Institutions**")
            c2.dataframe(pd.DataFrame(pw["institutions"], columns=["Institution", "Documents"]), hide_index=True, **STRETCH)
        if pw["venues"]:
            c3.markdown("**Journals / venues**")
            c3.dataframe(pd.DataFrame(pw["venues"], columns=["Venue", "Documents"]), hide_index=True, **STRETCH)
        if pw["timeline"]:
            st.markdown("**Documents per year**")
            st.bar_chart(pd.Series(pw["timeline"]))
        if not pw["countries"] and not pw["institutions"]:
            st.caption("Country and institution data come from OpenAlex; enable it in Settings for this part of the analysis.")


def patent_details_block(d):
    """Optional: load the full patent page (claims, classes, inventors) for one patent."""
    num = d["identifier"]
    det = st.session_state["details"].get(num)
    err = st.session_state["details"].get(num + "_err")
    if st.button("🔍 Load full patent details (claims, classes, dates)", key=f"full_{d['kind']}_{d['rank']}_{num}"):
        st.session_state["details"].pop(num + "_err", None)
        try:
            with st.spinner("Fetching patent page..."):
                st.session_state["details"][num] = patent_page.fetch_patent(num)
        except (ValueError, sources.SourceError) as e:
            st.session_state["details"][num + "_err"] = patent_page.explain_error(e)
        st.rerun()
    if err:
        st.warning(err)
    if det:
        st.markdown("**Inventors:** " + (", ".join(det["inventors"][:6]) or "n/a") + "  |  **Assignee:** " + (", ".join(det["assignees"][:2]) or "n/a"))
        st.markdown(f"**Priority:** {det['priority_date'] or 'n/a'}  |  **Filed:** {det['filing_date'] or 'n/a'}  |  **Published:** {det['publication_date'] or 'n/a'}")
        if det["independent_claims"]:
            st.markdown(f"**Independent claim 1** ({len(det['claims'])} claims in total)")
            st.write(det["independent_claims"][0][:1500])
        if det["cpc"]:
            st.markdown("**Classes:** " + "; ".join(f"{c['code']} {c['description']}".strip() for c in det["cpc"][:6]))
        if det["pdf_url"]:
            st.markdown(f"[Download patent PDF]({det['pdf_url']})")


def show_docs(docs, empty_msg):
    if not docs:
        st.info(empty_msg)
    for d in docs:
        is_pat = d["kind"] == "patent"
        with st.expander(f"#{d['rank']}  {d['title']}  -  {d['similarity']}%  ({d['year'] or 'n/a'})",
                         expanded=bool(is_pat and d["identifier"] in st.session_state["details"])):
            if is_pat:
                st.markdown(f"**Publication no.:** {d['identifier'] or 'n/a'}  |  **Source:** {d['source']}  |  "
                            f"**Inventor(s):** {', '.join(d['authors'][:4]) or 'n/a'}  |  "
                            f"**Assignee:** {d.get('assignee') or d.get('venue') or 'n/a'}")
                dates = [f"{k}: {d[f]}" for k, f in (("Priority", "priority_date"), ("Filed", "filing_date"), ("Published", "publication_date")) if d.get(f)]
                if dates:
                    st.caption("  |  ".join(dates))
            else:
                st.markdown(f"**Source:** {d['source']}  |  **ID:** {d['identifier'] or 'n/a'}  |  "
                            f"**Authors:** {', '.join(d['authors'][:6]) or 'n/a'}")
            if d["url"]:
                st.markdown(f"[Open source record]({d['url']})")
            st.write(d["abstract"] or ("_No snippet available from the source._" if is_pat else "_Abstract not available from the source._"))
            st.caption(d["explanation"])
            if is_pat and d["identifier"]:
                patent_details_block(d)


with tabs[0]:
    nv = res.get("novelty") or {}
    a, c, d_, e = st.columns(4)
    a.metric("Papers found", len(papers))
    c.metric("Top text similarity", f"{res['top_similarity']}%")
    d_.metric("Novelty score", f"{nv['score']}/100" if nv.get("score") is not None else "N/A",
              help="Indicative heuristic (higher = fewer close matches found). Not a legal opinion.")
    e.metric("Features extracted", len(res["features"]))
    st.caption(f"⏱️ Analysis finished in {res.get('elapsed', '?')} s")

    st.subheader("🆕 Novelty assessment")
    if nv.get("score") is None:
        st.warning(nv.get("label", "Novelty cannot be assessed."))
    else:
        st.progress(min(100, int(nv["score"])) / 100, text=f"Novelty score {nv['score']}/100 - {nv['label']}")
        st.markdown(f"**Confidence:** {nv['confidence']}  ·  based on {nv['components']['documents']} documents "
                    f"({nv['components']['patents']} patents)")
        for n_ in nv.get("notes", []):
            st.write("• " + n_)
        with st.expander("How is the novelty score calculated?"):
            comp = nv["components"]
            st.write("Score = 100 × (0.4 × (1 − best similarity) + 0.2 × (1 − mean of top-5 similarities) + "
                     "0.4 × share of your features not clearly covered by any top document).")
            st.table(pd.DataFrame({"Component": ["Best similarity", "Mean top-5 similarity", "Features not covered", "Documents analysed"],
                                   "Value": [f"{comp['best_similarity_pct']}%", f"{comp['top5_mean_similarity_pct']}%",
                                             f"{comp['uncovered_feature_share_pct']}%", str(comp["documents"])]}))
            if nv.get("uncovered_features"):
                st.write("Potentially differentiating features (not clearly covered): " + "; ".join(nv["uncovered_features"]))
        st.caption(nv["disclaimer"])
    st.progress(min(100, int(res["top_similarity"])) / 100, text=f"Text-overlap gauge: {res['overlap_level']}")

    st.subheader("Source status")
    good = [x for x in res["statuses"] if x["ok"] and x.get("state") != "skipped"]
    if good:
        st.dataframe(pd.DataFrame([{"Source": x["source"], "Type": x["kind"], "Status": "✅", "Records": x["count"],
                                    "Time (s)": x.get("seconds", 0)} for x in good]), hide_index=True, **STRETCH)
    else:
        st.warning("No source responded. Check your internet connection and press Analyze again.")
    years = pd.Series([d["year"] for d in res["ranked"] if d["year"]]).value_counts().sort_index()
    if not years.empty:
        st.subheader("Publication timeline of retrieved documents")
        st.bar_chart(years)

with tabs[1]:
    st.markdown(f"**{format_idea_features(res['features'])}**")
    for i, f in enumerate(res["features"], 1):
        st.write(f"{i}. {f}")
    st.markdown("**Keywords:** " + ", ".join(res["keywords"]))
    st.markdown("**Generated search queries:** " + " | ".join(f"`{q}`" for q in res["queries"]))
    st.subheader("🚀 How other important features can be included")
    st.caption("Ideas to strengthen your project. Items marked ⚠️ should be checked against prior art before you claim them as new.")
    ideas = res.get("feature_ideas") or []
    for it in ideas:
        icon = "✅" if it["status"].startswith("Already") else "💡"
        with st.expander(f"{icon} {it['category']}  -  {it['status']}", expanded=False):
            st.markdown(f"**How to include it:** {it['how']}")
            st.markdown(f"**Why it helps:** {it['benefit']}")
            st.markdown(f"**Effort:** {it['effort']}" + ("  ·  ⚠️ verify against prior art before claiming" if it["needs_verification"] else ""))

with tabs[2]:
    show_docs(papers, "No research papers were retrieved. Check source status in Overview or broaden the wording.")

with tabs[3]:
    show_docs(patents, "No patent records could be retrieved automatically. See the worldwide analysis and the official patent "
                       "databases below.")
    patent_notice("retry_patents")
    prior_work_panel(expanded=(p_state != "found"))
    st.markdown("#### 🔎 Check patents on official and established databases")
    st.caption("Your search terms are pre-filled where the site supports it. Searching several offices gives the best coverage.")
    dbs = sources.patent_search_links(res["queries"])
    st.dataframe(pd.DataFrame([{"Database": x["name"], "Region": x["region"], "Open": x["url"], "About": x["note"],
                                "Terms pre-filled": "Yes" if x["prefilled"] else "No (paste the terms)"} for x in dbs]),
                 hide_index=True, **STRETCH, column_config={"Open": st.column_config.LinkColumn("Open", display_text="Open ↗")})
    st.code(" ".join(res["queries"][1].split()[:4]) if len(res["queries"]) > 1 else (res["queries"][0] if res["queries"] else ""),
            language=None)
    st.caption("↑ Search terms to paste when a site does not pre-fill them.")
    st.markdown("#### ➕ Add patents you found (included in similarity ranking and the PDF)")
    with st.expander("Upload a CSV (Google Patents → Download (CSV))"):
        up = st.file_uploader("CSV file", type="csv", key="patent_csv")
        if up is not None and st.button("Import CSV"):
            try:
                docs = sources.parse_patent_csv(up.getvalue().decode("utf-8", errors="replace"))
                if not docs:
                    st.warning("No patent rows found in that file.")
                else:
                    st.session_state["analysis"] = pipeline.add_documents(res, docs)
                    st.session_state["pdf_cache"] = None
                    st.rerun()
            except ValueError as e:
                st.error(str(e))
    with st.expander("Add one patent manually"):
        with st.form("manual_patent", clear_on_submit=True):
            m_no = st.text_input("Publication number (e.g. US10123456B2)")
            m_title = st.text_input("Title")
            m_abs = st.text_area("Abstract (recommended)")
            m_url = st.text_input("Link (optional)")
            if st.form_submit_button("Add patent"):
                try:
                    doc = sources.make_patent(m_no, m_title, m_abs, m_url)
                    st.session_state["analysis"] = pipeline.add_documents(res, [doc])
                    st.session_state["pdf_cache"] = None
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))

with tabs[4]:
    st.caption(res["disclaimer"])
    if res["ranked"]:
        df = pd.DataFrame([{"Rank": d["rank"], "Type": d["kind"], "Source": d["source"], "Title": d["title"], "Year": d["year"],
                            "Similarity %": d["similarity"], "Cosine %": d["cosine"], "Feature coverage %": d["coverage"]}
                           for d in res["ranked"]])
        st.dataframe(df, **STRETCH, hide_index=True, column_config={
            "Similarity %": st.column_config.ProgressColumn("Similarity %", min_value=0, max_value=100, format="%.1f")})
        st.subheader("Feature coverage matrix (top 8)")
        top8 = res["ranked"][:8]
        mat = {f"#{d['rank']}": ["✔" if d["feature_scores"].get(f, 0) >= .6 else "◐" if d["feature_scores"].get(f, 0) >= .3 else "✘"
                                 for f in res["features"]] for d in top8}
        st.dataframe(pd.DataFrame(mat, index=res["features"]), **STRETCH)
        st.caption("✔ covered   ◐ partly   ✘ not evidenced in title/abstract")
        st.subheader("Side-by-side comparison")
        pick = st.selectbox("Choose a document", res["ranked"], format_func=lambda d: f"#{d['rank']} {d['title'][:80]}")
        l, r = st.columns(2)
        l.markdown("**Your invention**")
        l.write(res["idea"])
        r.markdown(f"**{pick['title']}**")
        r.write(pick["abstract"] or "_No abstract available._")
        st.info(pick["explanation"])
    else:
        st.info("Nothing to compare: no documents were retrieved.")

with tabs[5]:
    for sg in res["suggestions"]:
        badge = "⚠️ Needs verification" if sg["needs_verification"] else "✅ General practice"
        st.markdown(f"**{sg['title']}**  \n`{badge}` · _{sg['type']}_  \n{sg['rationale']}")
        st.divider()

with tabs[6]:
    st.write(f"This report reflects analysis run **{res['run_id']}** generated at **{res['generated_at']}**.")
    cache = st.session_state.get("pdf_cache")
    if not cache or cache[0] != res["run_id"]:
        try:
            cache = (res["run_id"], report.build_pdf(res))
        except Exception as e:  # keep the app alive if PDF creation fails
            cache = None
            st.error(f"PDF generation failed: {e}")
        st.session_state["pdf_cache"] = cache
    stamp = res["generated_at"].replace(":", "").replace("-", "").replace(" ", "_")
    if cache:
        st.download_button("⬇️ Download PDF report", cache[1], f"novelty_report_{stamp}.pdf", "application/pdf")
    st.download_button("⬇️ Download JSON", json.dumps(res, indent=2), f"novelty_{stamp}.json", "application/json")
    if res["ranked"]:
        csv = pd.DataFrame(res["ranked"]).drop(columns=["feature_scores"]).to_csv(index=False)
        st.download_button("⬇️ Download CSV of results", csv, f"novelty_{stamp}.csv", "text/csv")
