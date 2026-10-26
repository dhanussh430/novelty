"""PDF report builder (ReportLab). Uses only built-in Latin-1 fonts, so text is sanitised to avoid black boxes."""
import io
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from .sources import patent_search_links
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


_REPL = {"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-", "\u2014": "-", "\u2026": "...",
         "\u00a0": " ", "\u2212": "-", "\u2192": "->", "\u2265": ">=", "\u2264": "<="}
NAVY = colors.HexColor("#1f3a5f")
LIGHT = colors.HexColor("#eef2f7")


def _t(text) -> str:
    s = str(text if text is not None else "")
    for k, v in _REPL.items():
        s = s.replace(k, v)
    return escape(s.encode("latin-1", "replace").decode("latin-1"))


def _link(url) -> str:
    if not url:
        return "n/a"
    u = _t(url).replace('"', "&quot;")
    return f'<link href="{u}" color="blue">{u}</link>'


def _styles():
    ss = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("T", parent=ss["Title"], textColor=NAVY, fontSize=22, leading=26),
        "h1": ParagraphStyle("H1", parent=ss["Heading1"], textColor=NAVY, fontSize=14, spaceBefore=12, spaceAfter=6),
        "h2": ParagraphStyle("H2", parent=ss["Heading2"], textColor=NAVY, fontSize=11, spaceBefore=8, spaceAfter=3),
        "p": ParagraphStyle("P", parent=ss["BodyText"], fontSize=9, leading=12),
        "small": ParagraphStyle("S", parent=ss["BodyText"], fontSize=8, leading=10),
        "link": ParagraphStyle("L", parent=ss["BodyText"], fontSize=7.5, leading=9.5, wordWrap="CJK"),
        "warn": ParagraphStyle("W", parent=ss["BodyText"], fontSize=8.5, leading=11, backColor=colors.HexColor("#fff4d6"),
                               borderPadding=5, borderColor=colors.HexColor("#e0b84a"), borderWidth=0.5),
    }


def _table(rows, widths, st, header=True):
    data = [[c if not isinstance(c, str) else Paragraph(c, st["small"]) for c in r] for r in rows]
    t = Table(data, colWidths=[w * mm for w in widths], repeatRows=1 if header else 0)
    style = [("GRID", (0, 0), (-1, -1), 0.3, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), NAVY)]
        data[0] = [Paragraph(f'<font color="white"><b>{c}</b></font>' if isinstance(c, str) else c, st["small"]) for c in rows[0]]
        t = Table(data, colWidths=[w * mm for w in widths], repeatRows=1)
    t.setStyle(TableStyle(style))
    return t


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.grey)
    canvas.drawString(15 * mm, 8 * mm, "AI Novelty Analysis Report - text similarity only, not legal advice")
    canvas.drawRightString(195 * mm, 8 * mm, f"Page {doc.page}")
    canvas.restoreState()


def build_pdf(result: dict) -> bytes:
    st = _styles()
    ranked = result.get("ranked", [])
    papers = [d for d in ranked if d["kind"] == "paper"]
    patents = [d for d in ranked if d["kind"] == "patent"]
    s = []

    s += [Paragraph("AI Novelty Analysis Report", st["title"]),
          Paragraph(f"<b>Invention:</b> {_t(result['title'])}", st["p"]),
          Paragraph(f"<b>Generated:</b> {_t(result['generated_at'])} &nbsp;|&nbsp; <b>Run ID:</b> {_t(result['run_id'])}", st["p"]),
          Spacer(1, 6), Paragraph("<b>Important:</b> " + _t(result["disclaimer"]), st["warn"]), Spacer(1, 6)]

    s += [Paragraph("1. Invention Description", st["h1"]), Paragraph(_t(result["idea"]), st["p"])]

    s += [Paragraph("2. Extracted Technical Features", st["h1"]),
          Paragraph("<b>Idea Features:</b>", st["p"])]
    for i, f in enumerate(result["features"], 1):
        s.append(Paragraph(f"{i}. {_t(f)}", st["p"]))
    s += [Spacer(1, 4), Paragraph("<b>Keywords:</b> " + _t(", ".join(result["keywords"])), st["p"]),
          Paragraph("<b>Search queries used:</b> " + _t(" | ".join(result["queries"])), st["p"])]

    s.append(Paragraph("3. Data Sources and Status", st["h1"]))
    LBL = {"ok": "OK", "partial": "Partial", "failed": "Unavailable", "skipped": "Skipped"}
    rows = [["Source", "Type", "Status", "Records", "Details"]] + [
        [_t(x["source"]), _t(x["kind"]), LBL.get(x.get("state"), "OK" if x["ok"] else "Unavailable"), str(x["count"]), _t(x["message"])]
        for x in result["statuses"]]
    s.append(_table(rows, [34, 16, 22, 16, 92], st))

    def doc_table(docs, label):
        if not docs:
            msg = f"No {label} were retrieved automatically. This is reported honestly; no placeholder records are shown."
            extra = []
            if label == "patent records":
                why = "; ".join(f"{x['source']}: {x['message']}" for x in result["statuses"] if x["kind"] == "patent" and not x["ok"])
                if why:
                    msg += " Reasons - " + why + "."
                pw = result.get("prior_work") or {}
                if pw.get("available"):
                    extra.append(Paragraph("<b>Worldwide prior-work analysis (from the retrieved research papers)</b>", st["h2"]))
                    extra += [Paragraph(_t(p_.replace("**", "")), st["small"]) for p_ in pw["paragraphs"]]
                extra.append(Paragraph("<b>Official / established patent databases to check manually</b>", st["h2"]))
                for db in patent_search_links(result["queries"]):
                    extra.append(Paragraph(f"<b>{_t(db['name'])}</b> ({_t(db['region'])}) - {_t(db['note'])}: " + _link(db["url"]), st["link"]))
            return [Paragraph(_t(msg), st["p"])] + extra
        rows = [["#", "Title", "Authors / Assignee", "Year", "Identifier", "Sim."]]
        for d in docs:
            rows.append([str(d["rank"]), _t(d["title"]), _t(", ".join(d["authors"][:3]) or "n/a"),
                         str(d["year"] or "n/a"), _t(d["identifier"] or "n/a"), f"{d['similarity']}%"])
        out = [_table(rows, [8, 70, 40, 12, 36, 14], st), Spacer(1, 4)]
        for d in docs:
            out.append(Paragraph(f"<b>{d['rank']}. {_t(d['title'])}</b> ({_t(d['source'])})", st["p"]))
            out.append(Paragraph("Source link: " + _link(d["url"]), st["link"]))
            ab = d["abstract"] or "Abstract not available from the source."
            out.append(Paragraph("Abstract: " + _t(ab[:700] + ("..." if len(ab) > 700 else "")), st["small"]))
            out.append(Spacer(1, 4))
        return out

    s.append(Paragraph("4. Research Paper Results", st["h1"]))
    s += doc_table(papers, "research papers")
    s.append(Paragraph("5. Patent Results", st["h1"]))
    s += doc_table(patents, "patent records")

    s.append(Paragraph("6. Similarity Analysis", st["h1"]))
    s.append(Paragraph(f"<b>Highest text similarity:</b> {result['top_similarity']}% - {_t(result['overlap_level'])}", st["p"]))
    nv = result.get("novelty") or {}
    if nv.get("score") is not None:
        s.append(Paragraph(f"<b>Novelty indicator (heuristic): {nv['score']} / 100</b> - {_t(nv['label'])}. "
                           f"Confidence: {_t(nv['confidence'])}.", st["p"]))
        c = nv.get("components", {})
        s.append(Paragraph(_t(f"Basis: best similarity {c.get('best_similarity_pct')}%, mean of top-5 {c.get('top5_mean_similarity_pct')}%, "
                              f"features not clearly covered {c.get('uncovered_feature_share_pct')}%, documents analysed {c.get('documents')} "
                              f"(patents {c.get('patents')}). " + " ".join(nv.get("notes", []))), st["small"]))
    else:
        s.append(Paragraph("<b>Novelty indicator:</b> " + _t(nv.get("label", "not available")), st["p"]))
    s.append(Paragraph(_t(nv.get("disclaimer", "")), st["small"]))
    s.append(Paragraph("Method: similarity = 50% TF-IDF cosine similarity (idea vs. title+abstract) + 50% average feature "
                       "coverage (share of each feature's key terms found in the document). This is text similarity only. "
                       "It is not legally established novelty.", st["small"]))
    if ranked:
        rows = [["Rank", "Document", "Type", "Similarity", "Cosine", "Feature coverage"]] + [
            [str(d["rank"]), _t(d["title"][:90]), d["kind"], f"{d['similarity']}%", f"{d['cosine']}%", f"{d['coverage']}%"]
            for d in ranked[:25]]
        s += [Spacer(1, 4), _table(rows, [10, 82, 16, 22, 18, 32], st)]

    s.append(Paragraph("7. Detailed Comparisons (top 10)", st["h1"]))
    for d in ranked[:10]:
        s += [Paragraph(f"#{d['rank']} {_t(d['title'])} - {d['similarity']}%", st["h2"]),
              Paragraph(_t(d["explanation"]), st["small"])]
    if not ranked:
        s.append(Paragraph("Nothing to compare because no documents were retrieved.", st["p"]))
    top5 = ranked[:5]
    if top5 and result["features"]:
        s.append(Paragraph("Feature coverage matrix (top 5 documents)", st["h2"]))
        rows = [["Feature"] + [f"#{d['rank']}" for d in top5]]
        for f in result["features"]:
            rows.append([_t(f)] + ["Yes" if d["feature_scores"].get(f, 0) >= 0.6 else
                                   "Partial" if d["feature_scores"].get(f, 0) >= 0.3 else "No" for d in top5])
        s.append(_table(rows, [80] + [20] * len(top5), st))

    s.append(Paragraph("8. Innovation Suggestions", st["h1"]))
    for sg in result["suggestions"]:
        tag = "NEEDS VERIFICATION" if sg["needs_verification"] else "General practice"
        s.append(Paragraph(f"<b>{_t(sg['title'])}</b> [{tag}]<br/>{_t(sg['rationale'])}", st["p"]))
        s.append(Spacer(1, 3))

    fi = result.get("feature_ideas") or []
    if fi:
        s.append(Paragraph("Ideas for other important features", st["h2"]))
        for f in fi:
            tag = f["status"] + ("; verify against prior art before claiming" if f["needs_verification"] else "")
            s.append(Paragraph(f"<b>{_t(f['category'])}</b> [{_t(tag)}; effort: {_t(f['effort'])}]<br/>How: {_t(f['how'])} "
                               f"Benefit: {_t(f['benefit'])}", st["small"]))
            s.append(Spacer(1, 2))

    s.append(Paragraph("9. Limitations", st["h1"]))
    for lim in ["Similarity is computed from titles, abstracts or snippets only, not full text or patent claims.",
                "Search sources return a limited number of results; relevant documents may be missed.",
                "Patent coverage depends on source availability; unofficial endpoints may be blocked or change.",
                "Feature extraction is rule-based and may split or merge concepts; edit features manually for better results.",
                "Suggestions are heuristic starting points and marked where verification is needed.",
                "This report is not legal advice and does not establish novelty, inventive step or freedom to operate."]:
        s.append(Paragraph("- " + _t(lim), st["p"]))

    s.append(Paragraph("10. Source Links", st["h1"]))
    if ranked:
        for d in ranked:
            s.append(Paragraph(f"{d['rank']}. {_t(d['title'][:80])}: " + _link(d["url"]), st["link"]))
    else:
        s.append(Paragraph("No source documents to link.", st["p"]))

    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm,
                      bottomMargin=16 * mm, title=f"Novelty Report - {result['title']}"[:100]).build(
        s, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()
