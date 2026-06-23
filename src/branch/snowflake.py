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


def list_tables(cursor: Cursor, database: str) -> set[tuple[str, str]]:
    """Return the (schema, table) pairs of every base table in a Snowflake database."""
    cursor.execute(
        f"SELECT table_schema, table_name FROM {ident(database)}.INFORMATION_SCHEMA.TABLES "
        "WHERE table_type = 'BASE TABLE'"
    )
    return {(str(row[0]), str(row[1])) for row in cursor.fetchall()}


def assert_tables_cloned(cursor: Cursor, branch_name: str, base_branch: str) -> None:
    """Raise if the clone is missing any base table present in the source database."""
    missing = list_tables(cursor, base_branch) - list_tables(cursor, branch_name)
    if missing:
        formatted = ", ".join(f"{schema}.{table}" for schema, table in sorted(missing))
        raise RuntimeError(f"clone {branch_name} is missing {len(missing)} tables from {base_branch}: {formatted}")


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

    verify_branch = assert_tables_cloned if config.verify_clone else None

    return run_branch_experiment(
        backend="snowflake",
        config=config,
        client_factory=client_factory,
        build_branch_name=build_branch_name,
        create_branch=create_branch,
        delete_branch=delete_branch,
        results_path=results_path,
        verify_branch=verify_branch,
    )
