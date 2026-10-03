# Agent Instructions

## Python Environment

- Use the repository's existing `.venv`; do not create or activate a second environment as part of routine work.
- Prefer `.venv/bin/python` for Python commands so they use the repository environment regardless of which terminal is active.
- Run the test suite with `.venv/bin/python -m unittest -v`.
- The project requires Python 3.12 or newer. Check `.venv/bin/python --version` if the interpreter version is unclear; do not silently switch to system Python if it is too old.
- If project imports are missing, install the script's declared dependencies into this same environment with `.venv/bin/python -m pip install requests python-dotenv`.