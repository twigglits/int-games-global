"""Environment-driven configuration for the pipeline.

Every value comes from an environment variable. The pipeline holds no hardcoded
host, port, credential or file path.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration read from the process environment."""

    model_config = SettingsConfigDict(
        env_file=None,
        case_sensitive=False,
        extra="ignore",
    )

    # --- PostgreSQL ---------------------------------------------------------
    postgres_host: str = Field(default="postgres")
    postgres_port: int = Field(default=5432)
    postgres_user: str = Field(default="movies")
    postgres_password: str = Field(default="movies")
    postgres_db: str = Field(default="movies")

    # --- Embedding service --------------------------------------------------
    embeddings_url: str = Field(default="http://embeddings:80")
    embedding_model_id: str = Field(default="BAAI/bge-base-en-v1.5")
    embedding_dim: int = Field(default=768)
    embedding_query_prefix: str = Field(default="")
    embedding_doc_prefix: str = Field(default="")
    embedding_timeout_seconds: float = Field(default=120.0)

    # --- Pipeline behaviour -------------------------------------------------
    pipeline_version: str = Field(default="1.0.0")
    pipeline_batch_size: int = Field(default=32, ge=1, le=512)
    pipeline_log_level: str = Field(default="INFO")
    pipeline_force_reembed: bool = Field(default=False)
    # Last year the source dataset can legitimately contain. Anything later is a
    # two-digit-year rollover in the source. See pipeline.cleaning.clean.
    pipeline_max_release_year: int = Field(default=2011)

    # --- Output paths -------------------------------------------------------
    pipeline_log_dir: Path = Field(default=Path("/app/logs"))
    pipeline_report_dir: Path = Field(default=Path("/app/logs"))
    # Copy of the Vega movies dataset baked into the image at build time. It
    # keeps a pipeline run reproducible and offline. When the file is absent the
    # pipeline falls back to `vega_datasets.data.movies()`.
    dataset_cache_path: Path = Field(default=Path("/app/data/movies.json"))

    @field_validator("pipeline_log_level")
    @classmethod
    def _upper(cls, value: str) -> str:
        return value.upper()

    @property
    def postgres_dsn(self) -> str:
        """libpq connection string for psycopg."""
        dsn = PostgresDsn.build(
            scheme="postgresql",
            username=self.postgres_user,
            password=self.postgres_password,
            host=self.postgres_host,
            port=self.postgres_port,
            path=self.postgres_db,
        )
        return str(dsn)


def load_settings() -> Settings:
    """Build a :class:`Settings` instance from the environment."""
    return Settings()
