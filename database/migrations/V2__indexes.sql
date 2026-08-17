-- ---------------------------------------------------------------------------
-- V2 — Indexes.
--
-- The search path is: filter on metadata, then order by vector distance. The
-- HNSW index answers the ordering. The btree indexes answer the filters and
-- let the planner discard rows before it reads the vectors.
-- ---------------------------------------------------------------------------

-- Vector index. HNSW, not IVFFlat, because HNSW needs no training step and
-- keeps its recall when the pipeline adds rows later. Cosine distance matches
-- the model: BAAI/bge-base-en-v1.5 returns L2-normalized vectors.
--
-- m = 16 and ef_construction = 64 are the pgvector defaults. They are correct
-- for a table of a few thousand rows. The query side raises hnsw.ef_search when
-- a metadata filter is present, because filtered rows shrink the candidate set.
CREATE INDEX IF NOT EXISTS movies_embedding_hnsw_idx
    ON movies USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- --- Metadata filter indexes ------------------------------------------------
CREATE INDEX IF NOT EXISTS movies_major_genre_idx  ON movies (major_genre);
CREATE INDEX IF NOT EXISTS movies_decade_idx       ON movies (decade);
CREATE INDEX IF NOT EXISTS movies_mpaa_rating_idx  ON movies (mpaa_rating);
CREATE INDEX IF NOT EXISTS movies_release_year_idx ON movies (release_year);
CREATE INDEX IF NOT EXISTS movies_imdb_rating_idx  ON movies (imdb_rating);

-- Covers the common combination "genre plus decade" in one scan.
CREATE INDEX IF NOT EXISTS movies_genre_decade_idx ON movies (major_genre, decade);

-- --- Title lookup ------------------------------------------------------------
-- Exact and case-insensitive match.
CREATE INDEX IF NOT EXISTS movies_title_lower_idx ON movies (LOWER(title));

-- Fuzzy match. GIN plus trigrams answers `title % $1` and `similarity(title, $1)`.
CREATE INDEX IF NOT EXISTS movies_title_trgm_idx
    ON movies USING gin (title gin_trgm_ops);
