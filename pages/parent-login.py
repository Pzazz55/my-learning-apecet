"""Parent Login & Sign-Up page.

Sign-in and sign-up are two tabs of a single page so a new parent can
create an account without leaving the entry screen. Password reset (email
OTP) and Google OAuth are supported on the sign-in tab.
"""

from __future__ import annotations

import uuid
from typing import Any

import streamlit as st

from backend.services.auth_storage import (
    create_parent,
    create_student,
    get_parent_by_username,
    get_parent_by_email,
    get_parent_by_google_id,
    verify_parent_credentials,
    generate_otp,
    verify_otp,
    update_parent_password,
)
from backend.services.google_auth import (
    get_google_auth_url,
    generate_auth_state,
    handle_google_callback,
    is_google_configured,
    GoogleAuthError,
)
from backend.services.email_service import send_otp_email, is_email_configured, EmailServiceError
from backend.services import llm_backend
from backend.services.logging_config import get_logger
from middleware import is_parent_authenticated
from ui.components.theme import inject_parent_theme
from ui.components.appearance import render_appearance_toggle

logger = get_logger(__name__)

# Page configuration
st.set_page_config(page_title="Parent Login · Study Sprint", page_icon="🔐", layout="wide")

# Configuration used throughout the page
CONFIG = llm_backend.load_config()
DEFAULTS = CONFIG["defaults"]

# Theme
theme = render_appearance_toggle(default=DEFAULTS.get("appearance", "Dark"))
inject_parent_theme(theme)










def authenticate_parent(parent_data: dict[str, Any]) -> None:
    """Set parent authentication session."""
    st.session_state.parent_authenticated = True
    st.session_state.parent_data = parent_data
    # A fresh sign-in starts with no student selected, so the next page picks
    # one of *this* parent's children rather than a leftover id.
    st.session_state.current_student_id = None
    logger.info("Parent '%s' authenticated.", parent_data.get("username"))


def generate_student_id() -> str:
    """Generate a unique student ID."""
    return f"STU{uuid.uuid4().hex[:8].upper()}"


def render_child_fields(prefix: str, index: int, defaults: dict[str, Any] | None = None) -> dict[str, Any]:
    """Render one child's name field.

    ``prefix`` namespaces the widget keys so several children can be shown on
    one page without clashing. Returns the collected child values.
    """
    defaults = defaults or {}
    st.markdown(f"##### Child {index}")
    name_key = f"{prefix}_name_{index}"
    child_name = st.text_input("Student Name", value=defaults.get("student_name", ""), key=name_key)
    return {"student_name": child_name}


def validate_signup(form_data: dict[str, Any]) -> tuple[bool, str]:
    """Validate the sign-up form data, including one or more children."""
    children = form_data.get("children") or []
    if not children:
        return False, "Please add at least one child."
    for index, child in enumerate(children, start=1):
        if not (child.get("student_name") or "").strip():
            return False, f"Child {index}: student name is required."
    if not form_data.get("parent_name"):
        return False, "Parent name is required"
    if not form_data.get("parent_email"):
        return False, "Parent email is required"

    if form_data.get("auth_type") == "manual":
        if not form_data.get("parent_username"):
            return False, "Parent username is required"
        if not form_data.get("parent_password"):
            return False, "Parent password is required"
        if form_data.get("parent_password") != form_data.get("confirm_password"):
            return False, "Passwords do not match"
        if get_parent_by_username(form_data["parent_username"]):
            return False, "Username already exists"
        if get_parent_by_email(form_data["parent_email"]):
            return False, "Email already registered"

    return True, ""


# Handle Google OAuth callback -------------------------------------------------
if "code" in st.query_params and "state" in st.query_params:
    try:
        code = st.query_params["code"]
        state = st.query_params["state"]

        if st.session_state.get("oauth_state") != state:
            st.error("Invalid OAuth state. Please try again.")
            logger.warning("Google OAuth state mismatch.")
            st.stop()

        google_user = handle_google_callback(code, state)
        parent = get_parent_by_google_id(google_user["google_id"])
        if parent:
            authenticate_parent(parent)
            st.query_params.clear()
            st.switch_page("learning-home.py")
        else:
            # Unknown Google account: carry the data into the sign-up tab.
            st.session_state.google_user_data = google_user
            st.session_state.auth_type = "google"
            st.query_params.clear()
            st.rerun()

    except GoogleAuthError as error:
        logger.error("Google authentication failed: %s", error)
        st.error(f"Google authentication failed: {error}")
        st.stop()

# If already signed in there is no login/sign-up to show: go to the workspace.
if is_parent_authenticated():
    parent = st.session_state.get("parent_data") or {}
    st.info(f"Already signed in as {parent.get('username', 'parent')}. Redirecting…")
    if st.button("Go to Student Workspace", type="primary"):
        st.switch_page("learning-home.py")
    st.stop()

# Main page --------------------------------------------------------------------
st.markdown('<div class="brand">study<span>·</span>sprint / parent access</div>', unsafe_allow_html=True)
st.markdown("## Parent Access")
st.caption("Sign in to run exams and review your child's results, or create a new account.")

google_user_data = st.session_state.get("google_user_data")
# When arriving from a Google sign-up - or when the visitor clicks the
# "Register a new user" link - present the Sign Up tab first by placing it
# ahead of Sign In in the tab order.
if google_user_data or st.session_state.get("show_signup"):
    signup_tab, signin_tab = st.tabs(["Sign Up", "Sign In"])
else:
    signin_tab, signup_tab = st.tabs(["Sign In", "Sign Up"])

with signin_tab:
    if is_google_configured():
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            if st.button("🔑 Log in with Google", type="primary", use_container_width=True):
                state = generate_auth_state()
                st.session_state.oauth_state = state
                auth_url = get_google_auth_url(state)
                st.markdown(f'<meta http-equiv="refresh" content="0;url={auth_url}">', unsafe_allow_html=True)
        st.markdown("---")

    with st.form("parent_login"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign In", type="primary", use_container_width=True)

    if submitted:
        parent = verify_parent_credentials(username, password)
        if parent:
            authenticate_parent(parent)
            st.success("Login successful!")
            st.switch_page("learning-home.py")
        else:
            logger.warning("Failed login attempt for username '%s'.", username)
            st.error("Invalid username or password")

    # Link for brand-new users so registration is one click away.
    st.markdown("---")
    st.markdown("#### New here?")
    st.caption("Create a parent account to register one or more children and start running exams.")
    if st.button("🆕 Register a new user", use_container_width=True):
        st.session_state.show_signup = True
        st.rerun()

    # Password reset (email OTP)
    st.markdown("---")
    st.markdown("### Forgot Password?")
    reset_option = st.radio("Choose reset method:", ["Email OTP", "Cancel"], horizontal=True)

    if reset_option == "Email OTP":
        if not is_email_configured():
            st.warning("Email service is not configured. Please contact administrator.")
        else:
            email = st.text_input("Enter your registered email address")
            if st.button("Send OTP"):
                parent = get_parent_by_email(email)
                if not parent:
                    st.error("No account found with this email address.")
                elif parent.get("auth_type") == "google":
                    st.warning("Google-authenticated accounts cannot reset password via email. Please use Google login.")
                else:
                    try:
                        otp = generate_otp(parent["id"])
                        send_otp_email(email, otp)
                        st.session_state.reset_email = email
                        st.session_state.parent_id_reset = parent["id"]
                        logger.info("OTP sent for password reset to '%s'.", email)
                        st.success(f"OTP sent to {email}")
                    except EmailServiceError as error:
                        logger.error("Failed to send OTP: %s", error)
                        st.error(f"Failed to send OTP: {error}")

    if st.session_state.get("reset_email"):
        st.markdown("### Verify OTP")
        otp_input = st.text_input("Enter the OTP sent to your email", max_chars=6)
        if st.button("Verify OTP"):
            if verify_otp(st.session_state.parent_id_reset, otp_input):
                st.success("OTP verified! You can now set a new password.")
                st.session_state.otp_verified = True
            else:
                st.error("Invalid or expired OTP")

    if st.session_state.get("otp_verified"):
        st.markdown("### Set New Password")
        new_password = st.text_input("New Password", type="password")
        confirm_password = st.text_input("Confirm New Password", type="password")
        if st.button("Update Password"):
            if new_password != confirm_password:
                st.error("Passwords do not match")
            elif len(new_password) < 6:
                st.error("Password must be at least 6 characters")
            else:
                try:
                    update_parent_password(st.session_state.parent_id_reset, new_password)
                    logger.info("Password updated for parent id %s.", st.session_state.parent_id_reset)
                    st.success("Password updated successfully!")
                    st.session_state.reset_email = None
                    st.session_state.parent_id_reset = None
                    st.session_state.otp_verified = False
                    st.info("Please log in with your new password")
                except Exception as error:  # noqa: BLE001
                    logger.exception("Failed to update password")
                    st.error(f"Failed to update password: {error}")

with signup_tab:
    if google_user_data:
        st.success(f"Authenticated as {google_user_data['name']} ({google_user_data['email']})")
        st.info("Please complete the registration below.")
    elif is_google_configured():
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            if st.button("🔑 Sign up with Google", use_container_width=True):
                state = generate_auth_state()
                st.session_state.oauth_state = state
                auth_url = get_google_auth_url(state)
                st.markdown(f'<meta http-equiv="refresh" content="0;url={auth_url}">', unsafe_allow_html=True)
        st.markdown("---")

    auth_type = st.session_state.get("auth_type", "manual")
    if "signup_child_count" not in st.session_state:
        st.session_state.signup_child_count = 1

    st.markdown("### Children")
    st.caption("You can register more than one child now. You can always add or remove children later from the Parent Profile page.")
    child_count = st.number_input(
        "How many children would you like to register?",
        min_value=1,
        max_value=10,
        value=st.session_state.signup_child_count,
        step=1,
        key="signup_child_count",
    )

    with st.form("registration_form"):
        children: list[dict[str, Any]] = []
        for index in range(1, int(child_count) + 1):
            children.append(render_child_fields("signup", index))

        st.markdown("### Parent Information")
        if auth_type == "google" and google_user_data:
            parent_name = st.text_input("Parent Name", value=google_user_data.get("name", ""), disabled=True)
            parent_email = st.text_input("Parent Email ID", value=google_user_data.get("email", ""), disabled=True)
            parent_username = st.text_input("Parent's Username", value=google_user_data.get("username", ""), disabled=True)
            parent_password = ""
            confirm_password = ""
        else:
            parent_name = st.text_input("Parent Name")
            parent_email = st.text_input("Parent Email ID")
            parent_username = st.text_input("Parent's Username")
            parent_password = st.text_input("Parent Password", type="password")
            confirm_password = st.text_input("Confirm Password", type="password")

        submitted = st.form_submit_button("Register", type="primary", use_container_width=True)

    if submitted:
        form_data = {
            "children": children,
            "parent_name": parent_name,
            "parent_email": parent_email,
            "parent_username": parent_username,
            "parent_password": parent_password,
            "confirm_password": confirm_password,
            "auth_type": auth_type,
        }
        is_valid, error_message = validate_signup(form_data)
        if not is_valid:
            st.error(error_message)
        else:
            try:
                if auth_type == "google" and google_user_data:
                    parent_id = create_parent(
                        parent_name=parent_name,
                        username=parent_username,
                        email=parent_email,
                        google_id=google_user_data["google_id"],
                        auth_type="google",
                    )
                else:
                    parent_id = create_parent(
                        parent_name=parent_name,
                        username=parent_username,
                        email=parent_email,
                        password=parent_password,
                        auth_type="manual",
                    )

                created_ids = []
                for child in children:
                    student_id = generate_student_id()
                    create_student(
                        student_id=student_id,
                        student_name=child["student_name"].strip(),
                        parent_id=parent_id,
                        grade="",
                        country="",
                    )
                    created_ids.append(student_id)
                logger.info(
                    "Registered parent '%s' with %s child(ren): %s.",
                    parent_username,
                    len(created_ids),
                    ", ".join(created_ids),
                )

                # Clear transient sign-up state. Reset the child-count key before the
                # next render so the widget starts from its default value without
                # mutating a widget-owned session state entry after instantiation.
                st.session_state.google_user_data = None
                st.session_state.auth_type = "manual"
                st.session_state.show_signup = False
                st.session_state.pop("signup_child_count", None)

                # Auto sign-in the new parent and continue.
                parent = get_parent_by_username(parent_username)
                if parent:
                    authenticate_parent(parent)
                    st.success(f"Registration successful! Registered {len(created_ids)} child(ren).")
                    st.switch_page("learning-home.py")
                else:
                    st.success(f"Registration successful! Registered {len(created_ids)} child(ren).")
                    st.info("You can now sign in on the Sign In tab.")

            except Exception as error:  # noqa: BLE001
                logger.exception("Registration failed")
                st.error(f"Registration failed: {error}")
                st.session_state.google_user_data = None
                st.session_state.auth_type = "manual"
