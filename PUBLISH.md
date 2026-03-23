# Publishing diskman to PyPI

This guide explains how to publish diskman to PyPI.

## Prerequisites

1. **PyPI Account**: Create one at https://pypi.org/account/
2. **API Token**: Generate an API token at https://pypi.org/manage/account/token/
3. **GitHub Tag**: Create a git tag for the version (e.g., `v0.2.3`)

## Publishing Steps

### 1. Update Version

Ensure the version in these files matches:
- `pyproject.toml`: `version = "0.2.3"`
- `src/diskman/__init__.py`: `__version__ = "0.2.3"`

### 2. Create Git Tag

```bash
git tag -a v0.2.3 -m "Release version 0.2.3"
git push origin v0.2.3
```

### 3. Build and Publish

#### Option A: Using the script (Recommended)

```bash
# Set your PyPI credentials
export TWINE_USERNAME=__token__
export TWINE_PASSWORD=pypi-your-actual-pypi-token-here

# Publish to PyPI
./scripts/publish_pypi.sh
```

#### Option B: Manual steps

```bash
# Install build tools
python3 -m pip install --upgrade build twine

# Build the package
python3 -m build --outdir packages

# Verify the package
python3 -m twine check packages/*

# Upload to PyPI
python3 -m twine upload packages/*
# When prompted, use:
#   Username: __token__
#   Password: pypi-your-actual-pypi-token-here
```

### 4. Verify Publication

Visit https://pypi.org/project/diskman/ to confirm the new version is live.

## Testing with TestPyPI

Before publishing to the real PyPI, test with TestPyPI:

```bash
# Generate a TestPyPI token at https://test.pypi.org/manage/account/token/
export TWINE_USERNAME=__token__
export TWINE_PASSWORD=testpypi-your-test-token-here

# Publish to TestPyPI
./scripts/publish_pypi.sh
# Or manually:
python3 -m twine upload --repository-url https://test.pypi.org/legacy/ packages/*
```

## GitHub Actions (Automatic)

The repository has a GitHub Actions workflow that automatically publishes to PyPI when you push a version tag:

1. Push a tag: `git push origin v0.2.3`
2. GitHub Actions will build and publish automatically
3. Requires `PYPI_API_TOKEN` secret in repository settings

### Setting up GitHub Secrets

1. Go to your repository Settings > Secrets and variables > Actions
2. Add a new secret named `PYPI_API_TOKEN`
3. Paste your PyPI API token as the value

## Post-Publish

After publishing, users can install via:

```bash
pip install --upgrade diskman
```
