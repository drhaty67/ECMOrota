from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import streamlit as st


class AuthenticationError(RuntimeError):
    pass


@dataclass(frozen=True)
class AuthConfig:
    enabled: bool
    url: str = ""
    anon_key: str = ""


def auth_config(secrets: Any) -> AuthConfig:
    try:
        supabase = secrets.get("supabase", {})
        auth = secrets.get("auth", {})
    except FileNotFoundError:
        return AuthConfig(enabled=False)
    enabled = bool(auth.get("enabled", bool(supabase.get("url"))))
    return AuthConfig(
        enabled=enabled,
        url=supabase.get("url", ""),
        anon_key=supabase.get("anon_key", ""),
    )


class AuthService:
    def __init__(self, config: AuthConfig) -> None:
        if not config.url or not config.anon_key:
            raise AuthenticationError(
                "Authentication is enabled but the Supabase URL or anon key is missing."
            )
        try:
            from supabase import create_client
        except ImportError as exc:
            raise AuthenticationError("The Supabase Python dependency is not installed.") from exc
        self.client = create_client(config.url, config.anon_key)

    def sign_in(self, email: str, password: str):
        try:
            response = self.client.auth.sign_in_with_password(
                {"email": email.strip(), "password": password}
            )
            if not response.session or not response.user:
                raise AuthenticationError("Supabase did not return a valid session.")
            return response
        except AuthenticationError:
            raise
        except Exception as exc:
            raise AuthenticationError("Sign-in failed. Check the email and password.") from exc

    def restore(self, access_token: str, refresh_token: str):
        try:
            response = self.client.auth.set_session(access_token, refresh_token)
            if not response.session or not response.user:
                raise AuthenticationError("Your session has expired.")
            return response
        except AuthenticationError:
            raise
        except Exception as exc:
            raise AuthenticationError("Your session has expired. Please sign in again.") from exc

    def is_admin(self, user_id: str) -> bool:
        try:
            response = (
                self.client.table("admin_users")
                .select("user_id")
                .eq("user_id", user_id)
                .eq("active", True)
                .limit(1)
                .execute()
            )
            return bool(response.data)
        except Exception as exc:
            raise AuthenticationError(
                "Could not verify administrator access. Ensure the updated schema is installed."
            ) from exc

    def sign_out(self) -> None:
        try:
            self.client.auth.sign_out()
        except Exception:
            pass


def _clear_session() -> None:
    for key in ("auth_access_token", "auth_refresh_token", "auth_user"):
        st.session_state.pop(key, None)
    st.session_state.pop("rota_state", None)


def require_administrator(config: AuthConfig):
    """Render a login gate and return the authenticated administrator."""
    if not config.enabled:
        return None, None
    try:
        service = AuthService(config)
    except AuthenticationError as exc:
        st.error(str(exc)); st.stop()

    access = st.session_state.get("auth_access_token")
    refresh = st.session_state.get("auth_refresh_token")
    if access and refresh:
        try:
            response = service.restore(access, refresh)
            if not service.is_admin(response.user.id):
                _clear_session()
                st.error("This account is not an active rota administrator.")
                st.stop()
            st.session_state.auth_access_token = response.session.access_token
            st.session_state.auth_refresh_token = response.session.refresh_token
            st.session_state.auth_user = {"id": response.user.id, "email": response.user.email}
            return service, st.session_state.auth_user
        except AuthenticationError:
            _clear_session()

    st.title("Administrator sign in")
    st.caption("Sign in with an approved Supabase administrator account to access the rota.")
    with st.form("administrator_login"):
        email = st.text_input("Email address")
        password = st.text_input("Password", type="password")
        submit = st.form_submit_button("Sign in", type="primary", use_container_width=True)
    if submit:
        if not email.strip() or not password:
            st.error("Enter both an email address and password.")
        else:
            try:
                response = service.sign_in(email, password)
                if not service.is_admin(response.user.id):
                    service.sign_out()
                    st.error("This account is valid but is not an active rota administrator.")
                else:
                    st.session_state.auth_access_token = response.session.access_token
                    st.session_state.auth_refresh_token = response.session.refresh_token
                    st.session_state.auth_user = {"id": response.user.id, "email": response.user.email}
                    st.rerun()
            except AuthenticationError as exc:
                st.error(str(exc))
    st.stop()


def sign_out(service: AuthService | None) -> None:
    if service:
        service.sign_out()
    _clear_session()

