-- ---------------------------------------------------------------------------
-- Documented hybrid query: vector similarity combined with metadata filters.
--
-- This is the exact statement that `search_movies_by_description` runs. It
-- lives here as well so that it can be read, explained, and run by hand.
--
-- Run it with psql:
--
--   docker compose exec postgres psql -U movies -d movies \
--     -f /docker-entrypoint-initdb.d/hybrid_search.sql
--
-- ...or paste it into any client. Bind the six parameters:
--
--   $1  vector(768)  the embedded search query
--   $2  text         major genre, or NULL for no genre filter
--   $3  numeric      minimum IMDB rating, or NULL
--   $4  text         MPAA rating, or NULL
--   $5  integer      decade such as 1990, or NULL
--   $6  integer      number of rows to return
-- ---------------------------------------------------------------------------

-- Widen the HNSW candidate list. The index returns its candidates first and the
-- filters remove rows afterwards, so a narrow list can return fewer rows than
-- requested. A value of 40 times top_k keeps recall high on this table size.
-- The setting is transaction-local, so it never leaks to another query.
SET LOCAL hnsw.ef_search = 200;

SELECT
    id,
    title,
    release_year,
    decade,
    major_genre,
    creative_type,
    source,
    mpaa_rating,
    director,
    distributor,
    running_time_min,
    production_budget,
    us_gross,
    worldwide_gross,
    imdb_rating,
    imdb_votes,
    rt_rating,
    budget_tier,
    blockbuster_flag,
    rating_score_delta,
    imputed_fields,
    -- Cosine distance is `<=>`. The vectors are L2-normalized, so the
    -- similarity is 1 - distance and it falls in the range 0.0 to 1.0.
    1 - (embedding <=> $1::vector) AS similarity
FROM movies
WHERE embedding IS NOT NULL
  -- Each filter is a no-op when its parameter is NULL. One statement therefore
  -- serves every combination of filters, and the query plan stays cached.
  AND ($2::text    IS NULL OR major_genre = $2::text)
  AND ($3::numeric IS NULL OR imdb_rating >= $3::numeric)
  AND ($4::text    IS NULL OR mpaa_rating = $4::text)
  AND ($5::int     IS NULL OR decade      = $5::int)
ORDER BY embedding <=> $1::vector
LIMIT $6::int;

-- ---------------------------------------------------------------------------
-- Worked example — "action movies from the 90s with high IMDB ratings".
--
-- The .NET API and the MCP server split that sentence into two parts:
--
--   * the semantic part  -> the embedded text, parameter $1
--   * the hard filters   -> genre = 'Action', decade = 1990, min rating = 7.0
--
-- The filters are exact and cheap. The vector distance then ranks whatever
-- survives them. Neither half can do the job alone: a pure vector search
-- returns 1980s action films as well, and a pure filter cannot tell a heist
-- film from a war film.
--
-- To see the plan, prefix the statement with EXPLAIN ANALYZE.
-- ---------------------------------------------------------------------------
