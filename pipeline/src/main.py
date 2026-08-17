"""Entry point for the movie data pipeline.

Run it inside Docker Compose:

    docker compose run --rm pipeline

Run it directly, with the environment already set:

    PYTHONPATH=src python src/main.py

The run is idempotent. A second run with an unchanged dataset makes no call to
the embedding service and writes no row.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime

import pandas as pd

from pipeline import __version__
from pipeline.augmentation import augment
from pipeline.cleaning import clean
from pipeline.config import Settings, load_settings
from pipeline.dataset import load_movies
from pipeline.embedding import EmbeddingClient, EmbeddingError
from pipeline.imputation import impute
from pipeline.loader import MovieLoader, select_rows_needing_embedding, vector_literal
from pipeline.logging import configure_logging, get_logger
from pipeline.report import RunReport

logger = get_logger("pipeline.main")

EXIT_OK = 0
EXIT_FAILED = 1


def run(settings: Settings) -> RunReport:
    """Execute every stage in order and return the run report."""
    report = RunReport(pipeline_version=settings.pipeline_version)

    # --- 1. Source ----------------------------------------------------------
    raw = load_movies(settings.dataset_cache_path)
    report.source_records = len(raw)

    # --- 2. Clean -----------------------------------------------------------
    cleaned, report.cleaning = clean(raw, max_release_year=settings.pipeline_max_release_year)

    # --- 3. Impute ----------------------------------------------------------
    imputed, report.imputation = impute(cleaned)

    # --- 4. Augment ---------------------------------------------------------
    augmented, report.augmentation = augment(imputed)
    augmented["pipeline_version"] = settings.pipeline_version

    # --- 5. Database state --------------------------------------------------
    loader = MovieLoader(settings.postgres_dsn)
    loader.wait_until_ready()
    loader.verify_schema(settings.embedding_dim)
    existing = loader.fetch_existing()

    # --- 6. Embed only what changed -----------------------------------------
    with EmbeddingClient(
        settings.embeddings_url,
        dimension=settings.embedding_dim,
        batch_size=settings.pipeline_batch_size,
        doc_prefix=settings.embedding_doc_prefix,
        query_prefix=settings.embedding_query_prefix,
        timeout=settings.embedding_timeout_seconds,
    ) as embedder:
        embedder.wait_until_ready()
        embedder.prepare()
        model_id = embedder.model_id

        needs_embedding = select_rows_needing_embedding(
            augmented,
            existing,
            embedding_model=model_id,
            force=settings.pipeline_force_reembed,
        )
        targets = augmented.loc[needs_embedding]
        logger.info(
            "embedding.plan",
            total_rows=len(augmented),
            to_embed=int(needs_embedding.sum()),
            reused=len(augmented) - int(needs_embedding.sum()),
            force=settings.pipeline_force_reembed,
        )

        vectors: list[list[float] | None] = []
        if not targets.empty:
            vectors = embedder.embed_documents(targets["augmented_text"].tolist(), report.embedding)
        else:
            report.embedding.model_id = model_id
            report.embedding.dimension = settings.embedding_dim
            report.embedding.batch_size = embedder.batch_size

    report.embedding.texts_reused = len(augmented) - len(targets)

    # A row that keeps its stored vector sends NULL, and the upsert resolves that
    # with COALESCE(EXCLUDED.embedding, movies.embedding).
    embedding_column = pd.Series([None] * len(augmented), index=augmented.index, dtype="object")
    for position, (index, _) in enumerate(targets.iterrows()):
        vector = vectors[position] if position < len(vectors) else None
        if vector is not None:
            embedding_column.at[index] = vector_literal(vector)
    augmented["embedding"] = embedding_column
    augmented["embedding_model"] = model_id

    # A brand new row without a vector would be invisible to search, so it is
    # held back rather than written half-formed.
    unembeddable = augmented["embedding"].isna() & ~augmented["source_key"].isin(existing)
    if bool(unembeddable.any()):
        logger.error(
            "load.rows_skipped",
            count=int(unembeddable.sum()),
            reason="new row whose text could not be embedded",
        )
        augmented = augmented.loc[~unembeddable]

    # --- 7. Load -------------------------------------------------------------
    loader.upsert(augmented, report.load)

    report.finished_at = datetime.now(UTC).isoformat()
    return report


def main() -> int:
    settings = load_settings()
    log_path = configure_logging(settings.pipeline_log_level, settings.pipeline_log_dir)
    logger.info(
        "pipeline.started",
        version=settings.pipeline_version,
        code_version=__version__,
        log_file=str(log_path),
        embeddings_url=settings.embeddings_url,
        postgres_host=settings.postgres_host,
        batch_size=settings.pipeline_batch_size,
    )

    try:
        report = run(settings)
    except (EmbeddingError, RuntimeError, ValueError) as exc:
        logger.error("pipeline.failed", error=str(exc), exc_info=True)
        print(f"\nPIPELINE FAILED: {exc}\n", file=sys.stderr)
        return EXIT_FAILED

    report_path = report.write_json(settings.pipeline_report_dir)
    summary = report.render_text()
    print(summary)
    print(f"\nreport written to {report_path}")
    # The file sink is best effort — see configure_logging. Claiming a log was
    # written when the directory was unwritable sends the next person looking
    # for a file that is not there.
    if log_path.exists():
        print(f"log written to    {log_path}\n")
    else:
        print(f"log file unavailable ({log_path}); output above is the log\n")
    logger.info(
        "pipeline.finished",
        inserted=report.load.inserted,
        updated=report.load.updated,
        unchanged=report.load.unchanged,
        report_file=str(report_path),
    )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
