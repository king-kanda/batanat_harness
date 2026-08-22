"""DSN handling for the runtime database bootstrap."""

from __future__ import annotations

import pytest

from batanat_api.core.db_bootstrap import split_dsn


@pytest.mark.parametrize(
    ("dsn", "expected"),
    [
        (
            "postgresql://postgres:password@localhost:5432/batanat",
            ("postgresql://postgres:password@localhost:5432/postgres", "batanat"),
        ),
        (
            "postgresql://u@host/db_name",
            ("postgresql://u@host/postgres", "db_name"),
        ),
        (
            "postgresql://u:p@host:5432/batanat?sslmode=require",
            ("postgresql://u:p@host:5432/postgres?sslmode=require", "batanat"),
        ),
    ],
)
def test_split_dsn_targets_the_maintenance_database(dsn: str, expected: tuple[str, str]) -> None:
    assert split_dsn(dsn) == expected


def test_split_dsn_rejects_a_dsn_without_a_database() -> None:
    with pytest.raises(ValueError, match="no database name"):
        split_dsn("postgresql://postgres:password@localhost:5432/")


def test_password_is_not_lost_or_mangled() -> None:
    maintenance, _ = split_dsn("postgresql://postgres:p%40ss@localhost:5432/batanat")
    assert maintenance == "postgresql://postgres:p%40ss@localhost:5432/postgres"
