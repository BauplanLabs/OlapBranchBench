from pathlib import Path

import polars as pl


def append_results(df: pl.DataFrame, results_path: str | Path) -> pl.DataFrame:
    """Append the run rows to the cumulative parquet, creating it on first run."""
    path = Path(results_path)

    if path.exists():
        combined = pl.concat([pl.read_parquet(path), df], how="diagonal_relaxed")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        combined = df

    combined.write_parquet(path)

    return df
