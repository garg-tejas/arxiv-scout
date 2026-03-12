# ArXiv Literature Scout

ArXiv Literature Scout is a small research assistant that helps you go from a vague topic to a curated paper set and, if you want, a structured survey in Markdown.

You give it a topic. It proposes search angles, pulls papers, lets you steer what counts as “relevant”, runs proper per‑paper analysis, and can finally draft a survey with sections, a method comparison table, and references.

The point is not to replace reading. It’s to automate the boring bits around discovery and comparison so you can spend your time actually understanding the papers.

---

## What it does

### Discovery

- Takes a free‑text topic and turns it into:
  - a normalized topic string, and
  - 3–4 distinct search angles.
- Uses **Semantic Scholar** and **arXiv** to fetch candidates for each angle.
- Runs a **single batched LLM curation step** to:
  - pick a shortlist; and
  - build a preliminary “method extraction” table (model type, datasets, metrics, benchmarks).
- Lets you:
  - confirm or tweak the interpreted topic,
  - approve or replace the shortlist,
  - “nudge” discovery with free‑text steering (for example: “focus on retrieval‑augmented LLMs on MMLU, skip survey papers”).

Under the hood this is a LangGraph **discovery subgraph**. The graph state is the canonical runtime state; the REST `SessionSnapshot` is a projection used by the API and SSE stream.

### Analysis

Once you’re happy with the approved set:

- Fetches full text from `https://arxiv.org/html/{id}` via **Firecrawl** when possible.
- Falls back to abstract + metadata when full text isn’t usable.
- For each paper, runs an LLM‑based **Paper Analyzer** that extracts:
  - core claim
  - methodology (normalized into short bullet‑like lines)
  - datasets / metrics / benchmarks
  - limitations
  - explicit citations
- Builds a deterministic **citation graph** using **Semantic Scholar**:
  - seed nodes = your approved papers
  - context nodes = high‑signal one‑hop neighbors
  - edges capture `CITES`, `CITED_BY`, `SHARED_FOUNDATION`, and `EXTENDS` relationships
- Derives a **method comparison table** from the structured analyses.

All of this runs through a LangGraph **analysis subgraph** with a shared SQLite checkpointer. The graph emits stream events for “analysis ready”, “citation graph ready”, etc., which the SSE endpoint forwards to the frontend.

### Survey (optional)

If you want a written survey:

- You can provide a **survey brief** (angle, audience, emphasis, comparisons), or let the system synthesize one from:
  - the topic + search interpretation,
  - your steering preferences,
  - the analysis and comparison table.
- The LangGraph **survey subgraph** then:
  - clusters your approved papers into themes,
  - drafts one section per cluster (Gemini‑backed section writer),
  - runs a section‑level review agent that either accepts or requests at most one more revision,
  - assembles:
    - a short introduction,
    - the themed sections,
    - the method comparison table,
    - a conclusion,
    - and a reference list with arXiv links,
      into a single **Markdown document**.
- At the final survey checkpoint you can:
  - approve the survey; or
  - send **targeted revision requests** per section (e.g. “make this section contrast baselines more explicitly”), which updates only those sections and rebuilds the final document.

Again, this is a LangGraph **survey subgraph**; targeted revisions are modeled as a queue inside graph state so only the requested sections get regenerated.

### Checkpoints and interrupts

There are four main human checkpoints:

1. **Topic interpretation** – accept or fix the inferred topic + angles.
2. **Shortlist review** – approve the final paper set, adjust approvals, or steer with a nudge.
3. **Survey brief** – provide an explicit brief or ask for an automatic one.
4. **Survey review** – approve the final survey or request targeted section revisions.

Each checkpoint:

- appears in the REST contract as a dedicated endpoint, and
- is modeled as an interrupt / waiting state in the graphs, with allowed actions listed.

---

## Tech stack

- **Backend**
  - FastAPI
  - LangGraph (discovery, analysis, survey, supervisor graphs)
  - SQLite (sessions + events + LangGraph SQLite checkpointer)
- **LLM providers**
  - GLM 4.7 Flash (OpenAI‑compatible) for most agents (search, steering, curation, analysis, survey orchestration)
  - Gemini Flash for the **section writer** agent
- **External services**
  - Semantic Scholar API – discovery + citation graph context
  - arXiv API – topic search + canonical metadata
  - Firecrawl – fetch and normalize HTML from `arxiv.org/html/*`
- **Frontend**
  - React 18
  - TypeScript
  - Vite
- **Tracing (optional)**
  - LangSmith / LangChain tracing behind an env flag

---

## Getting started

### Prerequisites

- Python **3.11+**
- [`uv`](https://github.com/astral-sh/uv) for backend dependency management
- Node **18+** and **pnpm** for the frontend
- API keys:
  - Semantic Scholar
  - Firecrawl
  - GLM (Zhipu)
  - Gemini
  - (optional) LangSmith

### Clone the repo

```bash
git clone https://github.com/garg-tejas/arxiv-scout
cd arxiv-scout
```

### Backend

```bash
cd backend

# Create a local env file
cp .env.example .env
# Fill in your API keys and any overrides

# Install dependencies into a virtualenv
uv sync

# Run the API
uv run uvicorn app.main:app --reload
```

The backend starts on `http://127.0.0.1:8000` by default.

Useful endpoints:

- `POST /sessions` – create a new session
- `GET /sessions/{id}` – fetch the current `SessionSnapshot`
- `GET /sessions/{id}/stream` – SSE stream of session events
- `POST /sessions/{id}/topic` – start topic interpretation
- `POST /sessions/{id}/analysis/start` – start analysis
- `POST /sessions/{id}/survey/start` – start survey
- `POST /sessions/{id}/survey/revise` – targeted section revisions
- `POST /sessions/{id}/survey/approve` – approve the final survey

### Frontend

```bash
cd ../frontend
pnpm install
pnpm run dev
```

By default the frontend talks to the backend on `http://127.0.0.1:8000`.

---

## Environment and configuration

Backend configuration lives in `backend/app/config.py` and is loaded via environment variables with the `ARXIV_SCOUT_` prefix.

There is a reference file at `backend/.env.example`:

```bash
cp backend/.env.example backend/.env
```

Some of the important settings:

```bash
# Core
ARXIV_SCOUT_DATABASE_PATH=backend/data/arxiv_scout.db

# External APIs
ARXIV_SCOUT_SEMANTIC_SCHOLAR_API_KEY=...
ARXIV_SCOUT_FIRECRAWL_API_KEY=...
ARXIV_SCOUT_GLM_API_KEY=...
ARXIV_SCOUT_GEMINI_API_KEY=...

# LLM behaviour
ARXIV_SCOUT_LLM_TIMEOUT_SECONDS=45.0
ARXIV_SCOUT_LLM_MAX_RETRIES=2

# Optional LangSmith tracing
ARXIV_SCOUT_LANGSMITH_TRACING=false
ARXIV_SCOUT_LANGSMITH_API_KEY=...
ARXIV_SCOUT_LANGSMITH_PROJECT=arxiv-literature-scout
```

When `ARXIV_SCOUT_LANGSMITH_TRACING=true` and `ARXIV_SCOUT_LANGSMITH_API_KEY` are set, the backend also configures the usual `LANGCHAIN_*` variables so LangGraph runs (and underlying provider calls) are sent to LangSmith.

---

## How a session flows (end‑to‑end)

1. **Create** – `POST /sessions` creates a new session with an idle snapshot.
2. **Interpret** – `POST /sessions/{id}/topic` runs the discovery graph up to the topic confirmation interrupt.
3. **Curate** – `POST /sessions/{id}/discovery/confirm` runs shortlist fetch + curation; you can then update approvals or nudge discovery.
4. **Analyze** – `POST /sessions/{id}/analysis/start` launches the analysis graph for the chosen papers.
5. **Survey** – `POST /sessions/{id}/survey/start` either:
   - asks you for a brief; or
   - synthesizes one and runs the survey graph.
6. **Revise / approve** – use `/survey/revise` and `/survey/approve` to iterate and finalize.
7. **Download** – `GET /sessions/{id}/survey.md` returns the final survey as Markdown.

Sessions live in SQLite and are kept for 7 days after the last update.

---

## Limitations

- Analysis is capped at 8 papers per run. You can approve more during discovery; you just pick which 8 to analyze at a time.
- Firecrawl can struggle on very math‑heavy PDFs. In those cases, the system falls back to abstract‑level analysis and marks that clearly in the output.
- Citation graph quality depends on Semantic Scholar coverage. Some fields and older papers have sparser edges.
- Survey quality depends on both the underlying papers and your brief. The system does not invent references, but phrasing and framing still come from the model.
- Export is Markdown‑only right now (no PDF renderer baked in).

---

## Project structure

```text
backend/
  app/          # FastAPI app, config, routes
  graph/        # LangGraph graphs (discovery, analysis, survey, supervisor, checkpointing)
  models/       # Pydantic models and enums
  integrations/ # Semantic Scholar, arXiv, Firecrawl, GLM, Gemini adapters
  persistence/  # SQLite database manager and session store
  services/     # Session, discovery, analysis, citation, survey, streaming

frontend/
  src/          # React app, API/SSE client, discovery/analysis/survey views
```
