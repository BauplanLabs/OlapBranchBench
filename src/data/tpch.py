from pathlib import Path

import duckdb

TPCH_TABLES = (
    "customer",
    "lineitem",
    "nation",
    "orders",
    "part",
    "partsupp",
    "region",
    "supplier",
)


def generate_tpch_parquet(scale_factor: float, out_dir: str | Path) -> Path:
    """Generate the TPC-H tables at the given scale factor with DuckDB, one parquet per table."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Set up duck db
    con = duckdb.connect()
    con.execute("INSTALL tpch")
    con.execute("LOAD tpch")

    # scale_factor is a controlled float from the CLI, not free-form SQL
    con.execute(f"CALL dbgen(sf = {scale_factor})")
    for table in TPCH_TABLES:
        con.execute(f"COPY {table} TO '{out / f'{table}.parquet'}' (FORMAT PARQUET)")
    con.close()

    return out
