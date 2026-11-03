import time

import streamlit as st

from app.config import settings
from app.services.operator_auth import auth_configured, credential_version, verify_operator


def _submit_login():
    username = st.session_state.get("operator_login_username", "")
    password = st.session_state.get("operator_login_password", "")
    st.session_state["operator_login_password"] = ""
    if verify_operator(username, password):
        st.session_state["operator_session"] = {
            "username": username, "version": credential_version(),
            "expires_at": time.time() + settings.operator_session_hours * 3600,
        }
        st.session_state.pop("operator_login_error", None)
    else:
        st.session_state["operator_login_error"] = "Invalid username or password."


def _logout():
    st.session_state.clear()


def require_dashboard_operator():
    """Stop before queries or approval controls unless this session logged in."""
    if not auth_configured():
        st.error("Operator login is not configured. Follow the authentication setup in README.md.")
        st.stop()
    session = st.session_state.get("operator_session")
    if session and (
        session.get("username") == settings.operator_username
        and session.get("version") == credential_version()
        and session.get("expires_at", 0) > time.time()
    ):
        st.sidebar.caption(f"Signed in as {session['username']}")
        st.sidebar.button("Log out", on_click=_logout, key="operator_logout")
        return session["username"]
    st.session_state.pop("operator_session", None)
    with st.form("operator_login"):
        st.subheader("Operator login")
        st.text_input("Username", key="operator_login_username", max_chars=64)
        st.text_input("Password", type="password", key="operator_login_password", max_chars=1024)
        st.form_submit_button("Log in", on_click=_submit_login)
    if st.session_state.get("operator_login_error"):
        st.error(st.session_state["operator_login_error"])
    st.stop()
