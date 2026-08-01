# Contributing

When contributing to this repository, please first discuss the change you wish to make via issue, email, or any other method with the owners of this repository before making a change.

## Development Setup

```sh
# Clone the repository
git clone https://github.com/progovoy/vmn.git
cd vmn

# Create a virtual environment
python3 -m venv ./venv
source ./venv/bin/activate

# Install dependencies
pip install -r ./tests/requirements.txt
pip install -r ./tests/test_requirements.txt
pip install -e ./

# Verify installation
vmn --version  # Should print 0.0.0
```

## Running Tests

Tests require Docker and run in parallel (29 workers by default) using pytest-xdist.

```sh
# Full test suite
./tests/run_pytest.sh

# Run a specific test
./tests/run_pytest.sh --specific_test <test_name>

# Skip a test
./tests/run_pytest.sh --skip_test <test_name>
```

## Code Structure

- `version_stamp/cli/` — CLI entry point, arg parsing, command handlers, config TUI, output/display
- `version_stamp/stamping/` — IVersionsStamper, VersionControlStamper, Jinja2 template generation
- `version_stamp/backends/` — VCS abstraction (Git/LocalFile backends)
- `version_stamp/core/` — Constants, models, logging, utilities, version math
- `version_stamp/ui/` — `vmn ui` FastAPI server, readers, subprocess job runner, and the built SPA under `static/`
- `webui/` — React/Vite source for the UI; `npm run build` writes into `version_stamp/ui/static/`
- `version_stamp/version.py` — vmn's own version string
- `tests/` — Test suite with Docker-based isolated git environments
- `docs/` — Long-form guides (`experiments.md`, `ui.md`) and migration guides

## Working on the Web UI

```sh
pip install -e ".[ui]"
vmn ui --no-browser        # leave running

# Python changes under version_stamp/ui/ → just refresh the browser
# Changes under webui/src/ → rebuild, then refresh (no server restart needed)
cd webui && npm run build
```

The built assets under `version_stamp/ui/static/` are committed, so rebuild and
include them in any PR that touches `webui/src/`.

## Submitting Changes

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run the test suite
5. Submit a Pull Request

We will thank you for every contribution :)
