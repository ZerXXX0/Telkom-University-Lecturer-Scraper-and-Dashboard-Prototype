-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Create tables
CREATE TABLE IF NOT EXISTS lecturers (
    id SERIAL PRIMARY KEY,
    code VARCHAR UNIQUE,
    lecturer_code VARCHAR,
    study_program VARCHAR,
    research_group VARCHAR,
    academic_rank VARCHAR,
    field VARCHAR,
    full_name VARCHAR,
    titles VARCHAR,
    name_with_title VARCHAR,
    email VARCHAR,
    photo VARCHAR,
    citation_count INTEGER DEFAULT 0,
    h_index INTEGER DEFAULT 0,
    i10_index INTEGER DEFAULT 0,
    sinta_scopus_citations INTEGER DEFAULT 0,
    sinta_scopus_h_index INTEGER DEFAULT 0,
    sinta_scopus_i10_index INTEGER DEFAULT 0,
    sinta_scholar_citations INTEGER DEFAULT 0,
    sinta_scholar_h_index INTEGER DEFAULT 0,
    sinta_scholar_i10_index INTEGER DEFAULT 0,
    sinta_wos_citations INTEGER DEFAULT 0,
    sinta_wos_h_index INTEGER DEFAULT 0,
    sinta_wos_i10_index INTEGER DEFAULT 0,
    ai_categories JSONB DEFAULT '[]'::jsonb,
    sinta_metrics JSONB DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS profiles (
    id SERIAL PRIMARY KEY,
    lecturer_id INTEGER REFERENCES lecturers(id) ON DELETE CASCADE,
    platform VARCHAR,
    url VARCHAR
);

CREATE TABLE IF NOT EXISTS publications (
    id SERIAL PRIMARY KEY,
    lecturer_id INTEGER REFERENCES lecturers(id) ON DELETE CASCADE,
    title TEXT,
    year INTEGER
);

CREATE TABLE IF NOT EXISTS keywords (
    id SERIAL PRIMARY KEY,
    lecturer_id INTEGER REFERENCES lecturers(id) ON DELETE CASCADE,
    keyword VARCHAR
);

CREATE TABLE IF NOT EXISTS research_interests (
    id SERIAL PRIMARY KEY,
    lecturer_id INTEGER REFERENCES lecturers(id) ON DELETE CASCADE,
    interest VARCHAR
);

CREATE TABLE IF NOT EXISTS coauthors (
    id SERIAL PRIMARY KEY,
    lecturer_id INTEGER REFERENCES lecturers(id) ON DELETE CASCADE,
    coauthor_name VARCHAR
);

CREATE TABLE IF NOT EXISTS embeddings (
    id SERIAL PRIMARY KEY,
    lecturer_id INTEGER UNIQUE REFERENCES lecturers(id) ON DELETE CASCADE,
    keyword_embedding vector(384),
    publication_embedding vector(384)
);

CREATE TABLE IF NOT EXISTS recommendations (
    id SERIAL PRIMARY KEY,
    lecturer_id INTEGER REFERENCES lecturers(id) ON DELETE CASCADE,
    recommended_lecturer_id INTEGER REFERENCES lecturers(id) ON DELETE CASCADE,
    score FLOAT,
    reasons JSONB
);

CREATE TABLE IF NOT EXISTS collaborations (
    id SERIAL PRIMARY KEY,
    lecturer_id_1 INTEGER REFERENCES lecturers(id) ON DELETE CASCADE,
    lecturer_id_2 INTEGER REFERENCES lecturers(id) ON DELETE CASCADE,
    collaboration_count INTEGER DEFAULT 1,
    shared_publications JSONB
);

-- Indexes for performance optimization
CREATE INDEX IF NOT EXISTS idx_profiles_lecturer_id ON profiles(lecturer_id);
CREATE INDEX IF NOT EXISTS idx_publications_lecturer_id ON publications(lecturer_id);
CREATE INDEX IF NOT EXISTS idx_keywords_lecturer_id ON keywords(lecturer_id);
CREATE INDEX IF NOT EXISTS idx_research_interests_lecturer_id ON research_interests(lecturer_id);
CREATE INDEX IF NOT EXISTS idx_coauthors_lecturer_id ON coauthors(lecturer_id);
CREATE INDEX IF NOT EXISTS idx_recommendations_lecturer_id ON recommendations(lecturer_id);
CREATE INDEX IF NOT EXISTS idx_recommendations_recommended_lecturer_id ON recommendations(recommended_lecturer_id);
CREATE INDEX IF NOT EXISTS idx_collaborations_lecturer_id_1 ON collaborations(lecturer_id_1);
CREATE INDEX IF NOT EXISTS idx_collaborations_lecturer_id_2 ON collaborations(lecturer_id_2);
