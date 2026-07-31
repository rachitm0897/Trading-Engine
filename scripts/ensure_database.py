#!/usr/bin/env python3
"""Create the PostgreSQL database from DATABASE_URL when it is missing."""

from __future__ import annotations

import os
import sys
import time
from typing import Callable, TypeVar

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.errors import DuplicateDatabase


NumberT = TypeVar("NumberT", int, float)


def get_positive_number(
    name: str,
    default: str,
    converter: Callable[[str], NumberT],
) -> NumberT:
    """Read a positive numeric environment variable."""

    raw_value = os.getenv(name, default)

    try:
        value = converter(raw_value)
    except ValueError as exc:
        raise RuntimeError(
            f"{name} must contain a valid number"
        ) from exc

    if value <= 0:
        raise RuntimeError(
            f"{name} must be greater than zero"
        )

    return value


def ensure_database() -> None:
    """Check whether the configured database exists and create it if needed."""

    database_url = os.getenv("DATABASE_URL", "").strip()

    if not database_url:
        raise RuntimeError("DATABASE_URL is required")

    connection_parameters = conninfo_to_dict(database_url)
    database_name = connection_parameters.get("dbname")

    if not database_name:
        raise RuntimeError(
            "DATABASE_URL must include a database name"
        )

    maintenance_database = os.getenv(
        "POSTGRES_MAINTENANCE_DB",
        "postgres",
    ).strip()

    if not maintenance_database:
        raise RuntimeError(
            "POSTGRES_MAINTENANCE_DB cannot be empty"
        )

    max_attempts = get_positive_number(
        "DATABASE_BOOTSTRAP_MAX_ATTEMPTS",
        "30",
        int,
    )

    retry_seconds = get_positive_number(
        "DATABASE_BOOTSTRAP_RETRY_SECONDS",
        "2",
        float,
    )

    # Connect to the maintenance database because we cannot connect to the
    # application database before that database exists.
    maintenance_parameters = dict(connection_parameters)
    maintenance_parameters["dbname"] = maintenance_database
    maintenance_parameters.setdefault("connect_timeout", "5")

    for attempt in range(1, max_attempts + 1):
        try:
            with psycopg.connect(
                **maintenance_parameters,
                autocommit=True,
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT 1
                        FROM pg_database
                        WHERE datname = %s
                        """,
                        (database_name,),
                    )

                    if cursor.fetchone():
                        print(
                            f"Database '{database_name}' already exists."
                        )
                        return

                    try:
                        cursor.execute(
                            sql.SQL("CREATE DATABASE {}").format(
                                sql.Identifier(database_name)
                            )
                        )
                    except DuplicateDatabase:
                        # Another Backend instance may have created the
                        # database after our SELECT query.
                        print(
                            f"Database '{database_name}' "
                            "was created concurrently."
                        )
                    else:
                        print(
                            f"Created database '{database_name}'."
                        )

                    return

        except psycopg.OperationalError as exc:
            if attempt == max_attempts:
                raise RuntimeError(
                    "Could not connect to PostgreSQL after "
                    f"{max_attempts} attempts"
                ) from exc

            print(
                "PostgreSQL is not ready "
                f"({attempt}/{max_attempts}); "
                f"retrying in {retry_seconds:g} seconds...",
                file=sys.stderr,
            )

            time.sleep(retry_seconds)


if __name__ == "__main__":
    ensure_database()