-- ---------------------------------------------------------------------------
-- V1 — Base schema for the movie search platform.
--
-- One table holds both the structured metadata and the embedding vector. A
-- single table keeps hybrid search (metadata filter + vector distance) inside
-- one index scan and one plan. A separate vector table would force a join on
-- every search and give the planner no way to push the filters down.
-- ---------------------------------------------------------------------------

-- pgvector supplies the `vector` type and the distance operators.
CREATE EXTENSION IF NOT EXISTS vector;

-- pg_trgm supplies trigram similarity. `get_movie_by_title` uses it for the
-- fuzzy title match, so no fuzzy-match library is needed in the application.
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS movies (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Natural key. The pipeline derives it from the normalized title and the
    -- release date. It makes the load idempotent: a second run updates the
    -- same row instead of inserting a duplicate.
    source_key          TEXT        NOT NULL UNIQUE,

    -- --- Dataset fields, cleaned and normalized ---------------------------
    title               TEXT        NOT NULL,
    release_date        DATE,
    release_year        INTEGER,
    major_genre         TEXT,
    creative_type       TEXT,
    source              TEXT,
    mpaa_rating         TEXT,
    director            TEXT,
    distributor         TEXT,
    running_time_min    INTEGER,
    production_budget   BIGINT,
    us_gross            BIGINT,
    worldwide_gross     BIGINT,
    us_dvd_sales        BIGINT,
    imdb_rating         NUMERIC(3,1),
    imdb_votes          INTEGER,
    rt_rating           INTEGER,

    -- --- Derived features (Part 1.3) --------------------------------------
    decade              INTEGER,
    budget_tier         TEXT,
    rating_score_delta  NUMERIC(4,1),
    blockbuster_flag    BOOLEAN,
    profit_ratio        NUMERIC(10,3),

    -- --- Provenance --------------------------------------------------------
    -- Names of the columns whose value came from imputation, not from the
    -- source record. A consumer can exclude imputed values from analytics.
    imputed_fields      TEXT[]      NOT NULL DEFAULT '{}',

    -- --- Embedding ---------------------------------------------------------
    augmented_text      TEXT        NOT NULL,
    -- SHA-256 over every persisted column except the audit columns. The upsert
    -- writes a row only when this value differs, so a repeat run of an unchanged
    -- dataset leaves `updated_at` alone.
    --
    -- Re-embedding is decided separately, by comparing `augmented_text` and
    -- `embedding_model` against what is already stored. The two questions are
    -- not the same: a change to `us_gross` changes the hash but not the text,
    -- so the row is rewritten and the vector is kept.
    content_hash        TEXT        NOT NULL,
    embedding           vector(768),
    embedding_model     TEXT,

    -- --- Audit columns ------------------------------------------------------
    pipeline_version    TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- --- Domain constraints --------------------------------------------------
    -- The pipeline already rejects out-of-range values. These constraints stop
    -- a bad value that arrives by any other path.
    CONSTRAINT movies_imdb_rating_range   CHECK (imdb_rating IS NULL OR (imdb_rating >= 0 AND imdb_rating <= 10)),
    CONSTRAINT movies_rt_rating_range     CHECK (rt_rating IS NULL OR (rt_rating >= 0 AND rt_rating <= 100)),
    CONSTRAINT movies_runtime_positive    CHECK (running_time_min IS NULL OR running_time_min > 0),
    CONSTRAINT movies_budget_nonnegative  CHECK (production_budget IS NULL OR production_budget >= 0),
    CONSTRAINT movies_votes_nonnegative   CHECK (imdb_votes IS NULL OR imdb_votes >= 0),
    CONSTRAINT movies_year_range          CHECK (release_year IS NULL OR (release_year >= 1900 AND release_year <= 2100))
);

COMMENT ON TABLE  movies IS 'Cleaned movie metadata plus the embedding of its augmented text representation.';
COMMENT ON COLUMN movies.source_key IS 'Idempotency key derived from the normalized title and the release date.';
COMMENT ON COLUMN movies.content_hash IS 'SHA-256 over every persisted column except the audit columns. Controls whether a pipeline run rewrites the row.';
COMMENT ON COLUMN movies.imputed_fields IS 'Columns whose value was imputed rather than read from the source dataset.';
