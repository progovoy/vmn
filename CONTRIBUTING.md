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

- `version_stamp/vmn.py` — Main entry point, CLI commands, version stamping logic
- `version_stamp/stamp_utils.py` — VCS abstraction (Git/LocalFile backends), version parsing utilities
- `version_stamp/version.py` — vmn's own version string
- `tests/` — Test suite with Docker-based isolated git environments

## Submitting Changes

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run the test suite
5. Submit a Pull Request

We will thank you for every contribution :)
