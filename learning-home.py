from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from html import escape
from typing import Any

import streamlit as st
from streamlit_autorefresh import st_autorefresh

from backend.services import storage
from backend.services.llm_backend import generate_questions as generate_questions_from_backend, load_config, load_curriculum, load_models, resolve_curriculum_topics, resolve_units
from backend.services.auth_storage import get_students_by_parent
from backend.services.email_service import send_exam_report_email
from backend.services.logging_config import get_logger
from middleware import (
    get_current_parent,
    get_current_student,
    is_parent_authenticated,
    logout_parent,
    set_current_student,
)

from ui.components.appearance import render_appearance_toggle

logger = get_logger(__name__)

CURRICULUM = load_curriculum()
CONFIG = load_config()
DEFAULTS = CONFIG["defaults"]
QUESTION_COUNTS = [5, 10, 15, 20, 25, 30]
LEVEL_OPTIONS = ["Simple", "Medium", "Complex"]
FULL_TEST_COUNTS = {"Mathematics": 50, "Physics": 50, "Mechanical Engineering": 100}
FULL_TEST_TOTAL = sum(FULL_TEST_COUNTS.values())
FULL_TEST_MINUTES = 180

st.set_page_config(page_title="Study Sprint", page_icon="*", layout="wide", initial_sidebar_state="collapsed")


def inject_styles(theme: str) -> None:
    from ui.components.theme import inject_styles as ui_inject_styles
    ui_inject_styles(theme)


def save_question_set(student_name: str, subject: str, unit: str, topic: str, level: str, questions: list[dict[str, Any]]) -> int:
    """Store a generated question set and return its id.

    ``RETURNING id`` reads the new row's key on SQLite and on PostgreSQL alike.
    """
    question_set_id = storage.execute(
        "INSERT INTO question_sets (student_name, grade, subject, topic, unit, level, questions_json, created_at)"
        " VALUES (:student_name, '', :subject, :topic, :unit, :level, :questions_json, :created_at)"
        " RETURNING id",
        {
            "student_name": student_name,
            "subject": subject,
            "topic": topic,
            "unit": unit,
            "level": level,
            "questions_json": json.dumps(questions),
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return int(question_set_id or 0)


def reset_exam() -> None:
    for key in ("exam", "answers", "question_times", "question_started_at", "practice_feedback", "current_question", "exam_submitted", "celebration_shown"):
        st.session_state.pop(key, None)


def record_current_question_time() -> None:
    started_at = st.session_state.get("question_started_at")
    if started_at is None:
        return
    current = st.session_state.current_question
    elapsed = max(0.0, time.time() - started_at)
    st.session_state.question_times[current] = st.session_state.question_times.get(current, 0.0) + elapsed
    st.session_state.question_started_at = time.time()


def format_duration(seconds: float) -> str:
    total_seconds = max(0, round(seconds))
    minutes, remaining = divmod(total_seconds, 60)
    return f"{minutes}m {remaining:02d}s" if minutes else f"{remaining}s"


@st.fragment(run_every="1s")
def render_clock() -> None:
    """Show the current time in the timezone configured in config.json."""
    now = datetime.now(CONFIG["zone"])
    st.markdown(
        f'<div class="clock"><div class="clock-time">{now.strftime("%I:%M:%S %p").lstrip("0")}</div>'
        f'<div class="clock-zone">{now.strftime("%Z")} - {escape(str(CONFIG["timezone_label"]))}</div>'
        f'<div class="clock-date">{now.strftime("%a %d %b %Y")}</div></div>',
        unsafe_allow_html=True,
    )


def submit_exam() -> None:
    # Prevent multiple submissions. The flag is set before any database work
    # so a second call in the same or a racing run can never insert a duplicate.
    if st.session_state.get("exam_submitted"):
        return
    st.session_state.exam_submitted = True

    exam = st.session_state.get("exam")
    if not exam:
        st.session_state.result = st.session_state.get("result") or {}
        return

    record_current_question_time()
    answers = st.session_state.get("answers", {})
    correct = sum(answers.get(index) == question["answer"] for index, question in enumerate(exam["questions"]))
    ended = datetime.now(timezone.utc)
    record = {
        "student_name": exam["student_name"], "grade": "", "country": "", "school_state": "", "school_district": "", "subject": exam["subject"], "unit": exam["unit"], "topic": exam["topic"], "level": exam["level"], "question_set_id": exam["question_set_id"],
        "question_count": len(exam["questions"]), "time_limit": exam["time_limit"], "start_time": exam["start_time"],
        "end_time": ended.isoformat(), "score": round(correct / len(exam["questions"]) * 100), "correct_count": correct,
        "wrong_count": len(exam["questions"]) - correct,
        "questions_json": json.dumps([{**question, "student_answer": answers.get(index), "time_seconds": round(st.session_state.question_times.get(index, 0.0), 1)} for index, question in enumerate(exam["questions"])]),
    }

    # Resolve the owning student/parent once, preferring the id captured when the
    # exam was created. Falling back to session state means a hibernated or
    # refreshed session still links the exam instead of leaving student_id NULL.
    parent = get_current_parent()
    student_id_value = exam.get("student_id") or get_current_student()
    parent_id_value = parent["id"] if parent else None
    # exams.student_id stores the public student id (a string such as "STU-001"),
    # matching how student-results filters exams, so it is stored verbatim.
    record["student_id"] = str(student_id_value) if student_id_value else None
    record["parent_id"] = int(parent_id_value) if parent_id_value else None

    # The result is written to session state before any database work so the
    # completion screen always has something to show.
    st.session_state.result = record

    try:
        storage.execute(
            "INSERT INTO exams (student_name, student_id, parent_id, grade, country, school_state, school_district, subject, unit, topic, level, question_set_id, question_count, time_limit, start_time, end_time, score, correct_count, wrong_count, questions_json)"
            " VALUES (:student_name, :student_id, :parent_id, :grade, :country, :school_state, :school_district, :subject, :unit, :topic, :level, :question_set_id, :question_count, :time_limit, :start_time, :end_time, :score, :correct_count, :wrong_count, :questions_json)",
            record,
        )
    except Exception as db_error:
        logger.error("Failed to persist exam for '%s': %s", record["student_name"], db_error)

    if student_id_value and parent:
        try:
            from backend.services.auth_storage import get_student_by_id
            student = get_student_by_id(student_id_value)
            if student:
                login_url = "http://localhost:8501"
                send_exam_report_email(
                    to_email=parent["email"],
                    student_name=student["student_name"],
                    subject=exam["subject"],
                    score=record["score"],
                    correct_count=record["correct_count"],
                    wrong_count=record["wrong_count"],
                    total_questions=record["question_count"],
                    exam_date=ended.strftime("%B %d, %Y at %I:%M %p"),
                    parent_name=parent["parent_name"],
                    login_url=login_url
                )
        except Exception as email_error:
            logger.warning("Failed to send email report: %s", email_error)

    logger.info(
        "Exam submitted: student='%s' subject='%s' score=%s%% (%s/%s correct).",
        record["student_name"], record["subject"], record["score"],
        record["correct_count"], record["question_count"],
    )


def show_result() -> None:
    result = st.session_state.get("result")
    if not result:
        st.warning("Your exam has ended, but the result could not be loaded. Please start a new exam.")
        if st.button("Back to setup", type="primary"):
            reset_exam()
            st.session_state.pop("result", None)
            st.rerun()
        return
    if not st.session_state.get("celebration_shown", False):
        st.balloons()
        st.session_state.celebration_shown = True
    brand_left, brand_right = st.columns([3, 1])
    brand_left.markdown('<div class="eyebrow">Exam complete</div>', unsafe_allow_html=True)
    with brand_right:
        render_clock()
    st.markdown('<div class="celebration">Amazing work! You made it to the finish line!</div>', unsafe_allow_html=True)
    st.title("You did it!")
    st.markdown(f'<div class="success-box"><strong>{result["student_name"]}</strong>, your result has been saved for parent review.</div>', unsafe_allow_html=True)
    st.write("")
    columns = st.columns(4)
    columns[0].metric("Score", f'{result["score"]}%')
    columns[1].metric("Correct", result["correct_count"])
    columns[2].metric("Wrong", result["wrong_count"])
    columns[3].metric("Subject", result["subject"])
    st.subheader("Answer review")
    for index, item in enumerate(json.loads(result["questions_json"]), start=1):
        student_answer = item.get("student_answer") or "Not answered"
        status = "Correct" if student_answer == item["answer"] else "Wrong"
        st.markdown(f"**{index}. {item['question']}**  \nYour answer: {student_answer} - Correct answer: {item['answer']} - Time: {format_duration(item.get('time_seconds', 0))} - **{status}**")
    if st.button("Go Back", type="primary"):
        reset_exam()
        st.session_state.pop("result", None)
        st.rerun()


def option_index(options: list[Any], preferred: Any, fallback: int = 0) -> int:
    try:
        return options.index(preferred)
    except ValueError:
        return fallback


def whole_number(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def reset_topic_selection() -> None:
    st.session_state.pop("practice_topic", None)


def reset_unit_and_topic_selection() -> None:
    st.session_state.pop("practice_unit", None)
    st.session_state.pop("practice_topic", None)


def generate_full_practice_test(model: dict[str, Any], level: str, student_name: str, temperature: float) -> tuple[list[dict[str, Any]], str]:
    """Build the 200-question mock from catalog topics in small model requests."""
    questions: list[dict[str, Any]] = []
    source_names: set[str] = set()
    chunk_size = 20
    for subject, subject_count in FULL_TEST_COUNTS.items():
        topic_pairs = [
            (unit, topic)
            for unit in resolve_units(CURRICULUM, subject)
            for topic in resolve_curriculum_topics(CURRICULUM, subject, unit)
        ]
        if not topic_pairs:
            raise RuntimeError(f"No topics are configured for {subject} in curriculum.json.")
        remaining = subject_count
        topic_index = 0
        while remaining:
            unit, topic = topic_pairs[topic_index % len(topic_pairs)]
            batch_count = min(chunk_size, remaining)
            batch, source = generate_questions_from_backend(
                model, subject, unit, topic, level, batch_count,
                student_name=student_name, temperature=temperature,
            )
            questions.extend({**question, "subject": subject, "unit": unit, "topic": topic, "level": level} for question in batch)
            source_names.add(source)
            remaining -= batch_count
            topic_index += 1
    return questions, ", ".join(sorted(source_names))


def show_setup() -> None:
    parent = get_current_parent()
    students = get_students_by_parent(parent["id"]) if parent else []

    brand_left, brand_right = st.columns([3, 1])
    brand_left.markdown('<div class="brand"><div class="brand-mark">study<span>-</span>sprint</div><div class="pill">Student workspace</div></div>', unsafe_allow_html=True)
    with brand_right:
        render_clock()

    nav_col1, nav_col2, nav_col3 = st.columns([1, 1, 1])
    with nav_col1:
        if st.button("Student Results", use_container_width=True):
            st.switch_page("pages/student-results.py")
    with nav_col2:
        if st.button("Parent Profile", use_container_width=True):
            st.switch_page("pages/parent-profile.py")
    with nav_col3:
        if st.button("Sign out", use_container_width=True):
            logout_parent()

    selected_student_id: str | None = None
    if students:
        st.markdown("### Select Student")
        student_options = {f"{s['student_name']} ({s['student_id']})": s for s in students}
        current_student_id = get_current_student()

        if current_student_id not in {s['student_id'] for s in students}:
            current_student_id = students[0]['student_id']
            set_current_student(current_student_id)

        current_display = next(
            (name for name, s in student_options.items() if s['student_id'] == current_student_id),
            list(student_options.keys())[0],
        )
        selected_student_display = st.selectbox(
            "Student",
            options=list(student_options.keys()),
            index=list(student_options.keys()).index(current_display),
            key="student_selector_home",
        )
        selected_student = student_options[selected_student_display]
        if selected_student['student_id'] != current_student_id:
            set_current_student(selected_student['student_id'])
        # Record the chosen student so the exam can be linked even if the
        # session state (current_student_id) is lost before submission.
        selected_student_id = selected_student['student_id']

        default_name = selected_student['student_name']

        st.markdown("---")
    else:
        default_name = ""

    st.markdown('<div class="hero"><div class="eyebrow">Small steps, sharp thinking</div><h1>Your next best answer starts here.</h1><p>Build confidence with focused practice. Your progress is saved automatically so you can review it later.</p></div>', unsafe_allow_html=True)
    st.write("")
    subject_options = list(CURRICULUM)
    subject = st.selectbox("Subject", subject_options, index=option_index(subject_options, DEFAULTS.get("subject", "Mathematics")), key="practice_subject", on_change=reset_unit_and_topic_selection)
    unit_options = resolve_units(CURRICULUM, subject)
    unit = st.selectbox("Unit", unit_options, index=option_index(unit_options, DEFAULTS.get("unit", "")), key="practice_unit", on_change=reset_topic_selection)
    topic_options = resolve_curriculum_topics(CURRICULUM, subject, unit)
    topic = st.selectbox("Topic", topic_options, index=option_index(topic_options, DEFAULTS.get("topic", "")), key="practice_topic")
    level = st.selectbox("Level", LEVEL_OPTIONS, index=option_index(LEVEL_OPTIONS, DEFAULTS.get("level", "Medium")), key="practice_level")
    practice_mode = st.toggle("Practice mode", value=bool(DEFAULTS["practice_mode"]), help="Shows the correct answer after each question and moves forward only.")
    full_practice_test = st.toggle("Full practice test · 200 questions · 3 hours", value=False, help="Temporarily disabled.", disabled=True)
    with st.form("exam_setup"):
        first, second = st.columns(2)
        if students:
            name = default_name
            st.markdown(f"**Student:** {default_name}")
        else:
            name = first.text_input("Student name", value=default_name, placeholder="e.g. Alex Morgan")
        if full_practice_test:
            first.markdown(f"**Questions:** {FULL_TEST_TOTAL}")
            second.markdown(f"**Time limit:** {FULL_TEST_MINUTES // 60} hours")
        else:
            count = first.selectbox("Number of questions", QUESTION_COUNTS, index=option_index(QUESTION_COUNTS, whole_number(DEFAULTS["question_count"], QUESTION_COUNTS[0])))
            minutes = second.number_input("Time limit (minutes)", min_value=1, max_value=180, value=min(180, max(1, whole_number(DEFAULTS["time_limit"], 10))), step=1)
        submitted = st.form_submit_button("Start practice test" if full_practice_test else "Start exam", use_container_width=True)
    if submitted:
        if not str(name).strip():
            st.error("Please enter a student name to begin.")
            return
        if not subject or not unit or not topic:
            st.error("Please select a subject, unit, and topic to begin.")
            return
        with st.spinner("Preparing your questions..."):
            try:
                if full_practice_test:
                    questions, source = generate_full_practice_test(selected_model, level, str(name).strip(), temperature)
                    exam_subject = "Full Practice Test"
                    exam_unit = "Multiple units"
                    exam_topic = "Mathematics, Physics, Mechanical Engineering"
                    question_count = FULL_TEST_TOTAL
                    time_limit = FULL_TEST_MINUTES
                else:
                    questions, source = generate_questions_from_backend(
                        selected_model, subject, unit, topic, level, count,
                        student_name=str(name).strip(), temperature=temperature,
                    )
                    exam_subject = subject
                    exam_unit = unit
                    exam_topic = topic
                    question_count = count
                    time_limit = int(minutes)
            except RuntimeError as error:
                st.error(str(error))
                return
        for question in questions:
            question.setdefault("subject", subject)
            question.setdefault("unit", unit)
            question.setdefault("topic", topic)
            question.setdefault("level", level)
        question_set_id = save_question_set(str(name).strip(), exam_subject, exam_unit, exam_topic, level, questions)
        st.session_state.exam = {"student_name": str(name).strip(), "student_id": selected_student_id, "subject": exam_subject, "unit": exam_unit, "topic": exam_topic, "level": level, "practice_mode": practice_mode, "question_set_id": question_set_id, "time_limit": time_limit, "questions": questions, "start_time": datetime.now(timezone.utc).isoformat(), "deadline": time.time() + time_limit * 60, "source": source}
        st.session_state.answers = {}
        st.session_state.question_times = {}
        st.session_state.question_started_at = None
        st.session_state.practice_feedback = False
        st.session_state.current_question = 0
        st.session_state.exam_submitted = False
        st.rerun()


def show_exam() -> None:
    if st.session_state.get("exam_submitted"):
        show_result()
        return
    exam = st.session_state.get("exam")
    if not exam:
        show_setup()
        return
    st_autorefresh(interval=1000, key="exam_clock")
    current = st.session_state.current_question
    if "question_times" not in st.session_state:
        st.session_state.question_times = {}
    if st.session_state.get("question_started_at") is None:
        st.session_state.question_started_at = time.time()
    visible_answer = st.session_state.get(f"answer_{current}")
    if visible_answer:
        st.session_state.answers[current] = visible_answer
    seconds_left = max(0, int(exam["deadline"] - time.time()))
    if seconds_left == 0:
        submit_exam()
        st.rerun()
    question = exam["questions"][current]
    minutes, seconds = divmod(seconds_left, 60)
    top_left, top_right = st.columns([3, 1])
    exam_details = " - ".join(escape(str(value)) for value in (exam["student_name"], exam["subject"], exam["unit"], exam["topic"], exam["level"]) if value)
    top_left.markdown(f'<div class="brand"><div class="brand-mark">study<span>-</span>sprint</div><div class="pill">{exam_details}</div></div>', unsafe_allow_html=True)
    with top_right:
        render_clock()
        st.markdown(f'<div class="timer">{minutes:02d}:{seconds:02d}</div><div class="timer-label">remaining</div>', unsafe_allow_html=True)
    st.progress((current + 1) / len(exam["questions"]))
    st.markdown(f'<div class="question-panel"><div class="question-index">Question {current + 1} of {len(exam["questions"])}</div><div class="question-text">{question["question"]}</div>', unsafe_allow_html=True)
    previous_answer = st.session_state.answers.get(current)
    options = question["options"]
    selected = st.radio("Choose one answer", options, index=options.index(previous_answer) if previous_answer in options else None, key=f"answer_{current}", label_visibility="collapsed")
    feedback_shown = st.session_state.get("practice_feedback", False)
    if exam.get("practice_mode") and feedback_shown:
        if selected == question["answer"]:
            st.success("Correct! Great thinking.")
        else:
            st.error(f"Not quite. The correct answer is: {question['answer']}")
    st.markdown('</div>', unsafe_allow_html=True)
    st.write("")
    left, middle, right = st.columns([1, 1, 1])
    if current > 0 and not exam.get("practice_mode") and left.button("Previous", use_container_width=True):
        record_current_question_time()
        st.session_state.answers[current] = selected
        st.session_state.current_question -= 1
        st.session_state.question_started_at = time.time()
        st.rerun()
    if exam.get("practice_mode"):
        action_label = "Finish exam" if current == len(exam["questions"]) - 1 and feedback_shown else "Continue" if feedback_shown else "Check answer"
        if middle.button(action_label, type="primary", use_container_width=True):
            if not selected:
                st.warning("Choose an answer before continuing.")
            elif not feedback_shown:
                st.session_state.answers[current] = selected
                st.session_state.practice_feedback = True
                st.rerun()
            elif current < len(exam["questions"]) - 1:
                record_current_question_time()
                st.session_state.current_question += 1
                st.session_state.practice_feedback = False
                st.session_state.question_started_at = time.time()
                st.rerun()
            else:
                record_current_question_time()
                submit_exam()
                st.rerun()
    elif current < len(exam["questions"]) - 1 and middle.button("Next", type="primary", use_container_width=True):
        record_current_question_time()
        st.session_state.answers[current] = selected
        st.session_state.current_question += 1
        st.session_state.question_started_at = time.time()
        st.rerun()
    if not exam.get("practice_mode") and current == len(exam["questions"]) - 1 and not st.session_state.get("exam_submitted") and right.button("Submit exam", type="primary", use_container_width=True):
        record_current_question_time()
        st.session_state.answers[current] = selected
        submit_exam()
        st.rerun()
    st.caption(f"Questions are generated using {exam['source']}.")


def show_login_gate() -> None:
    st.session_state.setdefault("redirect_after_auth", "home")
    st.switch_page("pages/parent-login.py")


theme = render_appearance_toggle(default=DEFAULTS.get("appearance", "Dark"))
for message in CONFIG["warnings"]:
    st.sidebar.warning(message)
configured_models = load_models()
if not configured_models:
    st.sidebar.error("No enabled models found in config/models.json.")
    st.stop()
selected_model_name = st.sidebar.selectbox("LLM model", [model["name"] for model in configured_models], index=0, help="Models are configured in config/models.json.")
selected_model = configured_models[[model["name"] for model in configured_models].index(selected_model_name)]
temperature = st.sidebar.slider("Temperature", min_value=0.0, max_value=1.0, value=0.3, step=0.1, help="Lower values are more consistent; higher values create more variety.")
try:
    storage.ensure_schema()
except RuntimeError as error:
    st.error(f"Database connection failed: {error}")
    st.stop()
inject_styles(theme)

if not is_parent_authenticated():
    st.session_state.redirect_after_auth = "home"
    logger.info("Unauthenticated visit to learning-home; redirecting to login.")
    st.switch_page("pages/parent-login.py")

logger.info("Rendering student workspace for parent '%s'.", (get_current_parent() or {}).get("username"))

if st.session_state.get("exam_submitted"):
    show_result()
elif "exam" in st.session_state:
    show_exam()
else:
    show_setup()
