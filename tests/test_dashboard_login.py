from pathlib import Path
from unittest.mock import Mock

import pytest
from pydantic import SecretStr
from streamlit.testing.v1 import AppTest

from app.config import settings
from app.services.passwords import hash_password


PASSWORD = "dashboard-test-password"
LOGIN_APP = """
import streamlit as st
from app.ui.operator_login import require_dashboard_operator
require_dashboard_operator()
st.success('Protected content')
"""


@pytest.fixture
def operator(monkeypatch):
    monkeypatch.setattr(settings, "operator_username", "operator")
    monkeypatch.setattr(settings, "operator_password_hash", SecretStr(hash_password(PASSWORD)))


def login(app, password=PASSWORD):
    app.text_input(key="operator_login_username").set_value("operator")
    app.text_input(key="operator_login_password").set_value(password)
    app.button[0].click().run()
    return app


def test_dashboard_does_not_query_database_before_login(operator, monkeypatch):
    session = Mock(side_effect=AssertionError("Unauthenticated database access"))
    monkeypatch.setattr("app.db.session.SessionLocal", session)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "dashboard.py")).run(timeout=15)
    assert not app.exception
    assert app.text_input(key="operator_login_password")
    assert len(app.tabs) == 0
    session.assert_not_called()


def test_invalid_login_keeps_protected_content_hidden(operator):
    app = login(AppTest.from_string(LOGIN_APP).run(), "incorrect")
    assert not app.exception
    assert len(app.error) == 1
    assert len(app.success) == 0
    assert app.text_input(key="operator_login_password").value == ""


def test_login_logout_and_password_clear(operator):
    app = login(AppTest.from_string(LOGIN_APP).run())
    assert not app.exception
    assert app.success[0].value == "Protected content"
    app.button(key="operator_logout").click().run()
    assert not app.exception
    assert len(app.success) == 0
    assert app.text_input(key="operator_login_password").value == ""


def test_expired_session_requires_fresh_login(operator):
    app = login(AppTest.from_string(LOGIN_APP).run())
    session = dict(app.session_state["operator_session"])
    session["expires_at"] = 0
    app.session_state["operator_session"] = session
    app.run()
    assert not app.exception
    assert len(app.success) == 0
    assert app.text_input(key="operator_login_password")


def test_changing_credentials_invalidates_dashboard_session(operator, monkeypatch):
    app = login(AppTest.from_string(LOGIN_APP).run())
    monkeypatch.setattr(settings, "operator_password_hash", SecretStr(hash_password("replacement-password")))
    app.run()
    assert not app.exception
    assert len(app.success) == 0
