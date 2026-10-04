"""Unit tests for configuration loading."""

import pytest
from pathlib import Path
import json
import sys

# Add the project root to the path so we can import modules
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


def test_config_files_exist(config_dir):
    """Test that configuration files exist."""
    assert (config_dir / "config.json").exists()
    assert (config_dir / "curriculum.json").exists()
    assert (config_dir / "models.json").exists()


def test_config_json_structure(config_dir):
    """Test that config.json has the expected structure."""
    config_path = config_dir / "config.json"
    with open(config_path) as f:
        config = json.load(f)
    
    assert isinstance(config, dict)
    assert "timezone" in config or "defaults" in config


def test_curriculum_json_contains_subject_units_and_topics(config_dir):
    with open(config_dir / "curriculum.json", encoding="utf-8") as file:
        curriculum = json.load(file)

    assert set(curriculum) == {"Mathematics", "Physics", "Chemistry", "Mechanical Engineering"}
    assert curriculum["Mathematics"]["Matrices & Determinants"]
    assert curriculum["Mechanical Engineering"]["Thermodynamics & Heat Power"]