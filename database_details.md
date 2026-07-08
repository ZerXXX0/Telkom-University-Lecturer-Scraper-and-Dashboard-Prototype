# PostgreSQL Database Schema & Documentation
This document outlines the database schema, table structures, relationship mapping, and indexes of the **Lecturer Profiling and Collaboration System** for the Faculty of Informatics (FIF), Telkom University.

---

## 1. Relational Entity-Relationship Diagram (ERD)

```mermaid
erDiagram
    LECTURERS ||--o{ PROFILES : "has"
    LECTURERS ||--o{ PUBLICATIONS : "publishes"
    LECTURERS ||--o{ KEYWORDS : "associated_with"
    LECTURERS ||--o{ RESEARCH_INTERESTS : "focuses_on"
    LECTURERS ||--o{ COAUTHORS : "coauthors_with"
    LECTURERS ||--o| EMBEDDINGS : "possesses"
    LECTURERS ||--o{ RECOMMENDATIONS : "receives"
    LECTURERS ||--o{ COLLABORATIONS : "collaborates_in"

    LECTURERS {
        int id PK
        string name
        string code UK "NIP / Unique ID"
        string lecturer_code "Short Code"
        string study_program
        string research_group
        string academic_rank
        string field
        string full_name
        string titles
        string name_with_title
        string email
        string photo
        int citation_count
        int h_index
        int i10_index
        int sinta_scopus_citations
        int sinta_scopus_h_index
        int sinta_scopus_i10_index
        int sinta_scholar_citations
        int sinta_scholar_h_index
        int sinta_scholar_i10_index
        int sinta_wos_citations
        int sinta_wos_h_index
        int sinta_wos_i10_index
        jsonb ai_categories
        jsonb sinta_metrics
    }

    PROFILES {
        int id PK
        int lecturer_id FK
        string platform "google_scholar | sinta | orcid | scopus"
        string url
    }

    PUBLICATIONS {
        int id PK
        int lecturer_id FK
        text title
        int year
    }

    KEYWORDS {
        int id PK
        int lecturer_id FK
        string keyword
    }

    RESEARCH_INTERESTS {
        int id PK
        int lecturer_id FK
        string interest
    }

    COAUTHORS {
        int id PK
        int lecturer_id FK
        string coauthor_name
    }

    EMBEDDINGS {
        int id PK
        int lecturer_id FK "Unique"
        vector keyword_embedding "384-dim pgvector"
        vector publication_embedding "384-dim pgvector"
    }

    RECOMMENDATIONS {
        int id PK
        int lecturer_id FK
        int recommended_lecturer_id FK
        float score
        jsonb reasons
    }

    COLLABORATIONS {
        int id PK
        int lecturer_id_1 FK
        int lecturer_id_2 FK
        int collaboration_count
        jsonb shared_publications
    }
```

---

## 2. Table Specifications

### 2.1 `lecturers`
Stores primary profile details, SINTA metrics, and parsed research classifications.
*   **Primary Key:** `id` (Serial)
*   **Constraints:** `code` is UNIQUE.

| Column | Type | Default / Null | Description |
| :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | `SERIAL PRIMARY KEY` | Internal database auto-increment identifier |
| `name` | `VARCHAR` | `NULL` | Base name |
| `code` | `VARCHAR` | `UNIQUE` | Unique identifier (usually NIP) |
| `lecturer_code` | `VARCHAR` | `NULL` | Three-letter initials / academic code |
| `study_program` | `VARCHAR` | `NULL` | Faculty study program |
| `research_group` | `VARCHAR` | `NULL` | Assigned research group (CITI, DSIS, SEAL) |
| `academic_rank` | `VARCHAR` | `NULL` | Academic position rank (LEKTOR, etc.) |
| `field` | `VARCHAR` | `NULL` | Broad scientific area of expertise |
| `full_name` | `VARCHAR` | `NULL` | Full name without prefix titles |
| `titles` | `VARCHAR` | `NULL` | List of degree qualifications |
| `name_with_title` | `VARCHAR` | `NULL` | Formatted official name |
| `email` | `VARCHAR` | `NULL` | Academic email address |
| `photo` | `VARCHAR` | `NULL` | Path / URL to profile picture |
| `citation_count` | `INTEGER` | `0` | Overall cumulative citation count |
| `h_index` | `INTEGER` | `0` | Cumulative h-index |
| `i10_index` | `INTEGER` | `0` | Cumulative i10-index |
| `sinta_scopus_citations` | `INTEGER` | `0` | Scopus citations (from SINTA) |
| `sinta_scopus_h_index`| `INTEGER` | `0` | Scopus h-index |
| `sinta_scholar_citations`| `INTEGER` | `0` | Scholar citations |
| `sinta_wos_citations` | `INTEGER` | `0` | Web of Science citations |
| `ai_categories` | `JSONB` | `'[]'::jsonb` | Extracted AI subfields |
| `sinta_metrics` | `JSONB` | `'{}'::jsonb` | Granular yearly metrics |

---

### 2.2 `profiles`
Stores external URLs pointing to Google Scholar, SINTA, ORCID, and Scopus.
*   **Foreign Key:** `lecturer_id` referencing `lecturers.id` (ON DELETE CASCADE)

| Column | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | `SERIAL PRIMARY KEY` | Auto-increment key |
| `lecturer_id` | `INTEGER` | `FOREIGN KEY` | Link to lecturer profile |
| `platform` | `VARCHAR` | `NULL` | E.g., `google_scholar`, `sinta`, `orcid`, `scopus` |
| `url` | `VARCHAR` | `NULL` | Web URL string |

---

### 2.3 `publications`
Stores individual academic papers published by lecturers.
*   **Foreign Key:** `lecturer_id` referencing `lecturers.id` (ON DELETE CASCADE)

| Column | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | `SERIAL PRIMARY KEY` | Auto-increment key |
| `lecturer_id` | `INTEGER` | `FOREIGN KEY` | Link to authoring lecturer |
| `title` | `TEXT` | `NULL` | Complete title of publication |
| `year` | `INTEGER` | `NULL` | Publication year |

---

### 2.4 `keywords` & `research_interests`
Hold scientific tags extracted from profiles/papers.
*   **Foreign Key:** `lecturer_id` referencing `lecturers.id` (ON DELETE CASCADE)

| Column | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | `SERIAL PRIMARY KEY` | Auto-increment key |
| `lecturer_id` | `INTEGER` | `FOREIGN KEY` | Link to lecturer |
| `keyword` / `interest`| `VARCHAR` | `NULL` | Extracted keyword or interest tag |

---

### 2.5 `coauthors`
Extracted list of co-authors parsed from publication metadata.
*   **Foreign Key:** `lecturer_id` referencing `lecturers.id` (ON DELETE CASCADE)

| Column | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | `SERIAL PRIMARY KEY` | Auto-increment key |
| `lecturer_id` | `INTEGER` | `FOREIGN KEY` | Link to main lecturer |
| `coauthor_name` | `VARCHAR` | `NULL` | Co-author's name string |

---

### 2.6 `embeddings`
Stores vector embeddings generated from research profiles. Used to compute semantic similarities.
*   **Requirement:** Relies on the `pgvector` PostgreSQL extension.
*   **Foreign Key:** `lecturer_id` referencing `lecturers.id` (ON DELETE CASCADE, UNIQUE)

| Column | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | `SERIAL PRIMARY KEY` | Auto-increment key |
| `lecturer_id` | `INTEGER` | `FOREIGN KEY, UNIQUE`| Link to lecturer profile |
| `keyword_embedding` | `vector(384)` | `NULL` | 384-dimensional dense vector of keywords |
| `publication_embedding`| `vector(384)` | `NULL` | 384-dimensional dense vector of publications |

---

### 2.7 `recommendations`
Stores precomputed collaboration recommendation pairs.
*   **Foreign Keys:** Both `lecturer_id` and `recommended_lecturer_id` reference `lecturers.id` (ON DELETE CASCADE).

| Column | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | `SERIAL PRIMARY KEY` | Auto-increment key |
| `lecturer_id` | `INTEGER` | `FOREIGN KEY` | Link to querying lecturer |
| `recommended_lecturer_id`| `INTEGER`| `FOREIGN KEY` | Link to recommended lecturer |
| `score` | `FLOAT` | `NULL` | Similarity match score |
| `reasons` | `JSONB` | `NULL` | Bulleted list of reasons for recommendation |

---

### 2.8 `collaborations`
Stores direct co-authorship relationships between faculty members.
*   **Foreign Keys:** Both `lecturer_id_1` and `lecturer_id_2` reference `lecturers.id` (ON DELETE CASCADE).

| Column | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | `SERIAL PRIMARY KEY` | Auto-increment key |
| `lecturer_id_1` | `INTEGER` | `FOREIGN KEY` | First collaborating lecturer ID |
| `lecturer_id_2` | `INTEGER` | `FOREIGN KEY` | Second collaborating lecturer ID (guaranteed `id_1 < id_2`) |
| `collaboration_count` | `INTEGER` | `DEFAULT 1` | Total count of co-authored papers |
| `shared_publications` | `JSONB` | `NULL` | Array of co-authored paper titles |

---

## 3. Relational Cleanup & Population Order
To prevent foreign key violations, the sync script (`save_to_db.py`) drops and populates tables in the following strict order:

```mermaid
graph TD
    A[Wipe recommendations] --> B[Wipe collaborations]
    B --> C[Wipe embeddings]
    C --> D[Wipe profiles]
    D --> E[Wipe publications]
    E --> F[Wipe keywords]
    F --> G[Wipe research_interests]
    G --> H[Wipe coauthors]
    H --> I[Wipe lecturers]
```

---

## 4. Query Performance Optimization (Indexes)
Standard B-Tree indexes are defined to maximize search performance for filtering and dashboard rendering:
*   `idx_profiles_lecturer_id` on `profiles(lecturer_id)`
*   `idx_publications_lecturer_id` on `publications(lecturer_id)`
*   `idx_keywords_lecturer_id` on `keywords(lecturer_id)`
*   `idx_research_interests_lecturer_id` on `research_interests(lecturer_id)`
*   `idx_coauthors_lecturer_id` on `coauthors(lecturer_id)`
*   `idx_recommendations_lecturer_id` on `recommendations(lecturer_id)`
*   `idx_collaborations_lecturer_id_1` on `collaborations(lecturer_id_1)`
*   `idx_collaborations_lecturer_id_2` on `collaborations(lecturer_id_2)`
