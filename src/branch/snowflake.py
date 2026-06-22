import os
from pathlib import Path
from typing import cast

import polars as pl
from dotenv import load_dotenv

from src.branch.experiment import BranchConfig, run_branch_experiment
from src.branch.sql import Connection, Cursor, ident

# Credentials come from .env file
load_dotenv()


def connect() -> Connection:
    """Open a Snowflake connection from the SF_* environment using key-pair auth."""
    import snowflake.connector

    # Key-pair auth: providing private_key_file makes the connector skip password/MFA
    connection = snowflake.connector.connect(
        account=os.getenv("SF_ACCOUNT"),
        user=os.getenv("SF_USER"),
        role=os.getenv("SF_ROLE"),
        warehouse=os.getenv("SF_WAREHOUSE"),
        private_key_file=os.getenv("SF_PRIVATE_KEY_FILE"),
    )
    # The connector returns its concrete SnowflakeConnection; expose it via the Protocol
    return cast(Connection, connection)


def create_branches(
    config: BranchConfig | None = None,
    results_path: str | Path = "results/branching.parquet",
) -> pl.DataFrame:
    """Branch-equivalent benchmark on Snowflake: zero-copy database CLONE as create, DROP as delete."""

    config = config or BranchConfig()

    def client_factory() -> Cursor:
        """Open one cursor per worker thread, warmed up so connection cost is not measured."""
        cursor = connect().cursor()
        # Warmup keeps cold-connection latency out of the first measurement
        cursor.execute("SELECT 1")
        cursor.fetchone()
        return cursor

    def build_branch_name(exp_id: str, branch_id: str) -> str:
        """Build a unique uppercase database name from the experiment and branch ids."""
        suffix = f"{exp_id}{branch_id}".replace("-", "").upper()
        return f"BRANCH_TEST_{suffix}"

    def create_branch(cursor: Cursor, branch_name: str, base_branch: str) -> str:
        """Zero-copy clone the source database into a new one; return its name to chain from."""
        cursor.execute(f"CREATE DATABASE {ident(branch_name)} CLONE {ident(base_branch)}")
        return branch_name

    def delete_branch(cursor: Cursor, branch_name: str) -> None:
        """Drop the cloned database."""
        cursor.execute(f"DROP DATABASE IF EXISTS {ident(branch_name)}")

    return run_branch_experiment(
        backend="snowflake",
        config=config,
        client_factory=client_factory,
        build_branch_name=build_branch_name,
        create_branch=create_branch,
        delete_branch=delete_branch,
        results_path=results_path,
    )
