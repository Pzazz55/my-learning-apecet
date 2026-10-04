# Study Sprint

A Streamlit practice app with subject, unit, topic, and level-based questions, timed exams, saved results, and parent review.

## Run locally

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run learning-home.py
```

The app connects to the configured Turso database and does not fall back to either local SQLite file. Set `STUDY_SPRINT_DATABASE_URL` to its credentialed URL; a legacy `DATABASE_URL` is accepted only when it points to the configured Turso host. The first screen is the **Parent Login / Sign-Up** page; after signing in you can start exams, review **Student Results** and edit the **Parent Profile** from the in-app buttons.

The database schema is created automatically on first launch (new tables and
columns are added in place on older databases). It includes:

- `exams` table: completed exam results with student details, scores and question data
- `question_sets` table: generated question sets, kept for reuse
- `parents` / `students` tables: accounts and the one-to-many parent → children relationship
- `otp_codes` / `email_queue` tables: password-reset codes and outbound email
- Performance indexes on the commonly queried columns

## Project structure

| Path | Purpose |
| --- | --- |
| `learning-home.py` | App entry point — requires parent login, then setup form, timed exam, celebration screen |
| `pages/parent-login.py` | First screen: Parent Sign In (with Google OAuth + password reset) and Sign Up (multi-child) in one page |
| `pages/student-results.py` | Student Results page (student selector, filters, answer review, delete) |
| `pages/parent-profile.py` | Parent Profile — view/edit the parent details and add/remove/edit children |
| `app_settings.py` | Reads configuration from Streamlit secrets first, then the environment |
| `backend/services/llm_backend.py` | Config and curriculum loading, provider routing, question generation |
| `backend/services/storage.py` | Database layer with support for SQLite, Turso (libsql), and PostgreSQL |
| `backend/services/auth_storage.py` | Parent/student account persistence and exam linking |
| `backend/services/email_service.py` | Outbound email (exam reports, OTP reset codes) |
| `backend/services/google_auth.py` | Google OAuth sign-in |
| `backend/services/logging_config.py` | Shared logging setup; writes rotating logs to `logs/app.log` |
| `ui/components/theme.py` | Light/Dark CSS for the workspace and parent pages |
| `ui/components/appearance.py` | Shared Light/Dark appearance toggle |
| `middleware/` | Parent authentication / session middleware |
| `config/` | `config.json`, `curriculum.json`, `models.json` |
| `tests/` | Pytest unit and integration test suites |
| `logs/` | Runtime log output (`app.log`); contents are git-ignored |
| `requirements.txt` | Runtime dependencies installed by Streamlit Community Cloud |
| `runtime.txt` | Python version used by Streamlit Community Cloud |
| `.streamlit/secrets.toml.example` | Template for the secrets to paste into Community Cloud |

## Deploy to Streamlit Community Cloud

There is no build step: Community Cloud installs `requirements.txt` and runs the main file straight from GitHub.

1. Push the repository to GitHub. With the GitHub CLI:

   ```powershell
   gh repo create my-learning-app --public --source . --remote origin --push
   ```

   Or, after creating an empty repository on github.com:

   ```powershell
   git remote add origin https://github.com/<your-account>/my-learning-app.git
   git push -u origin master
   ```

2. Open <https://share.streamlit.io> and click **Create app** → **Yup, I have an app**.
3. Fill in the app details:

   | Field | Value |
   | --- | --- |
   | Repository | `<your-account>/my-learning-app` |
   | Branch | `master` |
   | Main file path | `learning-home.py` |

4. Click **Advanced settings**. The repository ships a `runtime.txt` pinning Python `3.12`, which Community Cloud picks up automatically; if the UI shows a Python version selector, choose `3.12` to match. Then paste your secrets into the **Secrets** box, starting from `.streamlit/secrets.toml.example`:

   ```toml
   GROQ_API_KEY = "..."
   OPENROUTER_API_KEY = "..."
   PARENT_USERNAME = "parent"
   PARENT_PASSWORD = "change-this-password"
   ```

   Streamlit exposes every root-level key through `st.secrets` **and** as an environment variable, and the app reads both, so the deployed names are identical to the local `.env` names.

5. Click **Deploy**. Most apps go live within a few minutes, and later pushes to `master` update it automatically. Changing `requirements.txt` triggers a full rebuild.

Points to keep in mind once deployed:

- **At least one provider key is required.** The sidebar lists only the models in `config/models.json` whose key is available, and the app stops with an explanatory message when none is.
- **`PARENT_USERNAME` and `PARENT_PASSWORD` are required** to open Parent Results; the page says so instead of failing silently.
- **Never commit `.env` or `.streamlit/secrets.toml`** — both are already excluded by `.gitignore`.
- Secrets can be edited later from the app's **Settings → Secrets** in your workspace.

### Data persistence on Community Cloud

The app uses the hosted Turso database `my-learning-apecet`; local SQLite files are not used. On startup, it creates any missing app tables in that database.

### Connect to the configured Turso database

In Turso, open the `my-learning-apecet` database, create or rotate its authentication token, and use the tokenized URL below.

**For Streamlit Community Cloud:**
- Add to the app's **Advanced settings → Secrets** box:
  ```toml
   STUDY_SPRINT_DATABASE_URL = "libsql://<database-auth-token>@my-learning-apecet-pzazz55.aws-us-east-1.turso.io"
  ```

**For local development:**
- Add to your `.env` file:
  ```env
   STUDY_SPRINT_DATABASE_URL=libsql://<database-auth-token>@my-learning-apecet-pzazz55.aws-us-east-1.turso.io
  ```
- Or save as `.streamlit/secrets.toml` (excluded from Git)

The app rejects URLs for any other host instead of silently switching databases. Never commit the token.

### Turso Benefits

- **Free tier** includes 500MB storage and 1 billion row reads per month
- **SQLite compatibility** - no schema changes needed
- **Edge caching** - fast reads from global edge locations
- **Automatic backups** and point-in-time recovery
- **Easy migration** from local SQLite

## LLM questions

Set `HF_TOKEN` before starting Streamlit to use the Hugging Face inference API with `google/flan-t5-base`. The app validates that the requested questions are unique, stores the generated set in SQLite before showing the first question, and links it to the completed result:

Runtime variables and provider keys are stored in the local `.env` file:

```env
HF_TOKEN=your-token
GROQ_API_KEY=your-groq-key
PARENT_USERNAME=parent
PARENT_PASSWORD=change-this-password
GOOGLE_API_KEY=your-google-key
OPENAI_API_KEY=your-openai-key
OPENROUTER_API_KEY=your-openrouter-key
```

The same names work in `.streamlit/secrets.toml` locally and in the **Secrets** box on Streamlit Community Cloud. The `.env` file is excluded from Git.

## Logging

Logging is configured once by `backend/services/logging_config.py`. Every module calls `get_logger(__name__)` and the first call sets up the root logger with:

- a console handler (visible in the Streamlit terminal), and
- a rotating file handler writing to `logs/app.log` (5 MB per file, 3 backups).

The `logs/` directory is created automatically and its contents are git-ignored. Key events such as sign-in/sign-out, successful or failed logins, registrations, exam submissions, result deletions and profile updates are logged.

## Configuration directory (`config/`)

- **`config/curriculum.json`** defines the available subjects, their units, and each unit's topics. Selecting a subject loads its units; selecting a unit loads its topics. Keep the JSON shape as `subject -> unit -> [topics]`.
- **`config/config.json`** sets the display timezone and optional setup defaults.
- **`config/models.json`** controls the available LLM providers and API key environment variable mappings.

Question generation sends the selected subject, unit, topic, and level (`Simple`, `Medium`, or `Complex`) to the selected LLM. The exam and question-set records retain the selected metadata; database migrations add the new fields to existing databases. Student registration only requires a name. Legacy grade/location columns remain in the database for compatibility but are no longer part of the app workflow.

The full practice test contains 200 questions over 3 hours: Mathematics (50), Physics (50), and Mechanical Engineering (100). It distributes each section across topics configured for that subject.

## Model configuration

Edit `config/models.json` to control which providers appear in the sidebar. Each enabled entry specifies its provider, provider model ID, and the environment variable containing its key. Supported providers are `google`, `openai`, `openrouter`, `groq`, and `huggingface`. Models are shown only when `enabled` is true and the configured API key exists. Disable a model with `"enabled": false` without changing Python code.

The selected model is routed through the matching provider automatically. An exam cannot start unless the selected model's configured API key is available.

## Application configuration

Optional `defaults` in `config/config.json` can set `subject`, `unit`, `topic`, `level`, `question_count`, `time_limit`, `practice_mode`, and `appearance`. The standard practice limit is configurable up to 180 minutes; the full practice test always uses 3 hours.

- `timezone` accepts any IANA name, for example `America/New_York`, `Europe/London` or `Asia/Kolkata`. The clock and completed timestamps use this zone.
- `timezone_label` is the caption shown under the clock.
- Invalid timezone settings are reported as warnings and fall back to the built-in timezone.
- `tzdata` supplies the IANA database on Windows and is listed in both `requirements.txt` and `pyproject.toml`.

## Parent results login

The whole application is parent-gated: the first screen is the **Parent Login / Sign-Up** page (`pages/parent-login.py`), which contains a **Sign In** tab and a **Sign Up** tab. Sign-up creates the parent account and their first student, then signs the parent straight in. Once signed in, the Sign Up tab is never shown again — visiting the page just offers to return to the workspace.

Sign in supports both manual credential accounts and Google OAuth, plus an email-OTP password reset for manual accounts.

Authenticated parents can delete saved tests after confirming the deletion.

Each saved test expands into a metric row (score, correct, wrong, question count and overall time) plus an answer review table. The review table lists every question with its `A)`–`D)` options next to the student's answer, the correct answer, the time taken and the status.

Results can be filtered by subject, unit, topic, and level. Full practice test results keep per-question subject and topic details so they can be found through those filters.
