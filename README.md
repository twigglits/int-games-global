# Intelligent Movie Search Platform

Semantic search over the Vega movies dataset. A Python pipeline cleans, imputes,
augments and embeds 3 200 films into PostgreSQL with pgvector. A FastMCP server
exposes search as MCP tools. A .NET 10 API puts a public, authenticated,
observable face on it. The whole thing starts with one command, and the same
containers deploy to AWS through Terraform.

```bash
git clone <repository-url> && cd movie-search-platform
cp .env.example .env
docker compose up --build
```

Nothing else. The first run downloads the embedding model, loads the dataset and
comes up ready to search.

---

## Contents

1. [Architecture](#1-architecture)
2. [Prerequisites](#2-prerequisites)
3. [Quick start](#3-quick-start)
4. [Service endpoints](#4-service-endpoints)
5. [Data pipeline](#5-data-pipeline)
6. [Data decisions](#6-data-decisions)
7. [Embedding strategy](#7-embedding-strategy)
8. [Database and search](#8-database-and-search)
9. [MCP server](#9-mcp-server)
10. [API documentation](#10-api-documentation)
11. [Authentication](#11-authentication)
12. [Observability](#12-observability)
13. [Embedding Atlas](#13-embedding-atlas-bonus)
14. [Terraform deployment](#14-terraform-deployment)
15. [Running the tests](#15-running-the-tests)
16. [Technology choices](#16-technology-choices)
17. [Known limitations and future work](#17-known-limitations-and-future-work)
18. [Hardening the Terraform state](#hardening-the-terraform-state)

---

## 1. Architecture

![Architecture](ARCHITECTURE_DIAGRAM.png)

```
                         ┌──────────────────────────────────────────────┐
   client ──HTTPS──────▶ │  .NET 10 Web API            :8080            │
                         │  JWT · OpenAPI 3.1 · cache · rate limit      │
                         └───────────────────┬──────────────────────────┘
                                             │ MCP over SSE (local)
                                             │ MCP over streamable HTTP (AWS)
                         ┌───────────────────▼──────────────────────────┐
                         │  Python MCP server (FastMCP)  :8000          │
                         │  6 tools · asyncpg pool · Pydantic v2        │
                         └────────┬────────────────────────┬────────────┘
                                  │ SQL                    │ HTTP
                    ┌─────────────▼──────────┐   ┌─────────▼─────────────┐
                    │ PostgreSQL 16          │   │ Text Embeddings       │
                    │ + pgvector  :5432      │   │ Inference      :8001  │
                    │ HNSW · pg_trgm         │   │ BAAI/bge-base-en-v1.5 │
                    └─────────────▲──────────┘   └─────────▲─────────────┘
                                  │                        │
                    ┌─────────────┴────────────────────────┴─────────────┐
                    │ Data pipeline (runs once, exits)                   │
                    │ clean → impute → augment → embed → load            │
                    └────────────────────────────────────────────────────┘

     Flyway migrates the schema before the pipeline runs.
     Embedding Atlas (:7000) reads the vectors back out and draws them.
     Prometheus (:9090), Grafana (:3000) and Jaeger (:16686) span every service.
```

**The request path, end to end.** A client posts credentials to `/auth/token`
and receives a JWT. It calls `GET /api/v1/movies/search?q=...`. The API validates
the criteria, checks its response cache, and calls the MCP tool
`search_movies_by_description` over MCP. The MCP server embeds the query text
through the embedding container, then runs one SQL statement that applies the
metadata filters and orders by cosine distance against the HNSW index. Rows come
back up the same path. One trace covers all of it, because the .NET HTTP client
writes a W3C `traceparent` header and the Python server reads it back off.

---

## 2. Prerequisites

To run the platform, one thing:

| Tool | Version | Why |
| --- | --- | --- |
| Docker Engine | 24.0 or later | Everything runs in containers |
| Docker Compose | v2.20 or later | `depends_on` conditions and `--wait` |

Verified on Docker 29.7.2 with Compose v5.4.0.

Nothing else is needed. Python, .NET and Terraform are only required to work on
the source outside containers:

| Tool | Version | Needed for |
| --- | --- | --- |
| Python | 3.12 or later | Running the Python tests outside Docker |
| .NET SDK | 10.0 | Running the .NET tests outside Docker |
| Terraform | 1.9 or later | The AWS deployment |
| k6 | any recent | The load test, unless the Docker image is used |

**Resources.** The first build pulls roughly 5 GB of images and the embedding
model is another 440 MB. Give Docker at least 6 GB of memory and 15 GB of disk.
The Embedding Atlas image alone is 3 GB, because it depends on PyTorch; skip it
with `docker compose up --scale atlas=0` if disk is tight.

---

## 3. Quick start

```bash
# 1. Clone
git clone <repository-url>
cd movie-search-platform

# 2. Create the environment file. The defaults are development-only values.
cp .env.example .env

# 3. Start everything and wait for it to be healthy.
docker compose up --build --wait

# 4. Get a token.
TOKEN=$(curl -s -X POST http://localhost:8080/auth/token \
  -H 'Content-Type: application/json' \
  -d '{"client_id":"reader-client","client_secret":"reader-secret-change-me"}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')

# 5. Search.
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8080/api/v1/movies/search?q=sci-fi+films+directed+by+James+Cameron&top_k=5" \
  | python3 -m json.tool
```

Five commands, and the fifth is the demonstration.

**How long the first run takes.** Building the images takes five to ten minutes.
The embedding container then downloads the model, and the pipeline embeds 3 200
films on CPU, which took **299 seconds** on the reference machine. Every later
`docker compose up` skips both: the model is cached in a volume, and the pipeline
finds nothing changed and writes nothing.

**If a port is already in use.** Every host port is a variable in `.env`. The
error names the port; change it there and start again:

```bash
API_HOST_PORT=18080
POSTGRES_HOST_PORT=15432
MCP_HOST_PORT=18000
EMBEDDINGS_HOST_PORT=18001
ATLAS_HOST_PORT=17000
GRAFANA_HOST_PORT=13000
PROMETHEUS_HOST_PORT=19090
JAEGER_HOST_PORT=16686
```

**Check it worked.** One script exercises every endpoint, both roles, the
validation rules and the cache:

```bash
./scripts/smoke_test.sh
```

---

## 4. Service endpoints

| Service | URL | What is there |
| --- | --- | --- |
| **API** | http://localhost:8080 | Redirects to the Swagger UI |
| Swagger UI | http://localhost:8080/swagger | Try every endpoint in the browser |
| OpenAPI 3.1 | http://localhost:8080/openapi/v1.json | The machine-readable contract |
| API health | http://localhost:8080/health | Overall, with the detail of each check |
| API liveness | http://localhost:8080/health/live | Process only, no dependency check |
| API readiness | http://localhost:8080/health/ready | Reaches the MCP server, the database and the model |
| API metrics | http://localhost:8080/metrics | Prometheus exposition |
| **MCP server** | http://localhost:8000/sse | MCP over Server-Sent Events |
| MCP health | http://localhost:8000/health | Database, embedding service, row count |
| MCP metrics | http://localhost:8000/metrics | Tool, query and embedding timings |
| **Embeddings** | http://localhost:8001 | Text Embeddings Inference |
| Embeddings health | http://localhost:8001/health | |
| **PostgreSQL** | `localhost:5432` | user `movies`, database `movies` |
| **Grafana** | http://localhost:3000 | Opens on the platform dashboard |
| **Prometheus** | http://localhost:9090 | |
| **Jaeger** | http://localhost:16686 | Distributed traces |
| **Embedding Atlas** | http://localhost:7000 | The vector space, drawn |

Grafana allows anonymous viewing, so the dashboard needs no login. The admin
account is `admin` / `admin` from `.env`.

---

## 5. Data pipeline

### What it does

Six stages, each a pure function over a dataframe plus a report object, so each
one is tested on its own:

| Stage | Module | What it produces |
| --- | --- | --- |
| Source | `dataset.py` | 3 201 raw records |
| Clean | `cleaning.py` | 3 200 rows plus a report of every change |
| Impute | `imputation.py` | No missing value that should be filled, and a per-row record of which fields were |
| Augment | `augmentation.py` | Five derived features, the embedded text, a content hash |
| Embed | `embedding.py` | One 768-dimension vector per row |
| Load | `loader.py` | An upsert that writes only what changed |

### Running it

```bash
docker compose run --rm pipeline          # on demand
docker compose up pipeline                # as part of the platform
```

It runs automatically as part of `docker compose up`, because everything
downstream of it declares `depends_on: pipeline: condition:
service_completed_successfully`.

### Idempotency

Three mechanisms, each doing a different job:

1. **A natural key.** `source_key` is the slugified title plus the release date,
   for example `the-terminator::1984-10-26`. A second run collides with the same
   row instead of inserting beside it. The key is title **and** date because 24
   titles in this dataset are shared by two films — *Casino Royale* (1967 and
   2006), *Alice in Wonderland* (1951 and 2010). Deduplicating on the title alone
   would delete real films.
2. **A conditional update.** `ON CONFLICT (source_key) DO UPDATE ... WHERE`
   writes only when the content hash, the embedding model or the pipeline version
   actually differ. An unchanged row is not written, so its `updated_at` keeps
   its original value.
3. **Vector reuse.** Before embedding anything, the pipeline reads back the
   stored `augmented_text` and `embedding_model`. A row whose text and model both
   match keeps its vector and is never sent to the embedding service.

Verified end to end:

```
First run                       Second run
  embedded   : 3200               embedded   : 0
  inserted   : 3200               inserted   : 0
  updated    : 0                  updated    : 0
  unchanged  : 0                  unchanged  : 3200
  duration   : 298.97s            duration   : 0.00s
```

### Verifying it

```bash
# The report, as text, on stdout.
docker compose logs pipeline | tail -80

# The same report as JSON, and the log file.
cat logs/pipeline/pipeline_report.json
cat logs/pipeline/pipeline.log

# What is actually in the database.
docker compose exec postgres psql -U movies -d movies -c \
  "SELECT count(*) AS rows, count(embedding) AS embedded,
          min(release_year) AS earliest, max(release_year) AS latest,
          count(DISTINCT major_genre) AS genres FROM movies;"
```

which reports 3 200 rows, 3 200 embedded, 1915 to 2011, 13 genres.

### Configuration

| Variable | Default | Effect |
| --- | --- | --- |
| `PIPELINE_BATCH_SIZE` | 32 | Texts per embedding request, clamped down to the server's own limit |
| `PIPELINE_FORCE_REEMBED` | `false` | Re-embed everything, ignoring the reuse rules |
| `PIPELINE_MAX_RELEASE_YEAR` | 2011 | Last year the dataset can contain; see below |
| `PIPELINE_LOG_LEVEL` | `INFO` | |
| `PIPELINE_VERSION` | 1.0.0 | Written to every row; changing it forces a rewrite |

---

## 6. Data decisions

Every decision below is also emitted in the run report, so the reasoning travels
with the data rather than living only here.

### Cleaning

| Issue found | Rows | What was done | Why |
| --- | --- | --- | --- |
| Title stored as a number (`300`, `2012`, `1408`) | 9 | Coerced to text | The column is a title, not a quantity |
| Row with no title | 1 | Dropped | A record with no title cannot be searched for or referred to |
| Two-digit-year rollover | 20 | Shifted back a century | See below |
| MPAA value `Open` | 2 | Mapped to `Not Rated` | It is not an MPAA certificate |
| Zero `US Gross` | 66 | Set to NULL | A zero gross is a missing figure, not a real one |
| Zero `Worldwide Gross` | 47 | Set to NULL | Same |
| Repeated titles | 48 | **Kept** | Remakes; the natural key is title plus date |
| Exact duplicate rows | 0 | — | Checked, none present |

**The rollover is the interesting one.** The source encodes years with two
digits, so *The Birth of a Nation* (1915) parses as **2015** and *Ben-Hur* (1925)
parses as **2025**. A "later than today" test does not catch either, because both
are already in the past. The bound therefore comes from the dataset: it ends in
2011, so any later year is the bug, and the correction is a century. That moved
20 rows and pulled the range from 1915–2046 to 1915–2011.

### Imputation

The question asked of every field was: does filling this help semantic search
more than it distorts the data? The answers differ, so the strategies differ.

| Field | Missing | Strategy | Why |
| --- | --- | --- | --- |
| `imdb_rating` | 213 | Median within Major Genre | Ratings cluster by genre. The median resists outliers and sits mid-scale, so an imputed row cannot pass a "highly rated" filter it does not deserve |
| `rt_rating` | 880 | **Least-squares fit against the observed IMDB rating** | The two correlate strongly here: Pearson r = 0.74 over 2 259 paired rows, fitting `rt = 17.01 × imdb − 53.04`. That carries far more information than a median. Rows with no observed IMDB rating fall through to the genre median |
| `running_time_min` | 1 992 | Median within Major Genre | Runtime follows genre convention; a documentary is shorter than an epic |
| `production_budget` | 1 | Median within release decade | Budgets are nominal dollars and inflate over time, so a decade median is closer than one global median |
| `major_genre` | 275 | Constant `Unknown` | Genre is an exact search filter. A guessed genre returns the wrong rows |
| `creative_type` | 446 | Constant `Unknown` | A label, not a measurement |
| `source` | 365 | Constant `Unknown` | Source material cannot be inferred from budget or box office |
| `director` | 1 330 | Constant `Unknown` | A director is an identity. The mode would attribute over a thousand films to one person and poison every director query |
| `distributor` | 232 | Constant `Unknown` | The mode would attribute independent films to a major studio |
| `mpaa_rating` | 605 | Constant `Not Rated` | `Not Rated` is a real MPAA outcome that already appears 94 times, so it is a truthful bucket rather than a sentinel |
| `imdb_votes` | 213 | **Left NULL** | Vote count measures audience size. A median would invent an audience and make an obscure film look popular |
| `us_gross` | 73 | **Left NULL** | Box office is a recorded fact, not a property that can be estimated |
| `worldwide_gross` | 54 | **Left NULL** | Same |
| `us_dvd_sales` | 2 636 | **Left NULL** | 82 % of the column is missing. Any fill value would define the column rather than complete it |

Two rules hold across the stage:

- **Nothing is imputed in secret.** Every row carries an `imputed_fields` array
  naming the columns whose value was filled. It is returned by the API, so a
  consumer can exclude estimated values from any analysis.
- **No imputation feeds another.** The Rotten Tomatoes fit reads the
  *pre-imputation* IMDB column. Predicting a critic score from an already-guessed
  audience score would stack one guess on another and report it as a measurement.

### Derived features

Five, against a required minimum of two.

| Feature | Definition | Why it exists |
| --- | --- | --- |
| `decade` | `floor(year / 10) × 10` | The API and the MCP tools expose a decade filter. Deriving it once makes that filter an indexed integer comparison rather than a date range |
| `budget_tier` | micro `<$5M`, low `<$20M`, mid `<$50M`, high `<$100M`, blockbuster `≥$100M` | Turns a dollar figure into the words people search with. **Fixed** cut points, not quantiles: a quantile boundary moves whenever rows are added, so the same film could change tier without changing budget |
| `rating_score_delta` | `imdb × 10 − rt` | The gap between the audience score and the critic score on one scale. It separates a crowd-pleaser from a critics' film, which neither rating column can do alone |
| `blockbuster_flag` | gross ≥ $100M **and** ≥ 2 × budget | Gross alone rewards an expensive film that lost money. 667 films qualify |
| `profit_ratio` | `worldwide_gross / budget`, capped at 9 999 | The continuous form of the flag |

---

## 7. Embedding strategy

### The model

**`BAAI/bge-base-en-v1.5`, 768 dimensions**, served by
[Text Embeddings Inference](https://github.com/huggingface/text-embeddings-inference)
in its own container.

Why this one:

- **768 dimensions**, which matches the `vector(768)` column in the specification
  without changing the schema.
- **Strong retrieval quality for its size.** BGE-base sits near the top of the
  MTEB retrieval board among models small enough to run on a CPU.
- **Native support in Text Embeddings Inference.** It needs no
  `trust_remote_code`, which matters because the alternative first choice,
  `nomic-embed-text-v1.5`, does not load at all: TEI 1.7 rejects its
  `config.json` with `duplicate field max_position_embeddings`. That was found by
  trying it, not by reading about it.
- **Normalised output.** The vectors come back L2-normalised, so cosine
  similarity is `1 − distance` and needs no rescaling.

To change the model, three things move together: `EMBEDDING_MODEL_ID`,
`EMBEDDING_DIM`, and the `vector(n)` column in
`database/migrations/V1__initial_schema.sql`. The pipeline refuses to start when
they disagree, and says which two disagree.

### The container, and how it is wired

```yaml
embeddings:
  image: ghcr.io/huggingface/text-embeddings-inference:cpu-1.7
  command: [--model-id=BAAI/bge-base-en-v1.5, --auto-truncate, --port=80]
  volumes: [embeddings-cache:/data]      # weights survive a restart
  healthcheck: curl -fsS http://localhost:80/health
```

Neither the pipeline nor the MCP server loads a model in process. Both hold an
HTTP client and call `POST /embed`. Both wait for the service themselves as well
as through the Compose health check, so either runs correctly on its own.

The pipeline reads `GET /info` at start-up and clamps its batch size to whatever
the server accepts — TEI reports `max_client_batch_size: 32` — then embeds a
probe string and refuses to continue if the width is not the configured one.

### The text that gets embedded

The template from the specification, plus the derived features written as words:

```
Title: Aliens
Genre: Action
Director: James Cameron
MPAA Rating: R
Release Year: 1986
Runtime: 137 minutes
IMDB Rating: 7.5/10 (84 votes)
Rotten Tomatoes: 100%
Budget: $17,000,000
Distributor: 20th Century Fox
Creative Type: Science Fiction
Source: Original Screenplay
Decade: 1980s
Budget Tier: Low-budget ($5M to $20M)
Critical Reception: Critically acclaimed by reviewers
Audience Reception: critics liked it much more than audiences did
Box Office: $183,316,455 worldwide, a commercial blockbuster
```

Two rules change what reaches the model, and both measurably improve results:

**A line whose value was imputed is dropped.** `Director: Unknown` repeated over
1 330 films would give those films a phrase in common that has nothing to do with
their content, and the model would place them near each other for that reason
alone. The column still holds `Unknown`, so metadata filters are unaffected — but
the vector space is not polluted. The same applies to genre, MPAA rating,
distributor, creative type and source.

**An interpretive line is written only from an observed score.** "Critically
acclaimed" comes from a real Rotten Tomatoes score, never from an imputed one.
Turning a guess into a strong adjective would publish it as a fact and pull the
row toward queries it has no claim on.

The result averages 426 characters, about 110 tokens, well inside the model's
512-token window.

### Asymmetric prefixes

BGE models are trained asymmetrically: a **query** carries an instruction, a
**document** does not.

```
EMBEDDING_DOC_PREFIX=                                                        # nothing
EMBEDDING_QUERY_PREFIX="Represent this sentence for searching relevant passages:"
```

The separating space is added in code rather than carried inside the configured
value, because a trailing space does not survive a `.env` file or a Kubernetes
ConfigMap.

### Does it work?

The five queries from the specification, run against the live platform:

| Query | Top results |
| --- | --- |
| `sci-fi films directed by James Cameron` | **Aliens**, **The Terminator**, **Terminator 2: Judgment Day** — all three are Cameron films, ranked 1, 2, 3 |
| `action movies from the 90s with high IMDB ratings` (genre=Action, decade=1990, min 7.0) | Die Hard: With a Vengeance, The Matrix, Die Hard 2, Face/Off, The Fifth Element |
| `animated family movies distributed by Disney` | 102 Dalmatians, The Princess and the Frog, Lilo & Stitch, Doug's 1st Movie, Pooh's Heffalump Movie |
| `critically acclaimed drama films with small budgets` (genre=Drama) | Little Women, Ordinary People, Harsh Times, A Mighty Heart, Closer |
| `dark psychological thrillers with low Rotten Tomatoes scores` | The Dark Hours, Dark City, **Twisted (RT 2)**, **Darkness (RT 4)**, Chocolate: Deep Dark Secrets |

Nearest neighbours of *The Terminator*: Terminator 2 (0.907), Terminator 3
(0.880), Terminator Salvation (0.861), Aliens (0.858), Predator (0.844).

---

## 8. Database and search

### Schema

One table holds the structured metadata **and** the vector. A separate vector
table would force a join on every search and give the planner no way to push the
filters down.

```sql
CREATE TABLE movies (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_key         TEXT NOT NULL UNIQUE,     -- idempotency key
    title              TEXT NOT NULL,
    release_date       DATE,
    release_year       INTEGER,
    decade             INTEGER,
    major_genre        TEXT,
    creative_type      TEXT,
    source             TEXT,
    mpaa_rating        TEXT,
    director           TEXT,
    distributor        TEXT,
    running_time_min   INTEGER,
    production_budget  BIGINT,
    us_gross           BIGINT,
    worldwide_gross    BIGINT,
    us_dvd_sales       BIGINT,
    imdb_rating        NUMERIC(3,1),
    imdb_votes         INTEGER,
    rt_rating          INTEGER,
    budget_tier        TEXT,
    rating_score_delta NUMERIC(4,1),
    blockbuster_flag   BOOLEAN,
    profit_ratio       NUMERIC(10,3),
    imputed_fields     TEXT[] NOT NULL DEFAULT '{}',   -- provenance
    augmented_text     TEXT NOT NULL,
    content_hash       TEXT NOT NULL,
    embedding          vector(768),
    embedding_model    TEXT,
    pipeline_version   TEXT,                            -- audit
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT movies_imdb_rating_range CHECK (imdb_rating BETWEEN 0 AND 10),
    CONSTRAINT movies_rt_rating_range   CHECK (rt_rating   BETWEEN 0 AND 100)
    -- ...four more range constraints
);
```

The check constraints repeat what the pipeline already enforces. They are there
for the value that arrives by some other path.

### Indexes

```sql
CREATE INDEX movies_embedding_hnsw_idx ON movies
  USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);

CREATE INDEX movies_major_genre_idx   ON movies (major_genre);
CREATE INDEX movies_decade_idx        ON movies (decade);
CREATE INDEX movies_mpaa_rating_idx   ON movies (mpaa_rating);
CREATE INDEX movies_imdb_rating_idx   ON movies (imdb_rating);
CREATE INDEX movies_genre_decade_idx  ON movies (major_genre, decade);
CREATE INDEX movies_title_lower_idx   ON movies (LOWER(title));
CREATE INDEX movies_title_trgm_idx    ON movies USING gin (title gin_trgm_ops);
```

**HNSW rather than IVFFlat**, because HNSW needs no training step and keeps its
recall when the pipeline adds rows later. Cosine distance, because the model
returns normalised vectors.

### The hybrid query

Documented in full, with a worked example, in
[`database/queries/hybrid_search.sql`](database/queries/hybrid_search.sql). It is
the statement `search_movies_by_description` runs:

```sql
SET LOCAL hnsw.ef_search = 200;

SELECT id, title, release_year, decade, major_genre, /* ...  */
       1 - (embedding <=> $1::vector) AS similarity
FROM movies
WHERE embedding IS NOT NULL
  AND ($2::text    IS NULL OR major_genre = $2::text)
  AND ($3::numeric IS NULL OR imdb_rating >= $3::numeric)
  AND ($4::text    IS NULL OR mpaa_rating = $4::text)
  AND ($5::int     IS NULL OR decade      = $5::int)
ORDER BY embedding <=> $1::vector
LIMIT $6::int;
```

Three things are deliberate:

1. **Every filter disappears when its parameter is NULL**, so one prepared
   statement serves every combination and the plan stays cached.
2. **`hnsw.ef_search` is widened before the query.** The index returns its
   candidate list first and the filters remove rows afterwards, so a narrow list
   can return fewer rows than asked for. The MCP server computes the value from
   `top_k` and clamps it to `[100, 1000]`. It is set with `SET LOCAL`, so it
   never leaks to another query.
3. **Neither half works alone.** A pure vector search for "action movies from
   the 90s" also returns 1980s action films; a pure filter cannot tell a heist
   film from a war film.

### Migrations: Flyway, and why

**Flyway**, not Alembic.

- The schema is **SQL-first**. A pgvector column type, an HNSW index with
  `m` and `ef_construction`, and a GIN trigram index are things you write in SQL.
  Expressing them through an ORM's migration DSL means writing the same SQL
  inside `op.execute()` strings and gaining nothing.
- The schema is **shared by two languages**. Python writes to it, .NET reads
  through the MCP server. A migrator tied to one of them makes that one the owner
  of a schema both depend on. Flyway belongs to neither.
- **No ORM is in use.** The pipeline uses psycopg with explicit SQL and the MCP
  server uses asyncpg with explicit SQL, because both run statements an ORM would
  obscure. Alembic's autogeneration, its main advantage, has no model to compare
  against.
- Versioned files with checksums, a schema history table, and the exact
  `V1__initial_schema.sql` naming the deliverables ask for.

```bash
docker compose run --rm flyway info       # what has been applied
docker compose run --rm flyway migrate    # apply anything new
docker compose run --rm flyway validate   # checksums still match
```

---

## 9. MCP server

FastMCP over SSE locally, streamable HTTP in production. Six tools, every input
and output a Pydantic v2 model, one asyncpg pool shared by all of them.

### Tools

| Tool | Signature | Notes |
| --- | --- | --- |
| `search_movies_by_description` | `(query, top_k=10, genre_filter=None, min_imdb_rating=None, mpaa_rating=None, decade=None) -> list[MovieResult]` | The hybrid search |
| `get_movie_by_title` | `(title) -> MovieResult \| None` | Exact match first, then trigram similarity |
| `get_movie_by_id` | `(movie_id) -> MovieResult \| None` | Added beyond the specified five: the API's `/movies/{id}` route needs it, and every other tool returns identifiers |
| `get_similar_movies` | `(movie_id, top_k=5) -> list[MovieResult]` | The movie is never its own neighbour |
| `list_genres` | `() -> list[str]` | Most common first |
| `get_dataset_stats` | `() -> DatasetStats` | Counts, ranges, per-genre and per-decade breakdown |

### The fuzzy title match

Worth describing, because a naive threshold gets it wrong. The score is the
larger of two pg_trgm measures:

```sql
GREATEST(similarity(title, $1), word_similarity($1, title))
```

`similarity` compares the strings whole and handles a misspelling, but punishes a
query much shorter than the title. `word_similarity` compares the query against
the best matching stretch of the title and handles a partial title. Taking the
larger of the two is what makes `Termnator 2` find *Terminator 2: Judgment Day*
rather than *The Terminator*. A tie is broken by the shorter title, so
`Jurasic Park` finds *Jurassic Park* rather than *Jurassic Park 3*.

Calibrated against this dataset: real misspellings score 0.60 to 1.00, unrelated
strings score below 0.35. The threshold is 0.50.

| Query | Result |
| --- | --- |
| `Termnator 2` | Terminator 2: Judgment Day |
| `Jurasic Park` | Jurassic Park |
| `Godfathr` | The Godfather |
| `shawshank redemtion` | The Shawshank Redemption |
| `lord of the rings fellowship` | The Lord of the Rings: The Fellowship of the Ring |
| `qqqqq wwwww eeeee` | *nothing* |

### Testing the tools directly

Any MCP client works. With the Python client that ships with FastMCP:

```bash
pip install fastmcp
python - <<'EOF'
import asyncio
from fastmcp import Client

async def main():
    async with Client("http://localhost:8000/sse") as client:
        print([t.name for t in await client.list_tools()])

        result = await client.call_tool("search_movies_by_description", {
            "query": "dark psychological thrillers with low Rotten Tomatoes scores",
            "top_k": 5,
        })
        for movie in result.data:
            print(f"{movie.similarity:.4f}  {movie.title} ({movie.release_year})")

        print((await client.call_tool("get_dataset_stats", {})).data)

asyncio.run(main())
EOF
```

Or point any MCP-compatible tool at `http://localhost:8000/sse`.

### Server behaviour

- **Transport** is `MCP_TRANSPORT`: `sse` mounts at `/sse`, `http` (streamable
  HTTP) mounts at `/mcp`. Production uses `http`, because a long-lived event
  stream survives a load balancer idle timeout poorly.
- **Connection pooling** through asyncpg, opened once by the application
  lifespan and shared. Size is `MCP_DB_POOL_MIN` to `MCP_DB_POOL_MAX`.
- **`GET /health`** reaches the database and the embedding service and answers
  200 only when both are up *and* at least one movie carries a vector. A server
  with an empty table can accept a search and return nothing useful, which is not
  healthy.
- **Structured logging.** One JSON object per line, with `trace_id` and
  `span_id` on every line. uvicorn, httpx and the MCP library are routed through
  the same formatter, so the container emits one format and only one.
- **Configuration** comes entirely from the environment. There is no hardcoded
  host, port or credential.
- **Errors** are `ToolError` with a sentence a person can act on: `movie_id must
  be a UUID, received 'not-a-uuid'`, `top_k must be between 1 and 50`.

---

## 10. API documentation

Base URL `http://localhost:8080`. All `/api/v1/*` routes need a bearer token.
Responses are snake_case throughout, to match the query parameters.

### `POST /auth/token`

```bash
curl -s -X POST http://localhost:8080/auth/token \
  -H 'Content-Type: application/json' \
  -d '{"client_id":"reader-client","client_secret":"reader-secret-change-me"}'
```

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "Bearer",
  "expires_in": 3600,
  "roles": ["reader"]
}
```

### `GET /api/v1/movies/search`

| Parameter | Type | Default | Notes |
| --- | --- | --- | --- |
| `q` | string, **required** | — | Natural language description, 1 to 1 000 characters |
| `top_k` | int | 10 | 1 to 50 |
| `genre` | string | — | Exact value; `GET /api/v1/movies/genres` lists them |
| `min_imdb_rating` | float | — | 0 to 10 |
| `mpaa_rating` | string | — | `G`, `PG`, `PG-13`, `R`, `NC-17`, `Not Rated` |
| `decade` | int | — | The first year of a decade, for example `1990` |

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8080/api/v1/movies/search?q=action+movies+from+the+90s+with+high+IMDB+ratings&genre=Action&decade=1990&min_imdb_rating=7&top_k=3"
```

```json
{
  "query": "action movies from the 90s with high IMDB ratings",
  "count": 3,
  "top_k": 3,
  "filters": { "genre": "Action", "min_imdb_rating": 7, "decade": 1990 },
  "cached": false,
  "took_ms": 206.97,
  "results": [
    {
      "id": "8f0c1e2a-...",
      "title": "Die Hard: With a Vengeance",
      "release_date": "1995-05-19",
      "release_year": 1995,
      "decade": 1990,
      "major_genre": "Action",
      "creative_type": "Contemporary Fiction",
      "source": "Original Screenplay",
      "mpaa_rating": "R",
      "director": "John McTiernan",
      "distributor": "20th Century Fox",
      "running_time_min": 128,
      "production_budget": 90000000,
      "us_gross": 100012499,
      "worldwide_gross": 366101666,
      "imdb_rating": 7.4,
      "imdb_votes": 137891,
      "rt_rating": 73,
      "budget_tier": "high",
      "blockbuster_flag": true,
      "rating_score_delta": 1.0,
      "imputed_fields": [],
      "similarity": 0.6034
    }
  ]
}
```

`imputed_fields` names any field the pipeline filled in. `cached` says whether
the response came from the in-memory cache.

### `GET /api/v1/movies/{id}`

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8080/api/v1/movies/8f0c1e2a-1111-2222-3333-444455556666
```

Returns one movie, or 404 with a problem document.

### `GET /api/v1/movies/{id}/similar?top_k=5`

```json
{
  "movie_id": "8267e750-...",
  "count": 5,
  "results": [
    { "title": "Terminator 2: Judgment Day", "similarity": 0.9065, "...": "..." },
    { "title": "Terminator 3: Rise of the Machines", "similarity": 0.8802, "...": "..." }
  ]
}
```

### `GET /api/v1/movies/genres`

```json
{
  "count": 13,
  "genres": ["Drama", "Comedy", "Action", "Unknown", "Adventure",
             "Thriller/Suspense", "Horror", "Romantic Comedy", "Musical",
             "Documentary", "Black Comedy", "Western", "Concert/Performance"]
}
```

### `GET /api/v1/stats` — requires the `admin` role

```json
{
  "total_movies": 3200,
  "movies_with_embeddings": 3200,
  "distinct_genres": 13,
  "earliest_release_year": 1915,
  "latest_release_year": 2011,
  "average_imdb_rating": 6.28,
  "movies_per_genre": [{ "genre": "Drama", "count": 789 }],
  "movies_per_decade": [{ "decade": 1990, "count": 769 }],
  "embedding_model": "BAAI/bge-base-en-v1.5",
  "embedding_dimension": 768,
  "pipeline_version": "1.0.0"
}
```

### Errors

Every failure is an RFC 9457 problem document with a `traceId`, so a caller
reporting a problem can name the exact trace to open in Jaeger.

```json
{
  "type": "https://datatracker.ietf.org/doc/html/rfc9110#section-15.5.1",
  "title": "Invalid request",
  "status": 400,
  "detail": "top_k must be between 1 and 50.",
  "instance": "/api/v1/movies/search",
  "parameter": "top_k",
  "traceId": "00-c4c4d70ccbcef745a8f47837aa3f10b3-1a2b3c4d5e6f7081-01"
}
```

| Status | When |
| --- | --- |
| 400 | The request is wrong: a missing `q`, a `top_k` outside 1–50, a rating above 10, a `decade` that is not a decade |
| 401 | No token, an expired token, or a token this API did not sign |
| 403 | A valid token without the role the route needs |
| 404 | No movie has that identifier |
| 429 | Over 60 requests a minute for this client. `Retry-After` says when to come back |
| 502 | The MCP server, the database or the embedding service failed |
| 504 | The request outlived its 30 second budget |

### OpenAPI

The document is generated from the endpoints and from the XML documentation
comments in the source, so it cannot drift from the code.

- Live: `GET /openapi/v1.json` — OpenAPI **3.1.1**, 6 paths, 11 schemas
- Swagger UI: http://localhost:8080/swagger
- Committed: [`openapi.json`](openapi.json), refreshed by
  `./scripts/export_openapi.sh`. CI fails if the committed copy is out of date.

---

## 11. Authentication

OAuth 2.0 client credentials, issuing a signed JWT.

```bash
TOKEN=$(curl -s -X POST http://localhost:8080/auth/token \
  -H 'Content-Type: application/json' \
  -d '{"client_id":"admin-client","client_secret":"admin-secret-change-me"}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')

curl -H "Authorization: Bearer $TOKEN" http://localhost:8080/api/v1/stats
```

### Roles

| Role | May do |
| --- | --- |
| `reader` | Search, read a movie, read neighbours, list genres |
| `admin` | Everything a reader may do, plus `GET /api/v1/stats` |

### Clients

The two development clients come from `.env`. In AWS the same values are
generated into Secrets Manager by `scripts/bootstrap_parameters.sh` and
injected by ECS; nothing is committed.

| Client | Roles | Secret variable |
| --- | --- | --- |
| `reader-client` | `reader` | `READER_CLIENT_SECRET` |
| `admin-client` | `reader`, `admin` | `ADMIN_CLIENT_SECRET` |

### What the implementation is careful about

- **The secret comparison is constant time.** Both sides are hashed and compared
  with `CryptographicOperations.FixedTimeEquals`. A plain string comparison
  returns as soon as two bytes differ, which leaks the length of the matching
  prefix to anyone who can measure the response time.
- **An unknown client and a wrong secret give byte-identical answers.** Telling
  the caller which half was wrong turns the endpoint into a client-id oracle.
  There is a test that asserts the two responses are identical.
- **Clock skew is 30 seconds, not the default five minutes**, so an expired token
  stops working when it expires.
- **The failure reason is logged, never returned.** It is useful to an operator
  and dangerous to a caller.
- **The signing key must be at least 32 bytes** and is validated at start-up. The
  application refuses to start with a short one rather than failing on the first
  request.

---

## 12. Observability

### Traces — Jaeger, http://localhost:16686

Pick `movie-search-api` and search. One trace covers both services:

```
movie-search-api   GET /api/v1/movies/search                     259.0 ms
movie-search-api    └─ mcp.call/search_movies_by_description      179.8 ms
movie-search-mcp        └─ mcp.tool/search_movies_by_description   44.3 ms
movie-search-mcp             ├─ embedding.embed_query               31.0 ms
movie-search-mcp             └─ db.hybrid_search                     9.5 ms
```

Propagation is not configured anywhere by hand. The .NET HTTP client
instrumentation writes a W3C `traceparent` header on the outgoing MCP request;
FastMCP middleware on the Python side reads it back off and starts the tool span
as a child of it. Both services export OTLP over HTTP to Jaeger on 4318, which is
the same protocol they use against the AWS Distro for OpenTelemetry sidecar in
production — the application code does not change between the two.

### Metrics — Prometheus http://localhost:9090, Grafana http://localhost:3000

Grafana opens straight on **Movie Search Platform**, 17 panels across four rows.
The datasource and the dashboard are both provisioned, so there is nothing to set
up.

| Row | Panels |
| --- | --- |
| Service health | Services up, requests per second, p95 latency against the 500 ms budget, error rate |
| API traffic and latency | Request rate by route, p50/p95/p99, responses by status code, active connections and connection pool |
| MCP server | Tool latency as the API sees it, tool latency inside the server, where a search spends its time, tool calls by outcome |
| Cache, limits and model | Cache hit ratio, rate limiting by outcome, embedding queue and inference time, results per search, .NET runtime |

Every query was written against the metric names the services actually publish,
and each one was checked to return data before it was committed.

> **One configuration detail worth knowing.** The OpenTelemetry exporter
> publishes OpenTelemetry names, which contain dots: `http.server.request.duration`.
> Prometheus 3 stores a UTF-8 name exactly as it arrives, so without
> `metric_name_validation_scheme: legacy` in the scrape config, every series would
> be named with dots and every dashboard query would need the quoted-name syntax.
> That setting is in `monitoring/prometheus.yml` with the reason beside it.

Scrape targets: the .NET API, the MCP server, the embedding service, and
Prometheus itself. All four report `up`.

### Logs

Both services write one JSON object per line to stdout.

```bash
docker compose logs -f api
docker compose logs -f mcp-server

# On disk, and mounted to the host:
tail -f logs/api/movie-search-api-*.json
tail -f logs/pipeline/pipeline.log
```

The .NET API uses Serilog with the compact JSON formatter to both console and a
rolling file. The Python services use structlog, with uvicorn, httpx and the MCP
library routed through the same formatter so nothing escapes as plain text. Every
line carries `@tr` (.NET) or `trace_id` (Python), so a log line and a Jaeger trace
line up without guessing.

### Health

```bash
curl -s http://localhost:8080/health | python3 -m json.tool
```

```json
{
  "status": "healthy",
  "total_duration_ms": 39.23,
  "checks": [{
    "name": "mcp-server",
    "status": "healthy",
    "data": {
      "database": "up",
      "embeddings": "up",
      "movies_indexed": "3200",
      "transport": "sse"
    }
  }]
}
```

Three routes, because an orchestrator asks two different questions.
`/health/live` runs **no** dependency check: a liveness probe that fails when a
downstream service is down makes the orchestrator restart a healthy container and
throw away the recovery it would otherwise have made. `/health/ready` reaches the
whole chain. `/health` is the one a person opens.

---

## 13. Embedding Atlas (bonus)

http://localhost:7000

The container exports the vectors from pgvector, projects them to two dimensions
with UMAP under the **cosine** metric — the same metric the search uses, so the
picture agrees with the ranking — and serves them.

```bash
# Rebuild the export by hand if wanted:
python scripts/export_embeddings_atlas.py --output /data/movies_atlas.parquet --force
```

The projection is computed once and handed to Atlas through `--x` and `--y`, so
Atlas never loads a model of its own and starts in seconds.

### Reading it

Each point is one film, placed by what its text means rather than by any single
column.

1. **Colour by genre.** In the sidebar, set the colour field to `major_genre`.
   Coherent bands appear at once: horror separates cleanly, drama and comedy
   share a long border, documentaries sit apart from everything.
2. **The clusters are semantic, not categorical.** Franchise entries land on top
   of each other — the four Terminator films, the Harry Potter run — because
   their augmented texts genuinely say the same things. Two unrelated films with
   the same director and budget tier will sit close as well.
3. **A point far from every cluster is worth opening.** It is usually a row with
   most of its fields imputed, so its text is short and carries little signal.
   That is the visualisation showing you a data quality problem.
4. **Select a region** to see the rows behind it, and check that the neighbours
   the picture suggests are the neighbours `/api/v1/movies/{id}/similar` returns.
   They are computed from the same vectors, before the projection.
5. **What the axes mean: nothing.** UMAP coordinates have no units. Only relative
   distance carries information, and only locally.

`ATLAS_SAMPLE_SIZE` draws a random subset for a larger corpus; `0` uses every
row, which is the default and is comfortable at 3 200.

---

## 14. Terraform deployment

**To deploy this to a real AWS account, follow
[`terraform/README.md`](terraform/README.md).** It covers the account setup, the
state bootstrap, the domain and certificate, the secret and configuration
bootstrap, the cost, and the teardown. The orchestrator choice is argued in
[`ECS_EKS_CHOICE.md`](ECS_EKS_CHOICE.md).

In short:

```bash
# Check the configuration without touching AWS. This is what CI runs.
cd terraform && terraform fmt -check -recursive && terraform init -backend=false && terraform validate

# Once per environment: write the configuration and the secrets.
./scripts/bootstrap_parameters.sh dev

# Deploy. No -var flags: everything comes from Secrets Manager and Parameter Store.
cd terraform/environments/dev
terraform init
terraform plan -out=dev.tfplan
terraform apply dev.tfplan

# Push the images, deploy that tag, migrate, load.
# (the four commands are in terraform/README.md)
```

**Tearing it down is a button, not a runbook.** `.github/workflows/destroy.yml`
runs from the Actions tab and nowhere else — there is no push or schedule trigger.
You type the environment name to confirm, production needs a second phrase, and a
destroy plan is printed to the run summary before anything is deleted.

The teardown is **two Terraform runs**, and the reason is worth stating: a destroy
plan contains only delete actions, so Terraform never emits an update while
destroying. A `deletion_protection = false` in the configuration would never be
applied — Terraform would go straight to the delete call and AWS would refuse it.
So a targeted `apply -var force_destroy=true` flips the RDS and ALB flags in
place first, and the destroy that follows has nothing left to be refused by.
Terraform disarms itself, declaratively, rather than a shell script reaching
around it.

Then it drains the services, destroys, and **sweeps for the five things that
actually cost money**, writing a table of what is left. That last step is the one
that matters: a green destroy is not the same as an empty bill.

What it builds: a three-tier VPC with flow logs, an ECS Fargate cluster running
the API, the MCP server and the embedding service, RDS PostgreSQL 16 in private
subnets with no route to the internet, an ALB with an ACM certificate and an
HTTP-to-HTTPS redirect, target-tracking autoscaling on both CPU and memory,
CloudWatch alarms and a dashboard, X-Ray sampling rules, and a GitHub Actions
deployment role assumed through OIDC — no access key anywhere.

**Secrets and configuration live in two stores, split by what the value is.** The
four secrets are in **AWS Secrets Manager**, which gives them rotation, a
resource policy each, and `AWSCURRENT`/`AWSPREVIOUS` version labels so a rotation
does not break a running task. The six configuration values — domain name,
hosted zone, certificate ARN, alarm topic ARN — are in **Parameter Store**, which
is free at the standard tier and needs none of that. Both are written once per
environment by `scripts/bootstrap_parameters.sh`, before the first apply.

```
Parameter Store (String, free)          Secrets Manager ($0.40 each per month)
  /movie-search/dev/config/               movie-search/dev/
    domain-name              required       database-password
    route53-zone-id          optional       jwt-signing-key
    certificate-arn          optional       clients/reader-client
    github-oidc-provider-arn optional       clients/admin-client
    alarm-topic-arn          optional
    alb-access-logs-bucket   optional     (no leading slash — not a typo)
```

**No secret is in the Terraform state file.** Terraform resolves each secret ARN
with `data "aws_secretsmanager_secret"` — the singular data source, which returns
metadata and not the value — hands the ARN to the ECS task definition, and reads
exactly one secret value, the database password, through an `ephemeral` resource
into a write-only argument that is never persisted.

| Value | Who needs it | Mechanism | In state |
| --- | --- | --- | --- |
| All four secrets | Nobody, at plan time | `data "aws_secretsmanager_secret"` — metadata only | The ARN, which is not a secret |
| Signing key, client secrets | The ECS agent only | The ARN goes in the task definition's `secrets` block; the agent reads the value itself at task start | No |
| Database password | RDS, at create time | `ephemeral "aws_secretsmanager_secret_version"` feeds the write-only `password_wo` | No |
| Config values | Terraform, at plan time | `data "aws_ssm_parameters_by_path"`, one call for the subtree | Yes, correctly: a domain name is not a secret |

The ARN is resolved rather than constructed because Secrets Manager appends six
random characters to every ARN it creates — the real ones in the account end
`-yJ2Ca1`, `-FPhiUX`, `-r8KcNb`, `-Y668FF`. An SSM parameter ARN can be assembled
by hand from account, region and name; a Secrets Manager ARN cannot.

A CI job fails the build if anyone reintroduces a pattern that would put a secret
back into state — including `data "aws_secretsmanager_secret_version"`, which
differs from the ephemeral resource above by a single keyword. The trade is one
bootstrap step per environment, alongside the S3 state bootstrap you already do,
and $1.60 a month for the four secrets.

---

## 15. Running the tests

| Suite | Count | Command |
| --- | --- | --- |
| Pipeline unit tests | 85 | `cd pipeline && pytest` |
| MCP server unit tests | 73 | `cd mcp-server && pytest` |
| .NET unit and integration | 107 | `cd api && dotnet run --project tests/MovieSearch.Tests/MovieSearch.Tests.csproj` |
| End-to-end smoke test | 37 checks | `./scripts/smoke_test.sh` |
| Load test | — | see below |

```bash
# Python — the same commands CI runs
cd pipeline    && pip install -e ".[dev]" && ruff check . && ruff format --check . && mypy && pytest
cd mcp-server  && pip install -e ".[dev]" && ruff check . && ruff format --check . && mypy && pytest

# .NET
cd api
dotnet format MovieSearch.sln --verify-no-changes
dotnet build MovieSearch.sln -c Release
dotnet run --project tests/MovieSearch.Tests/MovieSearch.Tests.csproj -c Release --no-build
```

> **Why `dotnet run` and not `dotnet test`.** The .NET 10 SDK removed the VSTest
> bridge, and xunit.v3 runs on Microsoft.Testing.Platform, which makes the test
> project an executable. Running it directly is the supported path and executes
> all 107 tests.

Both Python services pass `mypy --strict` and `ruff` with no findings. The .NET
solution builds with `TreatWarningsAsErrors` and `latest-recommended` analysers,
so a successful build is a build with no analyser findings.

### Load test

```bash
docker run --rm --network movie-search-platform_movie-search \
  -v "$PWD/scripts:/scripts:ro" \
  -e API_BASE_URL=http://api:8080 \
  -e CLIENT_ID=reader-client -e CLIENT_SECRET=reader-secret-change-me \
  -e VUS=5 -e DURATION=60s \
  grafana/k6:latest run /scripts/load_test.js
```

Measured on the reference machine, at the rate the API's own 60/minute limit
permits:

```
  requests        56 over 60 s
  p50             0.4 ms      (cache hit)
  p95           119.1 ms      (budget 500 ms)  ✓
  max           181.7 ms
  errors          0
  rate limited    0
```

The script paces its virtual users to the configured limit. Every user
authenticates as the same client, and the limit is per client, so an unpaced test
would measure the rate limiter rather than the search: at 10 users and one
request per second each, three quarters of the requests come back 429.

To find the real ceiling, raise the limit and turn the cache off:

```
  20 virtual users, cache disabled, limit raised
  throughput     42.5 requests/second sustained
  p50           397 ms
  p95           716 ms
  errors          0   (every request answered 200)
```

The bottleneck is the single CPU-only embedding container, not the API or the
database: a cached search answers in 0.4 ms and a database query takes 9.5 ms.
Scaling the embedding service is what moves that number, and the Terraform
autoscaling policy for it is written accordingly.

### Security scan — Trivy

Runs in Docker, so nothing has to be installed:

```bash
./scripts/security_scan.sh              # repository and images
./scripts/security_scan.sh iac          # Terraform and Dockerfiles only
./scripts/security_scan.sh --severity CRITICAL
```

It covers the ground the language linters cannot. ruff, mypy and the .NET
analysers all read source; none of them knows that a pinned dependency has a CVE,
that a credential was committed, or that a security group is open.

| Pass | Finds |
| --- | --- |
| `vuln` | CVEs in Python wheels, NuGet packages and the OS packages inside the images |
| `secret` | Credentials committed by accident. The CI Terraform guard covers four specific patterns; this is the general case |
| `misconfig` | Terraform, Dockerfile and Compose misconfiguration — the tfsec ruleset |

**Where it runs in the pipeline.** Three gates, same tool and same
[`.trivyignore`](.trivyignore) as the local script, so a local run and a CI run
never disagree:

| Where | Scans | On a finding |
| --- | --- | --- |
| `ci.yml` → `security` | Dependencies, secrets, IaC | Fails the build, and uploads SARIF to the Security tab so the finding is navigable rather than buried in a log |
| `ci.yml` → `integration` | The three images it already built | Fails the pull request — the early warning |
| `cd.yml` → `images` | Each image **before** it is pushed | Blocks the push. This is the real gate |

The delivery order is **build → scan → push**, not build → push → scan. ECR has
`scan_on_push` enabled in Terraform and that is a useful backstop, but it reports
*after* the image is in the registry: by then it is deployable and the finding
lives in a console somebody has to remember to open. Scanning the local image
first means a vulnerable image never reaches ECR at all. The build runs twice; the
second call is a complete cache hit and is what produces the provenance and SBOM
attestations, which only exist on a registry push.

Image scans pass `--ignore-unfixed`. A CVE with no published fix is not
actionable at build time, and blocking a release nobody can unblock trains people
to bypass the gate.

**What it found on its first run, and what was done about it.** Eleven items, and
the split is the point:

- **One real defect, fixed.** The VPC endpoint security group allowed egress to
  `0.0.0.0/0` for "return traffic". Security groups are stateful, so replies need
  no egress rule at all; it is now confined to the VPC CIDR.
- **One real CVE, fixed.** `CVE-2026-53615` across nine `util-linux` packages in
  both Python images. Pulling a fresh `python:3.12-slim` did **not** clear it —
  upstream had not rebuilt. Waiting for a base image to catch up is not a plan,
  so both Dockerfiles now `apt-get upgrade` at build time. All three images scan
  clean.
- **Nine design decisions, recorded.** Public load balancer, public subnets
  assigning public IPs, mutable dev image tags, open task egress. Each is in
  [`.trivyignore`](.trivyignore) with a reason and a review date, because an
  ignore without a justification is a finding somebody forgot rather than one
  anybody decided about. The open task egress is flagged there as genuine
  hardening still owed, not a false positive.

### Code quality — SonarQube

Local only, and in its own compose file so it never starts with the platform:

```bash
./scripts/sonar_scan.sh          # start the server, run coverage, analyse
./scripts/sonar_scan.sh --stop   # it holds 2 GB; stop it when finished
```

ruff, `mypy --strict` and the .NET analysers already gate the build and are
better than Sonar at their own languages. Sonar earns its place on three things
they cannot do: duplication across the whole repository including across
languages, cognitive complexity per function against a threshold, and one quality
gate over all three languages instead of three separate verdicts.

Current state — **quality gate: OK**:

| Metric | Value |
| --- | --- |
| Lines of code | 2 590 |
| Bugs | 0 |
| Vulnerabilities | 0 |
| Duplication | 0.0% |
| Technical debt | 53 minutes |
| Reliability / Security / Maintainability | A / A / A |
| Code smells | 7 |
| Security hotspots | 3 |

The seven smells are honest ones and are listed here rather than hidden: two
functions over the cognitive-complexity threshold (`build_augmented_text` at 26,
`clean` at 16, both against a limit of 15), a literal repeated four times, a
redundant exception class, two field-naming complaints and one method that always
returns the same value. None is a defect; all are worth a look. The three
hotspots are `Math.random` in the k6 load test and two `http://` defaults for
service-to-service calls inside the Docker network, none of which is exposed.

---

## 16. Technology choices

Beyond the stack the specification fixes:

| Choice | Alternative considered | Why |
| --- | --- | --- |
| **Minimal APIs** | Controllers | Six read endpoints. Typed results state every outcome in the signature and generate the OpenAPI document from it; route groups apply authorization and rate limiting once per group, so a new endpoint cannot be added without them. Controllers earn their place on a large, convention-heavy surface |
| **BAAI/bge-base-en-v1.5** | `nomic-embed-text-v1.5` | The Nomic model does not load in TEI 1.7 at all. BGE gives 768 dimensions, strong retrieval quality, and needs no `trust_remote_code` |
| **Text Embeddings Inference** | sentence-transformers in a custom container | A purpose-built server: dynamic batching, its own Prometheus metrics, a health endpoint, and a 936 MB image instead of a PyTorch one |
| **Flyway** | Alembic | See [Migrations](#migrations-flyway-and-why) |
| **HNSW** | IVFFlat | No training step, and recall holds as rows are added |
| **asyncpg** | SQLAlchemy async | The MCP server runs six explicit statements. An ORM would add a layer over SQL that is already the clearest expression of the intent |
| **pg_trgm** | RapidFuzz in Python | The database already indexes it. Fuzzy matching in the application would mean fetching 3 200 titles per lookup |
| **`IMemoryCache` decorator** | `HybridCache`, output caching | One process, one cache. The decorator wraps the whole use case, so the service it wraps has no cache code and is tested without one |
| **Fixed-window rate limiting** | Sliding window | The requirement is a count per minute. A fixed window expresses exactly that and costs one counter per client |
| **structlog** | The standard library alone | JSON with a trace id on every line, including lines from uvicorn, httpx and the MCP library |
| **Two stores: Secrets Manager for secrets, Parameter Store for config** | One store for both | A password wants rotation, version labels and a resource policy; a domain name wants none of those and should not cost $0.40 a month. Splitting them puts each value where its lifecycle is served. Neither store is read into Terraform state either way — that property comes from the access pattern, not the store |
| **Secrets written out of band by a script** | `random_password` in Terraform, or a `secret_version` resource | Both write the generated value into the state file. Generating outside Terraform is the only way the state can be free of secrets, and it is asserted in CI rather than left to review |

---

## 17. Known limitations and future work

Honest list, in the order I would fix them.

### Search quality

- **No reranking.** A cross-encoder over the top 50 would measurably improve
  ordering. It costs a second model and roughly 50 ms.
- **No keyword channel.** A rare proper noun the embedding model has not seen is
  found only by luck. PostgreSQL full-text search fused with the vector score
  through reciprocal rank fusion would fix it, and needs no new service.
- **Filters are exact matches.** `genre=action` does not match `Action`, and
  there is no "any of these genres". The MCP tool signature is what the
  specification fixes; widening it is a compatible change.
- **`Unknown` is a genre.** 275 films carry it. `list_genres` returns it because
  it is genuinely a value in the column, but it is a sentinel wearing a genre's
  clothes.

### Data

- **The dataset ends in 2011** and is small. Nothing here has been tested at a
  million rows, where the HNSW build time and `ef_search` tuning start to matter.
- **The Rotten Tomatoes regression is global.** A per-genre fit would be better,
  and a residual would let the pipeline say how confident each filled value is.
- **`imputed_fields` is reported but never enforced.** Nothing stops a caller
  filtering on `min_imdb_rating` and receiving rows whose rating was imputed. An
  `exclude_imputed` parameter would.

### API and platform

- **The cache is per instance.** Two API tasks keep two copies. Redis or
  `HybridCache` with a distributed backing would fix it, at the cost of a
  dependency.
- **The rate limit is per instance too.** Three tasks means an effective 180
  requests a minute per client. A distributed limiter is the real answer.
- **The signing key is symmetric.** Correct for one service that both issues and
  validates its own tokens. A second service that had to validate without being
  able to mint would need an asymmetric key and a published JWKS.
- **Nothing rotates on a schedule.** The secrets are in Secrets Manager, so
  scheduled rotation is available, but no rotation Lambda is attached.
  `bootstrap_parameters.sh --rotate` is a manual act followed by a forced ECS
  deployment. RDS-managed rotation would automate the database password, and is
  the obvious next step now that the store supports it.
- **Tokens cannot be revoked** before they expire. The one hour lifetime is the
  only bound.
- **The embedding service is the bottleneck**, at 42.5 requests a second on CPU.
  A GPU instance or a smaller model moves it; so does caching query embeddings,
  which is the cheapest of the three.
- **`docker compose up` re-runs the pipeline.** It is idempotent, so the cost is
  about a second, but the dependency is on completion rather than on need.

### Operations

- **Terraform state lives in the same AWS account as the infrastructure it
  describes.** This is the largest structural gap, and it has its own section
  below: [Hardening the Terraform state](#hardening-the-terraform-state).
- **`terraform apply` has not been run.** A real `terraform plan` has: 94
  resources to add against a live account, with the state backend, both stores
  and the credentials all working, and all four secret values verified absent
  from the plan JSON. Everything up to the apply is proven; the apply itself is a
  deliberate, separate decision.
- **Embedding Atlas is local only.** It is a development tool, and the AWS
  deployment leaves it out on purpose.
- **No blue/green deployment.** ECS rolling updates with a circuit breaker and
  automatic rollback are configured; CodeDeploy blue/green would be better for a
  service with a strict error budget.
- **No backup restore drill.** Backups are configured. Nobody has proven a
  restore, which means nobody knows the restore works.
- **`dotnet test` does not work**, for the SDK reason described above. Tests run
  through `dotnet run`. It is a rough edge in the tooling rather than in the code,
  and CI runs the working command.

---

## Hardening the Terraform state

This platform is a demonstration, and it runs in a single AWS account. That is a
reasonable choice for what it is, and it carries one structural risk worth
writing down rather than discovering later.

### The risk

The state bucket sits in the **same account** as the infrastructure it describes.
Three consequences follow:

1. **A compromise takes both.** An attacker with account administrator rights
   gets the running platform *and* the record of how it was built. There is no
   second place to recover the truth from.
2. **An accidental deletion takes both.** A closed account, a mistaken
   `aws s3 rb`, or a broad lifecycle rule removes the state along with the
   resources it tracks. What is left is orphaned infrastructure nobody can
   `terraform destroy`.
3. **Everyone who can administer the account can read the state.** The state no
   longer holds secrets — those moved to Secrets Manager — but it does hold every
   endpoint, ARN and security group rule, which is a useful map for anybody who
   should not have one.

Point 3 is much smaller than it was. Before the secrets work, the state held the
database password, the token signing key and both client secrets.

### What the mature pattern looks like

A dedicated **management account** owns nothing but the state and the identities
that deploy:

```
                     ┌──────────────────────────────────┐
                     │  management account              │
                     │    S3 state bucket, versioned,   │
                     │      encrypted with a CMK        │
                     │    the GitHub OIDC provider      │
                     │    CloudTrail for the org        │
                     └───────────────┬──────────────────┘
                     assume role     │      assume role
             ┌───────────────────────┴──────────────────────┐
             ▼                                              ▼
   ┌──────────────────────┐                    ┌──────────────────────┐
   │  dev account         │                    │  prod account        │
   │    VPC, ECS, RDS     │                    │    VPC, ECS, RDS     │
   └──────────────────────┘                    └──────────────────────┘
```

Compromising a workload account then costs you that environment. It does not cost
you the state, the deployment identity, or the other environment.

### What it would take

Roughly a day, and it is not only Terraform:

| Step | Work |
| --- | --- |
| 1 | Create an AWS Organization and two member accounts, `dev` and `prod` |
| 2 | Move the state bucket and lock table into the management account |
| 3 | Encrypt the bucket with a customer managed KMS key, and write a key policy that lets the workload accounts' deploy roles decrypt |
| 4 | Add a bucket policy granting those roles `s3:GetObject`, `s3:PutObject` and `s3:DeleteObject` on their own key prefix only |
| 5 | Add `assume_role { role_arn = ... }` to each environment's `backend "s3"` block, so Terraform reads state as the management account and creates resources as the workload account |
| 6 | Move the GitHub OIDC provider to the management account and re-point `github_subject_patterns` |
| 7 | Turn on organization-wide CloudTrail, and a Service Control Policy that denies deleting the state bucket |

### A cheaper intermediate step

If a second account is more than this project warrants, two changes give most of
the protection against **accidental** loss, though none against compromise:

```bash
# 1. Replicate the state to a second region, so one regional failure or one
#    mistaken deletion is survivable.
aws s3api put-bucket-replication --bucket <state-bucket> --replication-configuration file://replication.json

# 2. Require MFA to delete an object version. Run as the account root, which is
#    the only identity permitted to set this.
aws s3api put-bucket-versioning --bucket <state-bucket> \
  --versioning-configuration Status=Enabled,MFADelete=Enabled \
  --mfa "arn:aws:iam::<account>:mfa/root-account-mfa-device <code>"
```

Versioning is already on, which means an overwritten state can be rolled back
today. Neither of these defends against an attacker with account administrator
rights; only account separation does that.

### When to do the full thing

Any one of these is the trigger:

- Anything production-critical runs on this platform.
- A second person can run `terraform apply`.
- An auditor asks who can read infrastructure state.
- A second environment or a second team appears.

Until then, the single-account setup is a considered trade rather than an
oversight, and this section is the record of that.

### A note on the two files with similar names

They are different things and only one belongs in the repository:

| File | In git? | What it is |
| --- | --- | --- |
| `.terraform.lock.hcl` | **yes, deliberately** | The provider dependency lock. It pins `hashicorp/aws` to one version and its checksums, so CI and every engineer resolve the same provider |
| `terraform.tfstate` | **never** | The state itself. It lives in S3, and `.gitignore` refuses it |
| `*.tfplan` | never | A saved plan. It holds resource detail and is regenerated on demand |

---

## Repository layout

```
.
├── README.md                     ← you are here
├── ECS_EKS_CHOICE.md             orchestrator decision record
├── docker-compose.yml            the whole platform, one command
├── openapi.json                  exported OpenAPI 3.1 document
├── .env.example                  every setting, with its default
│
├── pipeline/                     Part 1 — clean, impute, augment, embed, load
│   ├── src/pipeline/{cleaning,imputation,augmentation,embedding,loader}.py
│   ├── src/main.py
│   └── tests/                    85 tests
│
├── database/                     Part 2
│   ├── migrations/{V1__initial_schema.sql,V2__indexes.sql}
│   └── queries/hybrid_search.sql the documented hybrid query
│
├── mcp-server/                   Part 3 — FastMCP
│   ├── src/server/{main,tools,models,db,embeddings,context,telemetry}.py
│   ├── src/config.py
│   └── tests/                    73 tests
│
├── api/                          Part 4 — .NET 10
│   ├── src/MovieSearch.Api/            endpoints, middleware, DI
│   ├── src/MovieSearch.Application/    use cases
│   ├── src/MovieSearch.Domain/         entities, value objects, ports
│   ├── src/MovieSearch.Infrastructure/ MCP client, cache, tokens
│   └── tests/MovieSearch.Tests/        107 tests
│
├── embedding-atlas/              Part 5 — the visualisation container
├── scripts/                      bootstrap parameters, export, smoke test, load test
├── monitoring/                   Prometheus config, Grafana dashboard
├── terraform/                    Part 6 — modules and environments
└── .github/workflows/            ci.yml, cd.yml, destroy.yml
```
