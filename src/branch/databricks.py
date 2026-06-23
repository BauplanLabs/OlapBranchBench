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
    """Open a Databricks SQL warehouse connection from the DATABRICKS_* environment."""
    from databricks import sql

    connection = sql.connect(
        server_hostname=os.getenv("DATABRICKS_SERVER_HOSTNAME"),
        http_path=os.getenv("DATABRICKS_HTTP_PATH"),
        access_token=os.getenv("DATABRICKS_TOKEN"),
    )
    # The connector returns its concrete Connection; expose it via the Protocol
    return cast(Connection, connection)


def split_namespace(qualified: str) -> tuple[str, str]:
    """Split a catalog.schema source into its two validated parts.

    Databricks clones per table, so the source is a schema (catalog.schema) rather than a
    whole database like Snowflake; we need both parts to qualify the source tables and the
    new branch schema."""
    parts = qualified.split(".")
    if len(parts) != 2:
        raise ValueError(f"expected a catalog.schema source, got: {qualified}")
    return ident(parts[0]), ident(parts[1])


def list_tables(cursor: Cursor, catalog: str, schema: str) -> list[str]:
    """List the table names in a schema (SHOW TABLES returns namespace, tableName, isTemporary)."""
    cursor.execute(f"SHOW TABLES IN {catalog}.{schema}")
    return [ident(str(row[1])) for row in cursor.fetchall()]


def assert_tables_cloned(connection: Connection, branch_name: str, base_branch: str) -> None:
    """Raise if the branch schema is missing any table from the source schema."""
    catalog, schema = split_namespace(base_branch)
    cursor = connection.cursor()
    source = set(list_tables(cursor, catalog, schema))
    cloned = set(list_tables(cursor, catalog, ident(branch_name)))
    missing = source - cloned
    if missing:
        formatted = ", ".join(sorted(missing))
        raise RuntimeError(
            f"branch {catalog}.{branch_name} is missing {len(missing)} tables from {base_branch}: {formatted}"
        )


def create_branches(
    config: BranchConfig | None = None,
    results_path: str | Path = "results/branching.parquet",
) -> pl.DataFrame:
    """Branch-equivalent benchmark on Databricks: a branch is a schema of SHALLOW CLONE tables."""

    config = config or BranchConfig()
    source_catalog, source_schema = split_namespace(config.base_branch)

    # Enumerate the source tables once, outside the measured region
    enumeration = connect()
    tables = list_tables(enumeration.cursor(), source_catalog, source_schema)
    enumeration.close()
    if not tables:
        raise RuntimeError(f"no tables found in {config.base_branch}")

    def client_factory() -> Connection:
        """Open one connection per worker thread, warmed up so the warehouse resume is not measured."""
        connection = connect()
        warmup = connection.cursor()
        warmup.execute("SELECT 1")
        warmup.fetchall()
        return connection

    def build_branch_name(exp_id: str, branch_id: str) -> str:
        """Build a unique uppercase schema name from the experiment and branch ids."""
        return f"BRANCH_TEST_{exp_id}{branch_id}".replace("-", "").upper()

    def create_branch(connection: Connection, branch_name: str, base_branch: str) -> str:
        """Create a branch schema, shallow-clone every source table into it, return its catalog.schema."""
        catalog, schema = split_namespace(base_branch)
        cursor = connection.cursor()
        cursor.execute(f"CREATE SCHEMA {catalog}.{ident(branch_name)}")
        for table in tables:
            cursor.execute(
                f"CREATE TABLE {catalog}.{ident(branch_name)}.{table} SHALLOW CLONE {catalog}.{schema}.{table}"
            )
        return f"{catalog}.{branch_name}"

    def delete_branch(connection: Connection, branch_name: str) -> None:
        """Drop the branch schema and all its cloned tables."""
        connection.cursor().execute(f"DROP SCHEMA {source_catalog}.{ident(branch_name)} CASCADE")

    verify_branch = assert_tables_cloned if config.verify_clone else None

    return run_branch_experiment(
        backend="databricks",
        config=config,
        client_factory=client_factory,
        build_branch_name=build_branch_name,
        create_branch=create_branch,
        delete_branch=delete_branch,
        results_path=results_path,
        close_client=lambda connection: connection.close(),
        verify_branch=verify_branch,
    )
