"""Integration tests for backend services."""

import pytest
import sys
from pathlib import Path

# Add the project root to the path so we can import modules
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


def test_load_curriculum_integration():
    """The practice catalog exposes subjects, units, and topics from JSON."""
    from backend.services.llm_backend import (
        load_curriculum,
        resolve_curriculum_topics,
        resolve_units,
    )

    curriculum = load_curriculum()
    assert "Mathematics" in curriculum
    units = resolve_units(curriculum, "Mathematics")
    assert units
    assert resolve_curriculum_topics(curriculum, "Mathematics", units[0])


def test_question_generation_prompt_uses_selected_curriculum_values(monkeypatch):
    from backend.services import llm_backend

    prompts = []
    monkeypatch.setattr(llm_backend, "historical_mistakes", lambda *_args: [])

    def capture_prompt(_model, prompt, _temperature, _max_tokens):
        prompts.append(prompt)
        return '[{"question":"What is matrix rank?","options":["A","B","C","D"],"answer":"A"}]'

    monkeypatch.setattr(llm_backend, "_request_text", capture_prompt)
    llm_backend.generate_questions(
        {"name": "test-model"},
        "Mathematics",
        "Matrices & Determinants",
        "Rank of a Matrix",
        "Complex",
        1,
        temperature=0.2,
    )

    assert len(prompts) == 1
    assert all(
        value in prompts[0]
        for value in (
            "Mathematics",
            "Matrices & Determinants",
            "Rank of a Matrix",
            "Complex",
        )
    )


def test_load_config_integration():
    """Test that config can be loaded from the backend service."""
    from backend.services.llm_backend import load_config

    config = load_config()
    assert isinstance(config, dict)
    assert "timezone" in config or "zone" in config


def test_config_defaults_use_practice_selection_fields():
    from backend.services.llm_backend import load_config

    defaults = load_config()["defaults"]
    assert defaults["subject"] == "Mathematics"
    assert defaults["level"] == "Medium"
