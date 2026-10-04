"""Parent Profile Management page.

After the parent logs in they can:
* view and edit the student profile created during sign-up, and
* view/update their own parent account details.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import streamlit as st

from backend.services import llm_backend
from backend.services.auth_storage import (
    get_student_by_id,
    update_student,
    get_students_by_parent,
    create_student,
    delete_student,
)
from backend.services.google_auth import is_google_configured
from backend.services.logging_config import get_logger
from middleware import (
    require_parent_auth,
    logout_parent,
    get_current_parent,
    get_current_student,
    set_current_student,
)
from ui.components.theme import inject_parent_theme
from ui.components.appearance import render_appearance_toggle

logger = get_logger(__name__)

# Page configuration
st.set_page_config(page_title="Parent Profile · Study Sprint", page_icon="👤", layout="wide")

# Load configuration first so DEFAULTS is available to the theme toggle.
CONFIG = llm_backend.load_config()
DEFAULTS = CONFIG.get("defaults", {})

# Theme
theme = render_appearance_toggle(default=DEFAULTS.get("appearance", "Dark"))
inject_parent_theme(theme)

# Security check
require_parent_auth()

parent = get_current_parent()

# If the parent has multiple students, let them pick which profile to edit.
students = get_students_by_parent(parent["id"]) if parent else []
if not students:
    st.info("No students registered yet. Please register a student first.")
    if st.button("Register Student"):
        st.switch_page("pages/parent-login.py")
    st.stop()

student_options = {f"{s['student_name']} ({s['student_id']})": s['student_id'] for s in students}
current_student_id = get_current_student()
if not current_student_id or current_student_id not in student_options.values():
    current_student_id = students[0]['student_id']
    set_current_student(current_student_id)

current_display = next((name for name, sid in student_options.items() if sid == current_student_id), list(student_options.keys())[0])
selected_student_display = st.selectbox(
    "Editing student",
    options=list(student_options.keys()),
    index=list(student_options.keys()).index(current_display),
    key="profile_student_selector",
)
current_student_id = student_options[selected_student_display]
set_current_student(current_student_id)

# Get student data
student = get_student_by_id(current_student_id)

if not student:
    st.error("Student not found.")
    st.switch_page("pages/student-results.py")

st.markdown('<div class="brand">study<span>·</span>sprint / parent profile</div>', unsafe_allow_html=True)
st.markdown("## Parent Profile")
st.caption(f"Manage profile for {student['student_name']} ({student['student_id']})")

# Display current profile information
st.markdown("### Current Profile Information")

st.markdown(f"**Student Name:** {student['student_name']}")
st.markdown(f"**Student ID:** {student['student_id']}")

st.markdown(f"**Registered:** {datetime.fromisoformat(student['created_at']).strftime('%B %d, %Y')}")
st.markdown(f"**Last Updated:** {datetime.fromisoformat(student['updated_at']).strftime('%B %d, %Y at %I:%M %p')}")

# Edit profile form
st.markdown("---")
st.markdown("### Update Profile Information")

with st.form("update_profile"):
    st.markdown("#### Student Information")
    new_student_name = st.text_input("Student Name", value=student['student_name'])
    submitted = st.form_submit_button("Update Profile", type="primary")

if submitted:
    try:
        update_student(
            student_id=current_student_id,
            student_name=new_student_name,
        )
        
        st.success("Profile updated successfully!")
        logger.info("Updated student profile '%s'.", current_student_id)
        st.rerun()
        
    except Exception as e:
        logger.exception("Failed to update student profile")
        st.error(f"Failed to update profile: {e}")

# Account information section
st.markdown("---")
st.markdown("### Manage Children")
st.caption("Add another child to this account, or remove a child you no longer need.")

with st.expander("➕ Add a child", expanded=False):
    with st.form("add_child"):
        new_child_name = st.text_input("Child's name", key="add_child_name")
        add_submitted = st.form_submit_button("Add child", type="primary")

    if add_submitted:
        if not new_child_name.strip():
            st.error("Please enter the child's name.")
        else:
            try:
                new_id = f"STU{uuid.uuid4().hex[:8].upper()}"
                create_student(
                    student_id=new_id,
                    student_name=new_child_name.strip(),
                    parent_id=parent["id"],
                    grade="",
                    country="",
                )
                logger.info("Parent %s added child '%s' (%s).", parent["id"], new_child_name.strip(), new_id)
                st.success(f"Added {new_child_name.strip()} ({new_id}).")
                st.rerun()
            except Exception as error:  # noqa: BLE001
                logger.exception("Failed to add child")
                st.error(f"Could not add child: {error}")

if len(students) <= 1:
    # Only one child: removing them is not allowed. Show the reason directly on
    # the page (not inside a collapsed expander) so it is always visible.
    st.info("You must keep at least one child on the account. Remove is unavailable while only one child is registered — add another child first if you need to remove this one.")
else:
    with st.expander("➖ Remove a child", expanded=False):
        remove_options = {f"{s['student_name']} ({s['student_id']})": s['student_id'] for s in students}
        remove_target = st.selectbox("Select the child to remove", options=list(remove_options.keys()), key="remove_child_target")
        confirm_remove = st.checkbox("I understand this permanently removes this child and their results.", key="confirm_remove_child")
        if st.button("Remove child", type="primary", disabled=not confirm_remove, key="remove_child_button"):
            remove_id = remove_options[remove_target]
            if remove_id == current_student_id:
                remaining = [s for s in students if s['student_id'] != remove_id]
                if remaining:
                    set_current_student(remaining[0]['student_id'])
            delete_student(remove_id, parent["id"])
            logger.info("Parent %s removed child %s.", parent["id"], remove_id)
            st.success("Child removed.")
            st.rerun()

# Account information section
st.markdown("---")
st.markdown("### Account Information")

col1, col2 = st.columns(2)
with col1:
    st.markdown(f"**Parent Name:** {parent['parent_name']}")
    st.markdown(f"**Parent Email:** {parent['email']}")

with col2:
    st.markdown(f"**Username:** {parent['username']}")
    auth_type = parent.get('auth_type', 'manual')
    auth_display = "Google" if auth_type == 'google' else "Email/Password"
    st.markdown(f"**Authentication:** {auth_display}")

# Password change for manual accounts
if auth_type == 'manual':
    st.markdown("---")
    st.markdown("### Change Password")
    
    with st.form("change_password"):
        current_password = st.text_input("Current Password", type="password")
        new_password = st.text_input("New Password", type="password")
        confirm_password = st.text_input("Confirm New Password", type="password")
        submitted = st.form_submit_button("Change Password", type="primary")
    
    if submitted:
        from backend.services.auth_storage import verify_parent_credentials, update_parent_password
        
        # Verify current password
        verified = verify_parent_credentials(parent['username'], current_password)
        if not verified:
            st.error("Current password is incorrect.")
        elif new_password != confirm_password:
            st.error("New passwords do not match.")
        elif len(new_password) < 6:
            st.error("Password must be at least 6 characters.")
        else:
            try:
                update_parent_password(parent['id'], new_password)
                logger.info("Password changed for parent id %s.", parent['id'])
                st.success("Password changed successfully!")
            except Exception as e:
                logger.exception("Failed to change password")
                st.error(f"Failed to change password: {e}")

# Navigation buttons
st.markdown("---")
col1, col2, col3 = st.columns(3)
with col1:
    if st.button("← Back to Student Results"):
        st.switch_page("pages/student-results.py")
with col2:
    if st.button("Start an Exam"):
        st.switch_page("learning-home.py")
with col3:
    if st.button("🚪 Sign Out"):
        logout_parent()