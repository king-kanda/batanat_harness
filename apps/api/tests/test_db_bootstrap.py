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


# --- config path resolution ----------------------------------------------------


def test_repo_root_survives_a_shallow_install(tmp_path, monkeypatch) -> None:
    """The bug that took every container down before it could log a reason.

    In the repo this module sits four levels below the root. In the image it is
    `/app/src/batanat_api/config.py` — two levels shallower — and the hardcoded
    `parents[4]` ran off the top of the filesystem, raising IndexError at import
    time. The image built fine and died on first run.
    """
    from batanat_api import config

    shallow = tmp_path / "app" / "src" / "batanat_api" / "config.py"
    shallow.parent.mkdir(parents=True)
    shallow.touch()

    monkeypatch.setattr(config, "__file__", str(shallow))
    root = config._repo_root()

    assert root.is_dir()
    # No marker anywhere above, so it falls back rather than raising.
    assert not (root / ".env").is_file()


def test_repo_root_finds_the_marker_when_there_is_one(tmp_path, monkeypatch) -> None:
    from batanat_api import config

    root = tmp_path / "project"
    nested = root / "apps" / "api" / "src" / "batanat_api"
    nested.mkdir(parents=True)
    (nested / "config.py").touch()
    (root / ".env").write_text("APP_ENV=local\n")

    monkeypatch.setattr(config, "__file__", str(nested / "config.py"))
    assert config._repo_root() == root


def test_repo_root_never_raises_however_shallow(tmp_path, monkeypatch) -> None:
    """Import-time crashes are the worst kind: nothing gets to report them."""
    from batanat_api import config

    for depth in range(0, 6):
        path = tmp_path.joinpath(*[f"d{i}" for i in range(depth)]) / "config.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        monkeypatch.setattr(config, "__file__", str(path))
        assert config._repo_root().is_dir(), depth
