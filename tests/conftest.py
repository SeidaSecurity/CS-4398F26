"""Shared test helpers for authentication (SRS 4.7).

`sign_in` gives a TestClient a valid session cookie WITHOUT calling POST /auth/login, so it adds
no audit record. Existing tests assert exact audit contents (checkpoint A of the auth plan).
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import auth
from app.database import Base, get_session
from app.main import app

TEST_PASSWORD = "Correct-Horse-9"


def add_user(session_factory, username: str, role: str, password: str = TEST_PASSWORD):
    with session_factory() as db:
        user = auth.create_user(db, username, password, role)
        db.commit()
        return user


def sign_in(test_client: TestClient, session_factory, username: str, role: str) -> None:
    """Create the user and attach a session cookie to the client (no audit side effect)."""
    with session_factory() as db:
        user = auth.find_user(db, username) or auth.create_user(db, username, TEST_PASSWORD, role)
        token = auth.start_session(db, user)
        db.commit()
    test_client.cookies.set(auth.SESSION_COOKIE, token)


@pytest.fixture
def api():
    """A TestClient on an in-memory database, signed in as nobody. Yields (client, factory)."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_session():
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as test_client:
        yield test_client, factory
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()
