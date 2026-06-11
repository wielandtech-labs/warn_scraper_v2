"""User-management CLI commands (create-user, set-role, list-users, delete-user).

conftest's db_session_factory monkeypatches warn_v2.db.session._session_factory,
which session_scope() uses, so commands hit the in-memory SQLite DB directly.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from click.testing import CliRunner
from sqlalchemy import select

from warn_v2 import auth
from warn_v2.cli import main
from warn_v2.db.models import User, UserSession

PASSWORD = "correct-horse-battery"


@pytest.fixture()
def runner(db_session_factory):
    return CliRunner()


def _get_user(db_session_factory, email: str) -> User | None:
    with db_session_factory() as session:
        return session.scalar(select(User).where(User.email == email))


def test_create_user_prompts_and_hashes(runner, db_session_factory):
    result = runner.invoke(
        main,
        ["create-user", "--email", "A@Example.com", "--role", "paid"],
        input=f"{PASSWORD}\n{PASSWORD}\n",
    )
    assert result.exit_code == 0, result.output
    user = _get_user(db_session_factory, "a@example.com")  # lowercased
    assert user is not None
    assert user.role == "paid"
    assert user.password_hash != PASSWORD
    assert auth.verify_password(user.password_hash, PASSWORD)


def test_create_user_password_stdin(runner, db_session_factory):
    result = runner.invoke(
        main,
        ["create-user", "--email", "job@example.com", "--role", "admin", "--password-stdin"],
        input=f"{PASSWORD}\n",
    )
    assert result.exit_code == 0, result.output
    assert _get_user(db_session_factory, "job@example.com").role == "admin"


def test_create_user_rejects_short_password(runner, db_session_factory):
    result = runner.invoke(
        main,
        ["create-user", "--email", "x@example.com", "--password-stdin"],
        input="short\n",
    )
    assert result.exit_code == 1
    assert _get_user(db_session_factory, "x@example.com") is None


def test_create_user_duplicate_email(runner, db_session_factory):
    for _ in range(2):
        result = runner.invoke(
            main,
            ["create-user", "--email", "dup@example.com", "--password-stdin"],
            input=f"{PASSWORD}\n",
        )
    assert result.exit_code == 1
    assert "already exists" in result.output


def test_set_password_revokes_sessions(runner, db_session_factory):
    runner.invoke(
        main,
        ["create-user", "--email", "rot@example.com", "--password-stdin"],
        input=f"{PASSWORD}\n",
    )
    with db_session_factory() as session:
        user = session.scalar(select(User).where(User.email == "rot@example.com"))
        old_hash = user.password_hash
        session.add(
            UserSession(
                token_sha256="y" * 64,
                user_id=user.id,
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
        )
        session.commit()

    result = runner.invoke(
        main,
        ["set-password", "--email", "rot@example.com", "--password-stdin"],
        input="new-password-much-longer\n",
    )
    assert result.exit_code == 0, result.output
    with db_session_factory() as session:
        user = session.scalar(select(User).where(User.email == "rot@example.com"))
        assert user.password_hash != old_hash
        assert auth.verify_password(user.password_hash, "new-password-much-longer")
        assert session.scalar(select(UserSession)) is None  # sessions revoked

    missing = runner.invoke(
        main,
        ["set-password", "--email", "ghost@example.com", "--password-stdin"],
        input="new-password-much-longer\n",
    )
    assert missing.exit_code == 1


def test_set_role(runner, db_session_factory):
    runner.invoke(
        main,
        ["create-user", "--email", "u@example.com", "--password-stdin"],
        input=f"{PASSWORD}\n",
    )
    result = runner.invoke(main, ["set-role", "--email", "u@example.com", "--role", "paid"])
    assert result.exit_code == 0, result.output
    assert _get_user(db_session_factory, "u@example.com").role == "paid"

    missing = runner.invoke(main, ["set-role", "--email", "ghost@example.com", "--role", "paid"])
    assert missing.exit_code == 1


def test_list_users(runner, db_session_factory):
    for email in ("b@example.com", "a@example.com"):
        runner.invoke(
            main,
            ["create-user", "--email", email, "--password-stdin"],
            input=f"{PASSWORD}\n",
        )
    result = runner.invoke(main, ["list-users"])
    assert result.exit_code == 0
    lines = result.output.strip().splitlines()
    assert lines[0].startswith("a@example.com")  # ordered by email
    assert lines[1].startswith("b@example.com")


def test_delete_user_removes_sessions(runner, db_session_factory):
    runner.invoke(
        main,
        ["create-user", "--email", "gone@example.com", "--password-stdin"],
        input=f"{PASSWORD}\n",
    )
    with db_session_factory() as session:
        user = session.scalar(select(User).where(User.email == "gone@example.com"))
        session.add(
            UserSession(
                token_sha256="x" * 64,
                user_id=user.id,
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
        )
        session.commit()

    result = runner.invoke(main, ["delete-user", "--email", "gone@example.com"])
    assert result.exit_code == 0, result.output
    with db_session_factory() as session:
        assert session.scalar(select(User)) is None
        assert session.scalar(select(UserSession)) is None  # explicit cascade

    missing = runner.invoke(main, ["delete-user", "--email", "gone@example.com"])
    assert missing.exit_code == 1
