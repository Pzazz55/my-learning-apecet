from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

from backend.services import storage
from app_settings import BASE_DIR, read_setting

CONFIG_DIR = BASE_DIR / "config"


def _resolve_config_path(filename: str) -> Path:
    """Return the path to a config file, checking config/ first with root fallback."""
    in_config_dir = CONFIG_DIR / filename
    if in_config_dir.exists():
        return in_config_dir
    return BASE_DIR / filename


MODELS_PATH = _resolve_config_path("models.json")
CURRICULUM_PATH = _resolve_config_path("curriculum.json")
CONFIG_PATH = _resolve_config_path("config.json")
DEFAULT_CONFIG: dict[str, Any] = {
    "timezone": "America/New_York",
    "timezone_label": "Eastern Time",
    "defaults": {
        "subject": "Mathematics",
        "unit": "Matrices & Determinants",
        "topic": "",
        "level": "Medium",
        "question_count": 5,
        "time_limit": 10,
        "practice_mode": False,
        "appearance": "Dark",
    },
}


def load_models() -> list[dict[str, Any]]:
    """Return every model listed in models.json (filtered only by ``enabled``)."""
    path = _resolve_config_path("models.json")
    with path.open(encoding="utf-8") as file:
        models = json.load(file)
    return [model for model in models if model.get("enabled", True)]


def model_key_available(model: dict[str, Any]) -> bool:
    """Return True when the API key configured for ``model`` is present."""
    key_name = model.get("api_key_env", "")
    return bool(key_name) and bool(read_setting(key_name))


def load_curriculum() -> dict[str, dict[str, list[str]]]:
    """Load the Subject -> Unit -> Topics catalog used by question generation."""
    with CURRICULUM_PATH.open(encoding="utf-8") as file:
        configured = json.load(file)
    if not isinstance(configured, dict) or not configured:
        raise ValueError("curriculum.json must contain at least one subject.")

    curriculum: dict[str, dict[str, list[str]]] = {}
    for subject, units in configured.items():
        if not isinstance(subject, str) or not isinstance(units, dict) or not units:
            raise ValueError("Each curriculum subject must contain a unit object.")
        curriculum[subject] = {}
        for unit, topics in units.items():
            if not isinstance(unit, str) or not isinstance(topics, list) or not topics:
                raise ValueError("Each curriculum unit must contain a list of topics.")
            curriculum[subject][unit] = [str(topic) for topic in topics]
    return curriculum


def resolve_units(curriculum: dict[str, Any], subject: str) -> list[str]:
    """Return the configured units for a subject."""
    units = curriculum.get(subject, {})
    return list(units) if isinstance(units, dict) else []


def resolve_curriculum_topics(curriculum: dict[str, Any], subject: str, unit: str) -> list[str]:
    """Return the configured topics for a subject and unit."""
    topics = curriculum.get(subject, {}).get(unit, [])
    return [str(topic) for topic in topics] if isinstance(topics, list) else []


def load_config() -> dict[str, Any]:
    """Return the app settings configured in config.json.

    Recognised keys are "timezone" (an IANA name), "timezone_label" (the clock
    caption) and "defaults" (the starting value of each field on the setup
    page). Anything unusable is described in the "warnings" list so the app can
    report it in the sidebar instead of refusing to start.
    """
    settings: dict[str, Any] = {key: value for key, value in DEFAULT_CONFIG.items() if key != "defaults"}
    settings["defaults"] = dict(DEFAULT_CONFIG["defaults"])
    warnings: list[str] = []
    try:
        path = _resolve_config_path("config.json")
        with path.open(encoding="utf-8") as file:
            configured = json.load(file)
    except FileNotFoundError:
        configured = {}
    if not isinstance(configured, dict):
        raise ValueError("config.json must contain a JSON object.")
    for key in ("timezone", "timezone_label"):
        value = configured.get(key)
        if isinstance(value, str) and value.strip():
            settings[key] = value.strip()
    unknown_top = sorted(set(configured) - set(DEFAULT_CONFIG))
    if unknown_top:
        warnings.append(f"config.json has unknown key(s): {', '.join(unknown_top)}.")
    supplied = configured.get("defaults")
    if supplied is not None:
        if not isinstance(supplied, dict):
            warnings.append("config.json 'defaults' must be a JSON object. The built-in defaults are used instead.")
        else:
            unknown_keys = sorted(set(supplied) - set(DEFAULT_CONFIG["defaults"]))
            if unknown_keys:
                warnings.append(f"config.json 'defaults' has unknown key(s): {', '.join(unknown_keys)}.")
            settings["defaults"].update({key: value for key, value in supplied.items() if key in DEFAULT_CONFIG["defaults"]})
    try:
        settings["zone"] = ZoneInfo(settings["timezone"])
    except (KeyError, ValueError):
        warnings.append(f"config.json timezone '{settings['timezone']}' is not a recognised IANA timezone. Falling back to {DEFAULT_CONFIG['timezone']}.")
        settings["timezone"] = DEFAULT_CONFIG["timezone"]
        settings["timezone_label"] = DEFAULT_CONFIG["timezone_label"]
        settings["zone"] = ZoneInfo(settings["timezone"])
    settings["warnings"] = warnings
    return settings


def unique_questions(questions: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for question in questions:
        key = " ".join(str(question.get("question", "")).lower().split())
        if key and key not in seen:
            seen.add(key)
            unique.append(question)
    return unique[:count]


def historical_mistakes(student_name: str, subject: str, unit: str, topic: str) -> list[str]:
    """Questions this student previously answered incorrectly for the same topic.

    The query uses named bind parameters so it runs unchanged on SQLite and on a
    hosted PostgreSQL database.
    """
    rows = storage.fetch_all(
        "SELECT questions_json FROM exams"
        " WHERE lower(student_name) = lower(:student_name)"
        " AND subject = :subject AND unit = :unit AND topic = :topic"
        " ORDER BY end_time DESC",
        {"student_name": student_name, "subject": subject, "unit": unit, "topic": topic},
    )
    mistakes: list[str] = []
    seen: set[str] = set()
    for row in rows:
        try:
            review = json.loads(row["questions_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        for item in review:
            if item.get("student_answer") and item.get("student_answer") != item.get("answer"):
                question = str(item.get("question", "")).strip()
                key = " ".join(question.lower().split())
                if question and key not in seen:
                    seen.add(key)
                    mistakes.append(question)
    return mistakes[:8]


def _api_key(model: dict[str, Any]) -> str:
    key_name = model.get("api_key_env", "")
    key = read_setting(key_name)
    if not key:
        raise RuntimeError(f"Missing API key. Add {key_name} to .env or the app's Streamlit secrets for {model['name']}.")
    return str(key)


def _request_text(model: dict[str, Any], prompt: str, temperature: float, max_tokens: int) -> str:
    provider = model["provider"].lower()
    model_id = model["model"]
    key = _api_key(model)
    if provider == "google":
        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={key}",
            json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens}},
            timeout=45,
        )
        response.raise_for_status()
        parts = response.json()["candidates"][0]["content"]["parts"]
        return "".join(part.get("text", "") for part in parts)
    if provider in {"openai", "openrouter", "groq"}:
        endpoints = {
            "openai": "https://api.openai.com/v1/chat/completions",
            "openrouter": "https://openrouter.ai/api/v1/chat/completions",
            "groq": "https://api.groq.com/openai/v1/chat/completions",
        }
        endpoint = endpoints[provider]
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        if provider == "openrouter":
            headers.update({"HTTP-Referer": "http://localhost", "X-Title": "Study Sprint"})
        response = requests.post(
            endpoint,
            headers=headers,
            json={"model": model_id, "messages": [{"role": "user", "content": prompt}], "temperature": temperature, "max_tokens": max_tokens},
            timeout=45,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    if provider == "huggingface":
        response = requests.post(
            f"https://router.huggingface.co/hf-inference/models/{model_id}",
            headers={"Authorization": f"Bearer {key}"},
            json={"inputs": prompt, "parameters": {"max_new_tokens": min(512, max(256, max_tokens)), "temperature": temperature, "do_sample": temperature > 0}},
            timeout=45,
        )
        response.raise_for_status()
        payload = response.json()
        return payload[0].get("generated_text", "") if isinstance(payload, list) else payload.get("generated_text", "")
    raise RuntimeError(f"Unsupported model provider: {provider}")


def _difficulty_hint(level: str) -> str:
    """Translate the selected level into clear question-writing guidance."""
    hints = {
        "Simple": "Use foundational recall and direct, single-step applications.",
        "Medium": "Use a balanced mix of conceptual understanding and multi-step applications.",
        "Complex": "Require deeper analysis, connected concepts, and challenging multi-step reasoning.",
    }
    return hints.get(level, hints["Medium"])


def generate_questions(
    model: dict[str, Any],
    subject: str,
    unit: str,
    topic: str,
    level: str,
    count: int,
    student_name: str = "",
    temperature: float = 0.3,
) -> tuple[list[dict[str, Any]], str]:
    mistakes = historical_mistakes(student_name, subject, unit, topic) if student_name else []
    mistake_context = (
        f" Revisit these skills previously missed, using fresh questions: {mistakes}."
        if mistakes else ""
    )
    prompt = (
        f"Create exactly {count} multiple-choice questions for subject '{subject}', unit '{unit}', "
        f"and topic '{topic}'. Set the difficulty to '{level}': {_difficulty_hint(level)} "
        "Keep every question directly within the selected topic. Questions must be distinct and technically accurate. "
        f"{mistake_context}Return only a JSON array with no markdown. Each item must have question, "
        "options (exactly four strings), and answer (one option string)."
    )
    last_error = "unknown response"
    for _ in range(3):
        try:
            text = _request_text(model, prompt, temperature, max(800, count * 180))
            start, end = text.find("["), text.rfind("]")
            if start < 0 or end <= start:
                last_error = "response was not a JSON array"
                continue
            parsed = json.loads(text[start:end + 1])
            valid = unique_questions([item for item in parsed if isinstance(item, dict) and len(item.get("options", [])) == 4 and item.get("answer") in item.get("options", [])], count)
            if len(valid) == count:
                return valid, model["name"]
            last_error = f"received {len(valid)} unique valid questions"
        except requests.ConnectionError as error:
            raise RuntimeError(f"Could not reach {model['name']}. Check your internet connection.") from error
        except (ValueError, KeyError, TypeError, requests.RequestException, json.JSONDecodeError) as error:
            last_error = str(error)
    raise RuntimeError(f"{model['name']} could not create {count} unique questions after 3 attempts ({last_error}).")
