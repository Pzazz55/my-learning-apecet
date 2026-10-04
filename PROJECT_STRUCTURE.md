# Project Structure

This document describes the enterprise-standard folder structure for the Learning Application.

## Directory Structure

```
my-learning-app/
├── backend/                    # Backend services and data layer
│   ├── __init__.py
│   ├── models/                # Data models and schemas
│   │   └── __init__.py
│   └── services/              # Business logic and data services
│       ├── __init__.py
│       ├── llm_backend.py     # LLM integration and configuration loading
│       ├── logging_config.py  # Shared logging configuration (writes to logs/)
│       └── storage.py         # Database operations and storage layer
├── config/                    # Configuration files
│   ├── __init__.py
│   ├── config.json            # Application configuration
│   ├── curriculum.json        # Subject, unit, and topic catalog
│   └── models.json            # AI model configurations
├── middleware/                # Cross-cutting concerns and middleware
│   ├── __init__.py
│   └── auth/                  # Authentication and authorization
│       ├── __init__.py
│       └── auth_middleware.py # Parent authentication logic
├── ui/                        # User interface components
│   ├── __init__.py
│   └── components/            # Reusable UI components
│       ├── __init__.py
│       └── theme.py           # Styling and theme management
├── tests/                     # Test suite
│   ├── __init__.py
│   ├── conftest.py            # Pytest configuration and fixtures
│   ├── unit/                  # Unit tests
│   │   ├── __init__.py
│   │   ├── test_config.py     # Configuration tests
│   │   └── test_storage.py    # Storage layer tests
│   └── integration/          # Integration tests
│       ├── __init__.py
│       └── test_backend_integration.py
├── pages/                     # Streamlit pages
│   ├── parent-login.py         # First screen: Parent Sign In + Sign Up (tabs)
│   ├── student-results.py      # Student results page
│   └── parent-profile.py       # Parent / student profile page
├── logs/                      # Runtime logs (git-ignored, created on first run)
├── learning-home.py           # Main student interface (parent-gated)
├── app_settings.py            # Application settings and environment
├── requirements.txt            # Python dependencies
├── pyproject.toml             # Project configuration
└── README.md                  # Project documentation
```

## Key Changes

### Backend Layer
- **`backend/services/`**: Contains business logic including LLM integration (`llm_backend.py`) and database operations (`storage.py`)
- **`backend/models/`**: Reserved for data models and schemas (future expansion)

### Configuration
- **`config/`**: Centralized configuration files for the application
- All JSON configuration files are now in a dedicated directory

### Middleware
- **`middleware/auth/`**: Authentication logic extracted from pages into reusable middleware
- **`auth_middleware.py`**: Provides parent authentication functions and decorators

### UI Components
- **`ui/components/`**: Reusable UI components separated from page logic
- **`theme.py`**: Centralized styling and theme management

### Testing
- **`tests/`**: Comprehensive test structure with unit and integration tests
- **`tests/conftest.py`**: Shared pytest fixtures
- Proper organization for test maintenance and expansion

## Import Structure

All imports now follow the new package structure:

```python
# Backend services
from backend.services import storage
from backend.services.llm_backend import load_config, load_curriculum
from backend.services.logging_config import get_logger

# Middleware
from middleware import require_parent_auth, logout_parent

# UI components
from ui.components.theme import inject_styles, inject_parent_theme

# App settings
from app_settings import read_setting

logger = get_logger(__name__)
```

## Benefits

1. **Separation of Concerns**: Each layer has a clear responsibility
2. **Maintainability**: Easier to locate and modify specific functionality
3. **Scalability**: Simple to add new features in appropriate directories
4. **Testability**: Isolated components are easier to test
5. **Enterprise Standard**: Follows common Python project structure patterns
6. **Reusability**: Components can be imported and reused across the application

## Running the Application

The application structure remains compatible with Streamlit:

```bash
streamlit run learning-home.py
```

The app is parent-gated: the Parent Login / Sign-Up page is shown first, and the individual pages (`pages/parent-login.py`, `pages/student-results.py`, `pages/parent-profile.py`) are reached through in-app navigation after sign-in.

## Running Tests

```bash
# Run all tests
pytest

# Run unit tests only
pytest tests/unit/

# Run integration tests only
pytest tests/integration/
```

## Compilation Status

✅ All Python files compile successfully
✅ All import statements updated and working
✅ Streamlit application starts without errors
✅ Project structure follows enterprise standards