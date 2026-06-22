from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from src.branch.bauplan import create_branches as run_bauplan
from src.branch.databricks import create_branches as run_databricks
from src.branch.experiment import BranchConfig
from src.branch.snowflake import create_branches as run_snowflake


class Backend(StrEnum):
    bauplan = "bauplan"
    snowflake = "snowflake"
    databricks = "databricks"


BACKENDS: dict[Backend, Callable[..., object]] = {
    Backend.bauplan: run_bauplan,
    Backend.snowflake: run_snowflake,
    Backend.databricks: run_databricks,
}


def benchmark(
    backend: Annotated[Backend, typer.Argument(help="Backend to benchmark")],
    base_branch: Annotated[str, typer.Argument(help="Ref / database / catalog.schema to branch from")],
    n_branches: Annotated[int, typer.Option(help="Branches to create per run")] = 10,
    parallel: Annotated[bool, typer.Option(help="Parallel workers vs serial")] = True,
    n_workers: Annotated[int, typer.Option(help="Worker threads when parallel")] = 4,
    jitter_ms: Annotated[float, typer.Option(help="Max random pre-call jitter, parallel only")] = 0.0,
    chained: Annotated[
        bool, typer.Option(help="Chain branches: each created from the previous one (forces serial)")
    ] = False,
    results_path: Annotated[Path, typer.Option(help="Cumulative results parquet")] = Path("results/branching.parquet"),
) -> None:
    """Run the branch-creation benchmark on the chosen backend"""
    config = BranchConfig(
        n_branches=n_branches,
        # chaining is inherently sequential, so it overrides parallel
        parallel=parallel and not chained,
        n_workers=n_workers,
        jitter_ms=jitter_ms,
        base_branch=base_branch,
        chained=chained,
    )
    BACKENDS[backend](config=config, results_path=results_path)
    typer.echo(f"results appended to {results_path}")
