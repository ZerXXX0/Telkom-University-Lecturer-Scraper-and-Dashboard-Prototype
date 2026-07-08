# 🎓 Lecturer Profiling & AI Collaboration System (FIF Telkom University)

This repository contains the complete research profiling, collaborator recommendation, and network visualization platform built for the Faculty of Informatics (FIF) at Telkom University. The project focuses on mapping research expertise, SINTA metrics, and co-authorship networks to support AI-driven collaboration.

---

## 🚀 Tech Stack

*   **Frontend Dashboard:** Streamlit, Plotly, NetworkX (force-directed graphs).
*   **Database:** PostgreSQL / Supabase, utilizing the `pgvector` extension for semantic search and recommendations.
*   **Pipeline Scraper:** Async Playwright crawlers, Beautiful Soup, and OpenAlex REST API wrapper.
*   **AI Parser:** Google Gemini API (via `google-generativeai`) for zero-shot JSON metadata parsing.
*   **AI Embedding Model:** Sentence-Transformers (`all-MiniLM-L6-v2`) generating 384-dimensional dense vectors.

---

## 📂 Project Structure

```
├── config.py              # Environment and project settings configuration
├── dashboard.py           # Streamlit dashboard application (fully database-driven)
├── save_to_db.py          # Data migration script to parse JSON files and sync to DB
├── schema.sql             # SQL schema containing table DDL definitions and indexes
├── database/
│   ├── models.py          # SQLAlchemy ORM models
│   └── postgres.py        # Database engine setup and pgvector initialization
├── embedding/             # Model loading and vector representation generation
├── scraper/               # Playwright, SINTA, and OpenAlex scrapers
├── parser/                # Gemini LLM JSON parsers
└── database_details.md    # In-depth database ERD, spec tables, and optimizations
```

---

## 🛠️ Setup Instructions

### 1. Environment Setup
Clone the repository and install the Python dependencies:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: .\venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env` and fill in your details:
```env
GEMINI_API_KEY=your_gemini_api_key
DATABASE_URL=postgresql://user:password@host:port/database_name
OPENALEX_EMAIL=your_email@student.telkomuniversity.ac.id
```
*(Note: If your database password contains special characters like `!`, make sure to percent-encode them in the `DATABASE_URL` connection string, e.g., `!` becomes `%21`)*

### 3. Initialize the Database
Run this helper command to enable the `vector` extension and create all database tables:
```bash
python -c "from database.postgres import init_db; init_db()"
```

### 4. Sync Raw Data to Database
Upload all processed profiles (JSON output datasets) and compute co-authorship collaborations:
```bash
python save_to_db.py
```
This script wipes the database in strict relational dependency order and performs a clean import, establishing:
*   161 lecturer profiles.
*   10,226 publication titles with corrected publication years.
*   1,030 precalculated co-authorships.

---

## 📊 Running the Dashboard

Launch the Streamlit web dashboard locally:
```bash
streamlit run dashboard.py
```
The app will open automatically at `http://localhost:8501`.

### Dashboard Features:
1.  **👤 Lecturer Profiles Tab:** Displays researcher demographics, photo, direct links to Scopus/SINTA/Google Scholar, a full SINTA citation table, research tags, and the **top 10 recommended collaborators** with matching similarity scores and explanations.
    *   *Scopus Link Editor:* Allows you to update or fix Scopus profiles on the fly directly to the database.
2.  **📊 FIF Research Statistics Tab:** Interactive Plotly summaries displaying total lecturers, publication trends over time (1970–Present), study program counts, research group distributions, and AI specialization pie charts.
3.  **🤝 Collaboration Network Tab:** 
    *   *Network Clusters Graph:* An interactive force-directed NetworkX graph mapping links between lecturers. Nodes are color-coded by their research group (**CITI (Red)**, **DSIS (Green)**, and **SEAL (Blue)**) showing clear scientific clusters. Sized by degree of connection.
    *   *Search Filter:* Instantly look up co-authorships and expand cards to see the exact shared publication titles.

---

## 📚 Database Documentation
For details on the entity relational diagram (ERD), table specifications, performance indexes, and cleanup order, see [database_details.md](./database_details.md).
