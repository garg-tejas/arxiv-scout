# ArXiv Literature Scout

A research tool that helps you find relevant papers on any topic, lets you steer the search conversationally, and optionally compiles everything into a structured literature survey.

The idea is simple: you type a topic, the system finds papers, you tell it what's relevant and what isn't, and it learns from that as it goes. If you want, it can then take your approved papers and write a survey with proper section structure, citations, and a method comparison table.

---

## What it does

**Discovery** — You enter a topic (even a vague one) and the system interprets it, expands it into a few search angles, and shows you what it found before touching any API. You confirm the interpretation, review the shortlist, and nudge it toward what you actually want. Each nudge updates a running preference profile — so saying "skip survey papers" once applies to every subsequent fetch, not just the current one.

**Analysis** — Once you approve a set of papers, the system reads them properly — not just abstracts, but full paper content where available. It extracts core claims, methodology, datasets, metrics, and limitations for each one. It also builds a citation graph across your approved papers with one-hop expansion, so you can see which papers are foundational, which ones extend earlier work, and where the actual lineage runs.

**Survey (optional)** — If you want a compiled survey, you can provide a brief describing the angle you want, or skip it and let the system synthesize one from your search history and steering preferences. It then clusters your papers into themes, writes a section per cluster, runs a self-critique pass on each section, assembles everything, and gives you a final Markdown file to download.

There are four human checkpoints across the whole flow — one to confirm topic interpretation before any API calls, one to approve or redirect the paper shortlist, one to set the survey angle, and one to approve the final output. None of them are mandatory gates that block you; they're decision points where your input actually changes what happens next.

---

## Tech stack

- **Backend** — FastAPI, LangGraph, SQLite
- **Discovery** — Semantic Scholar API, arXiv API
- **Paper extraction** — Firecrawl (falls back to abstract + metadata if full text parsing fails)
- **LLM** — Gemini 2.0 Flash (GLM 4.7 Flash as fallback)
- **Frontend** — React

---

## Getting started

```bash
# Clone the repo
git clone https://github.com/garg-tejas/arxiv-literature-scout
cd arxiv-literature-scout

# Backend
cd backend
cp .env.example .env
# Add your API keys to .env
pip install -r requirements.txt
uvicorn app.main:app --reload

# Frontend
cd ../frontend
npm install
npm run dev
```

You'll need API keys for Semantic Scholar, Firecrawl, and Gemini. arXiv needs no key.

---

## Environment variables

```
GEMINI_API_KEY=
GLM_API_KEY=
FIRECRAWL_API_KEY=
SEMANTIC_SCHOLAR_API_KEY=
```

---

## How a session works

1. Enter a topic — the system shows you how it interpreted it and what search angles it'll use
2. Confirm or correct the interpretation
3. Review the paper shortlist — approve what's relevant, nudge toward what's missing
4. Repeat until the shortlist looks right
5. Start analysis on up to 8 approved papers
6. View per-paper summaries, the method comparison table, and the citation graph
7. Optionally compile a survey — provide a brief or skip it
8. Review and download the final Markdown

Sessions persist for 7 days of inactivity. Everything is stored in SQLite — no files on disk.

---

## Limitations worth knowing

- Analysis is capped at 8 papers per run. You can approve more during discovery, but you pick which 8 to analyze.
- Full paper extraction via Firecrawl can be noisy on math-heavy papers. When quality is poor, the system falls back to abstract-level analysis and marks it clearly.
- The citation graph is built from Semantic Scholar data, so papers with low indexing coverage may have sparse citation edges.
- Survey writing is as good as the underlying papers and the model. It won't hallucinate citations since it works strictly from structured extraction, but synthesis quality varies.
- PDF export is not in v1. Download is Markdown only.

---

## Project structure

```
backend/
  app/          # FastAPI routes, config, SSE endpoint
  graph/        # LangGraph phase graphs (discovery, analysis, survey)
  models/       # Pydantic schemas
  integrations/ # API adapters (Semantic Scholar, arXiv, Firecrawl, Gemini)
  persistence/  # SQLite store, LangGraph checkpointer, cleanup
  services/     # Session, streaming, artifact, and revision logic

frontend/
  src/          # App shell, API/SSE clients, Discovery/Analysis/Survey views
```

---

Built as part of an ML internship application project. Feedback welcome.
