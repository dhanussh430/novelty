# AI Novelty Analyzer v2.0

Live prior-art search (papers + patents), feature-level similarity ranking, innovation suggestions and a downloadable PDF report.

## Run in VS Code
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```
Tests: `pip install -r requirements-dev.txt` then `python -m pytest -q`  (64 tests)

## Data sources (all searched in parallel)
| Type | Sources | Key needed |
|---|---|---|
| Papers | OpenAlex, Crossref, Semantic Scholar, arXiv, Europe PMC, DOAJ, Zenodo | No |
| Patents | Google Patents (unofficial), Europe PMC Patents (life-science focus) | No |
| Patents | Lens.org (optional, paste token in sidebar) | Yes |

PatentsView was **removed**: the USPTO shut that API down on 20 March 2026.

## What each tab shows
- **Overview:** papers found, text similarity, novelty score, features, and a Source status table that lists only the sources that responded (✅).
- **Features:** extracted features plus **ideas for other important features** (security, APIs, personalisation, alerts, offline mode, energy, compliance, accessibility, scalability, cost, validation) with how to include each and an effort level.
- **Patents:** patent cards (when retrieved). If none can be retrieved: a **worldwide analysis of who worked on this before** (earliest work, closest works, countries, institutions, venues, timeline - built only from retrieved documents) and 13 official / established patent databases (Google Patents, Espacenet, WIPO PATENTSCOPE, The Lens, FreePatentsOnline, USPTO, India InPASS, Germany, Japan, Korea, China, Australia, Canada) with your search terms pre-filled where supported.

## Novelty score (Overview tab)
Indicative score 0-100 (higher = fewer close matches found) with a confidence level (based on how many documents and
patents were retrieved) and the exact formula. It is a text-based heuristic, NOT a legal novelty opinion. If no documents are
retrieved it shows "N/A" instead of a misleading number.

## Patent search
Google Patents search uses a relevance filter (65% keyword coverage + 35% TF-IDF) and retries once on HTTP 429/503.
Patents appear as cards like papers: publication number, inventors, assignee, dates, snippet, similarity, link and a
**Load full patent details** button (claims, classes). If Google does not answer, no placeholder rows are shown; you get a
clear status, a Retry button and manual search links.

## Patent Lookup (paste a link)
Open **🔎 Patent Lookup**, paste a Google Patents link such as `https://patents.google.com/patent/US9060213B2/en`
(or just `US9060213B2`) and press **Fetch**. The app downloads that page and shows the title, abstract, claims, inventors,
assignee, dates, CPC classes, citations, cited-by and similar patents, plus its text similarity with your invention.
After an analysis you can add the patent (or its related patents) to the ranking and the PDF report.
If Google blocks the request you get a clear message; open the link in your browser or add the patent manually.

## What "HTTP 503" means
503 = the remote service is overloaded or is throttling automated requests. It is a temporary problem on the
source's side. The app sends only ONE careful request to Google Patents and never retries in a loop. If it still
fails, press **Retry patent search** after a minute. Results are cached for 30 minutes so repeated analyses are fast and
do not trigger throttling.

## Speed
Fast mode (default) runs one query per source, all sources at the same time (typically a few seconds).
Thorough mode runs more queries per source.

## If the Patents tab is empty
Use the manual search links, upload the CSV from Google Patents (Download -> CSV), or add a patent by hand.
Imported patents join the similarity ranking and the PDF.

## Notes
- Similarity = 50% TF-IDF cosine + 50% feature coverage on titles/abstracts. It is text similarity, NOT legal novelty.
- "Optional features" you type are ADDED to automatically extracted features (tick "Use ONLY my features" to override).
