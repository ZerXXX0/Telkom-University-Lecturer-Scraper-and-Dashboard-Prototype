# 🎓 Lecturer Profiling & AI Collaboration System
## Faculty of Informatics (FIF) — Telkom University

> **Project Description & Technical Reference Document**
> Generated: July 2026 | Status: Production Ready (Data Pipeline), Active Development (Laravel Dashboard)

---

## 📌 1. Project Overview

This project delivers an end-to-end system for **mapping research expertise, tracking publication history, and recommending AI collaboration opportunities** for all lecturers in the Faculty of Informatics (FIF) at Telkom University.

The system was built as an undergraduate internship (Kerja Praktik / KP) project by Kelompok 1, under the title:

> **"Dashboard Visualisasi Topik Riset dan Peta Keahlian Dosen untuk Mendukung Kolaborasi AI di FIF"**

The primary stakeholder is the **FIF AI Task Force (Satgas AI)**, which needs a reliable tool to:
- Understand the distribution of AI sub-fields covered by the faculty.
- Discover which lecturers publish frequently in related domains and could collaborate.
- Visualize the current co-authorship network as a live graph.
- Access standardized profiles with metrics from Scopus, Google Scholar, and Web of Science.

---

## 👥 2. Team

| Name | NIM | Role |
| :--- | :--- | :--- |
| Syahdan Rizqi Ruhendy | 103012330308 | Developer 1 — Frontend & UI/UX |
| Muhammad Ghozy Abdurrahman | 103012330264 | Developer 2 — Backend & Data Integration |
| Muhammad Karov Ardava Barus | 103052300001 | Developer 3 — Data Visualization & Query Logic |

---

## 🏗️ 3. System Architecture

The project spans **two repositories** with distinct responsibilities:

### Repository 1: Data Pipeline (This Repo)
**`Telkom-University-Lecturer-Scraper-and-Dashboard-Prototype`**

Handles all data engineering work: scraping, parsing, embedding, recommendation pre-computation, database migration, and the Streamlit prototype dashboard.

### Repository 2: Presentation Dashboard
**`keluarga-kp`** (`Ardavaa/keluarga-kp`)

A Laravel 13 + Blade + Tailwind CSS web application that reads from the same PostgreSQL database and serves as the final deliverable, with Telkom University's visual identity applied.

### High-Level Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                        DATA SOURCES                                 │
│  ┌────────────────────┐  ┌──────────────┐  ┌─────────────────────┐ │
│  │ Keilmuan Dosen     │  │  OpenAlex    │  │ SINTA / GScholar /  │ │
│  │ FIF.xlsx (Input)   │  │  REST API    │  │ ORCID / Scopus      │ │
│  └────────┬───────────┘  └──────┬───────┘  └──────────┬──────────┘ │
└───────────┼──────────────────────┼────────────────────┼─────────────┘
            │                      │                    │
            ▼                      ▼                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     PYTHON DATA PIPELINE                            │
│  main.py ──► Playwright / httpx Scraper ──► Gemini LLM Parser      │
│         ──► all-MiniLM-L6-v2 Embedder ──► Cosine Similarity Engine │
│                                                                     │
│  fetch_sinta_metrics.py  (async SINTA metrics fetch)                │
│  save_to_db.py           (JSON → PostgreSQL migration)              │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
                  ┌──────────────────────────┐
                  │  PostgreSQL + pgvector   │
                  │  (Self-hosted, shared)   │
                  └──────────┬───────────────┘
                             │
             ┌───────────────┼───────────────────┐
             ▼                                   ▼
  ┌─────────────────────┐            ┌────────────────────────┐
  │  Streamlit Prototype │            │  Laravel Dashboard     │
  │  dashboard.py        │            │  keluarga-kp (Final)   │
  └─────────────────────┘            └────────────────────────┘
```

---

## ⚙️ 4. Tech Stack

### Data Pipeline

| Component | Technology |
| :--- | :--- |
| Language | Python 3.10+ |
| Web Scraping | Playwright (async Chromium), httpx, BeautifulSoup |
| Academic APIs | OpenAlex REST API, SINTA web crawl |
| AI Extraction | Google Gemini API (`google-generativeai`) — zero-shot JSON parsing |
| Embedding Model | `sentence-transformers/all-MiniLM-L6-v2` — 384-dim dense vectors |
| Database ORM | SQLAlchemy 2.x |
| Database | PostgreSQL + `pgvector` extension |
| Prototype Dashboard | Streamlit, Plotly, NetworkX |
| Validation | Pydantic |
| Task Concurrency | asyncio + `asyncio.Semaphore` |

### Production Dashboard (Laravel)

| Component | Technology |
| :--- | :--- |
| Backend Framework | Laravel 13.x (PHP 8.3+) |
| Database Driver | `pgsql` native Laravel (same PostgreSQL instance) |
| Templating | Blade + Alpine.js |
| Styling | Tailwind CSS v4 (custom `telu-red: #9F1521` theme) |
| Charting | Chart.js |
| Network Graph | vis-network |
| Export | maatwebsite/excel + barryvdh/laravel-dompdf |
| Asset Bundling | Vite (default Laravel 13) |

---

## 🔄 5. Data Pipeline Workflow

### Stage 1: Input Loading
`main.py` reads `data/input/Keilmuan Dosen FIF.xlsx` — an official spreadsheet containing:
- Lecturer name (`NAMA`) and NIP (`NIP`)
- Study program (`PROGRAM STUDI`) and academic rank (`JAD TERAKHIR`)
- Scientific field (`PLOTTING KEILMUAN`)

Research groups (CITI, DSIS, SEAL) are auto-classified from field/study program keywords during this stage.

### Stage 2: Web Scraping (Multi-Source)
For each lecturer, the pipeline:
1. Queries the **OpenAlex API** by name to fetch publications list, co-authors, and ORCID.
2. Runs a web search to discover SINTA, Google Scholar, Scopus, and institutional pages.
3. Uses **Playwright** to download raw HTML from the discovered URLs.

### Stage 3: LLM Extraction
Cleaned HTML text is sent to the **Gemini API** which extracts:
- Full name, titles, email
- Profile links (Google Scholar, SINTA, ORCID, Scopus)
- Photo URL
- Research keywords and interests

Results from multiple sources are merged with `parser/merge.py`, preferring OpenAlex for publications and web scraping for identity details.

### Stage 4: Embedding & AI Categorization
Using `sentence-transformers/all-MiniLM-L6-v2`:
- Keywords and publication titles are concatenated and encoded into 384-dimensional float vectors.
- AI specialization categories are programmatically labeled (e.g., Computer Vision, NLP, IoT).

### Stage 5: Recommendation Pre-computation
For each lecturer, `recommendation/recommender.py` computes cosine similarity between the lecturer's combined embedding vector and every other faculty member's vector, then:
- Ranks all candidates by similarity score.
- Calls Gemini to generate natural language reasons for the top N recommendations.
- Stores results as `recommendations: [{recommended_lecturer_id, score, reasons}]`.

### Stage 6: JSON Caching
All processed profiles are saved to `data/json/{NIP}.json`. This allows **resume-on-interrupt** — already processed lecturers are skipped on re-run.

### Stage 7: SINTA Metrics Fetch
`fetch_sinta_metrics.py` separately crawls SINTA's `?view=metrics` endpoint per lecturer to capture detailed yearly citation/publication counts across Scopus, Google Scholar, and Web of Science. Results are merged back into the JSON files.

### Stage 8: Database Migration
`save_to_db.py` reads all JSON files and populates PostgreSQL in the following strict relational order to avoid FK constraint violations:

```
Wipe: recommendations → collaborations → embeddings → profiles
    → publications → keywords → research_interests → coauthors → lecturers

Populate: lecturers → profiles → publications → keywords
        → research_interests → coauthors → embeddings
        → collaborations (computed) → recommendations
```

This produces:
- **~161** lecturer profiles
- **~10,226** publication titles with corrected publication years
- **~1,030** pre-calculated co-authorship pairs
- **384-dim embeddings** per lecturer for semantic search

---

## 🗄️ 6. Database Schema

Full schema defined in `schema.sql`. Complete table specs in [`database_details.md`](./database_details.md).

### Entity-Relationship Overview

```
LECTURERS ──has──► PROFILES (Google Scholar, SINTA, ORCID, Scopus URLs)
          ──publishes──► PUBLICATIONS (title, year)
          ──tagged──► KEYWORDS
          ──focuses──► RESEARCH_INTERESTS
          ──coauthors──► COAUTHORS (external/internal names)
          ──possesses──► EMBEDDINGS (keyword_vec 384-dim, publication_vec 384-dim)
          ──receives──► RECOMMENDATIONS (score, reasons JSONB)
          ──collaborates──► COLLABORATIONS (count, shared_publications JSONB)
```

### Key Columns in `lecturers`

| Column | Description |
| :--- | :--- |
| `name` | Base name (searchable, no titles) |
| `full_name` | Full clean name without prefix/suffix |
| `name_with_title` | Formatted official name with degrees |
| `code` | NIP — unique identifier (UNIQUE constraint) |
| `lecturer_code` | Three-letter initials |
| `study_program` | e.g., "S1 Informatika", "S1 Data Science" |
| `research_group` | `CITI`, `DSIS`, or `SEAL` |
| `academic_rank` | e.g., `LEKTOR KEPALA`, `ASISTEN AHLI` |
| `field` | Broad scientific expertise area |
| `ai_categories` | JSONB array of AI subfields |
| `sinta_metrics` | JSONB dict: `{scopus: {citation, h_index, ...}, google_scholar: {...}, wos: {...}}` |

---

## 📂 7. Repository File Map

```
project/
├── .env                         # Secret credentials (not committed)
├── .env.example                 # Template for env variables
├── .github/                     # GitHub Actions CI/CD workflows
├── config.py                    # Settings: directories, API keys
│
├── main.py                      # 🚀 Pipeline entrypoint
├── save_to_db.py                # 💾 JSON → PostgreSQL migrator
├── fetch_sinta_metrics.py       # 📊 SINTA metrics async crawler
├── incremental_update.py        # ♻️  Delta update script (bypass full rescrape)
├── update_missing_data.py       # 🔧 Fill in missing fields for existing profiles
├── update_from_soc.py           # 🔧 Sync from SoC official source
├── resolve_openalex_scopus.py   # 🔗 Link OpenAlex IDs to Scopus profiles
├── resolve_orcid_scopus.py      # 🔗 ORCID → Scopus resolver
├── scrape_titles.py             # 📄 Standalone title scraper
├── merge_scopus_from_kp_project.py  # 🔀 Merge Scopus data from parallel project
├── wipe_data.py                 # 🗑️  Clean all processed JSON data
│
├── schema.sql                   # DDL: table definitions + indexes
├── database_dump.sql            # Full PostgreSQL dump (backup)
├── database_details.md          # ERD, table specs, optimization notes
│
├── dashboard.py                 # 📊 Streamlit prototype dashboard
├── validator.py                 # Pydantic profile schema validator
├── inspect_columns_dashboard.py # Debug inspector utility
│
├── database/
│   ├── models.py                # SQLAlchemy ORM models
│   └── postgres.py              # DB engine + pgvector init
│
├── scraper/
│   ├── search.py                # Web search for profile discovery
│   ├── playwright_client.py     # Async Playwright page downloader
│   ├── cleaner.py               # HTML stripping and cleanup
│   └── openalex.py              # OpenAlex API wrapper
│
├── parser/
│   ├── llm.py                   # Gemini API prompt + JSON parsing
│   └── merge.py                 # Multi-source profile merge + AI categorizer
│
├── embedding/
│   └── embedder.py              # Sentence-Transformers model + encode()
│
├── recommendation/
│   └── recommender.py           # Cosine similarity + ranked recommendations
│
├── utils/
│   └── logger.py                # Centralized Python logger setup
│
└── data/
    ├── input/                   # Source spreadsheets (Keilmuan Dosen FIF.xlsx)
    └── json/                    # Cached JSON profiles per lecturer ({NIP}.json)
```

---

## 📊 8. Prototype Dashboard Features (Streamlit)

The Streamlit prototype (`dashboard.py`) provides four tabs:

### Tab 1 — 👤 Lecturer Profiles
- Sidebar search and selection by name, NIP, study program, or research group.
- Displays photo, academic identity, email, direct links to SINTA / Google Scholar / ORCID / Scopus.
- SINTA citation metrics table (Scopus, Google Scholar, Web of Science: Article, Citation, H-Index, i10-Index, G-Index).
- Research keywords and publications list (latest first).
- **Top 10 Recommended Collaborators** with similarity scores and Gemini-generated match reasoning.
- Inline **Scopus Link Editor** for correcting or adding missing Scopus Author IDs.

### Tab 2 — 📊 FIF Research Statistics
- KPI cards: total lecturers, publications, collaboration pairs.
- Bar chart: publication trend by year (1970–Present).
- Pie chart: AI specialization domain distribution (NLP, Computer Vision, IoT, etc.).
- Horizontal bar chart: lecturer count by study program.
- Bar chart: research group distribution (CITI, DSIS, SEAL).

### Tab 3 — 🤝 Collaboration Network
- **Network Clusters Graph:** Interactive force-directed graph (NetworkX + Plotly). Nodes colored by research group: 🔴 CITI, 🔵 SEAL, 🟢 DSIS. Node size proportional to collaboration degree.
- Threshold slider to filter edges by minimum shared publication count.
- Network statistics: total nodes/edges in view, top 3 collaboration hubs.
- **Co-Authorship Directory:** Searchable list showing all pairs with expandable shared publication titles.

### Tab 4 — 🔍 Database Inspector
- Raw column value inspector for the selected lecturer (diagnostic/debugging view).

---

## 🖥️ 9. Production Dashboard Features (Laravel — `keluarga-kp`)

| Page | Function | Data Source |
| :--- | :--- | :--- |
| **Dashboard Utama** | KPI summary: lecturers, publications, collaborations | `lecturers`, `publications`, `collaborations` |
| **Topik Dominan** | Most frequent AI research topics (Chart.js doughnuts/bars) | `lecturers.ai_categories`, `keywords`, `research_interests` |
| **Peta Keahlian Dosen** | Expertise map grouped by KK / research group / study program | `lecturers.research_group`, `field`, `study_program` |
| **Profil Dosen** | Full profile: metrics, publications, links, keywords | `lecturers`, `profiles`, `publications`, `keywords` |
| **Kolaborasi** | vis-network force-directed graph + co-authorship list | `collaborations`, `coauthors` |
| **Rekomendasi Kolaborasi** | Recommended pairs with similarity score + match reasons | `recommendations` |

**Cross-cutting features:**
- Global filters: `study_program`, `field`/`ai_category`, `publication_year`, `research_group`.
- Export to Excel (`maatwebsite/excel`) and PDF (`barryvdh/laravel-dompdf`).
- Telkom University visual identity: brand red `#9F1521`, Inter font, clean flat card design.
- Left sidebar navigation (static desktop / slide-out mobile drawer).

---

## 🔐 10. Environment Variables

| Variable | Description |
| :--- | :--- |
| `GEMINI_API_KEY` | Google Gemini API key (from Google AI Studio) |
| `DATABASE_URL` | PostgreSQL connection string, e.g. `postgresql://user:pass@host:5432/db` |
| `OPENALEX_EMAIL` | Registered email for OpenAlex polite pool (higher rate limit) |

> ⚠️ **Never commit `.env` to the repository.** Use `.env.example` as the template.

---

## 🚀 11. Quick Start

```bash
# 1. Clone & setup environment
git clone https://github.com/<your-org>/Telkom-University-Lecturer-Scraper-and-Dashboard-Prototype.git
cd Telkom-University-Lecturer-Scraper-and-Dashboard-Prototype

python -m venv venv
source venv/bin/activate          # Windows: .\venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium

# 2. Configure credentials
cp .env.example .env
# Fill in GEMINI_API_KEY, DATABASE_URL, OPENALEX_EMAIL

# 3. Initialize database schema
python -c "from database.postgres import init_db; init_db()"

# 4. Run the full data pipeline
python main.py

# 5. Fetch detailed SINTA metrics
python fetch_sinta_metrics.py

# 6. Migrate cached data to PostgreSQL
python save_to_db.py

# 7. Launch the prototype dashboard
streamlit run dashboard.py
# Opens at http://localhost:8501
```

---

## 📋 12. Data Integrity & Performance

- **B-Tree Indexes** on all `lecturer_id` foreign keys across child tables to ensure fast dashboard rendering and filtering.
- **pgvector IVFFLAT index** on the `embeddings` table for approximate nearest-neighbor vector search.
- All child tables use **ON DELETE CASCADE**, ensuring referential integrity when a lecturer is wiped and re-imported.
- Wipe and repopulate order in `save_to_db.py` guarantees no FK violations during full re-sync.
- The `incremental_update.py` script supports delta-only updates — skipping already-processed lecturers to avoid redundant API calls and scraping.
- GitHub Actions is configured in `.github/` to automate incremental pipeline runs on a cron schedule.

---

## 🔗 13. References

- `database_details.md` — Full ERD, table specifications, and performance index documentation.
- `schema.sql` — Authoritative SQL DDL for all tables and indexes.
- `docs/PRD.md` (keluarga-kp) — Product Requirements Document covering the Laravel dashboard features, design tokens, and milestone roadmap.
- `ROLE_DIVISION.md` (keluarga-kp) — Detailed responsibility matrix for the three developers.
- `Keilmuan Dosen FIF.xlsx` — Official FIF spreadsheet mapping lecturers to research groups and expertise fields.
