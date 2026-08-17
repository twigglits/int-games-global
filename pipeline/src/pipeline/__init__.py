"""Data pipeline for the intelligent movie search platform.

The pipeline runs five stages in order:

1. ``dataset``      — read the raw Vega movies records.
2. ``cleaning``     — remove duplicates, normalize strings, parse dates, bound numbers.
3. ``imputation``   — fill missing values and record which values were filled.
4. ``augmentation`` — derive extra features and build the text that gets embedded.
5. ``embedding``    — call the embedding service in batches.
6. ``loader``       — upsert rows into pgvector.

Every stage is a pure function over a ``pandas.DataFrame`` plus a report object,
so each stage can be tested on its own.
"""

__version__ = "1.0.0"
