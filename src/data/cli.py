from pathlib import Path
from typing import Annotated

import typer

from src.data.tpch import generate_tpch_parquet

app = typer.Typer(help="Dataset generation for OlapBranchBench")


@app.command()
def tpch(
    scale_factor: Annotated[float, typer.Option("--sf", help="TPC-H scale factor")] = 1.0,
    out_dir: Annotated[Path | None, typer.Option(help="Output dir (default data/tpch_sf<sf>)")] = None,
) -> None:
    """Generate TPC-H parquet files with DuckDB, ready to upload to object storage."""
    target = out_dir or Path(f"data/tpch_sf{scale_factor:g}")
    out = generate_tpch_parquet(scale_factor, target)
    typer.echo(f"wrote TPC-H sf={scale_factor:g} parquet to {out}")
