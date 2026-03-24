# Contributing

Thanks for your interest in contributing to Ryanair FlyNomad!

## Getting Started

```bash
git clone https://github.com/avkudryashov/ryanair.git
cd ryanair
pip install -r requirements.txt
python3 app.py
```

Open http://localhost:5000

## Running Tests

```bash
# Unit tests
pytest tests/test_app.py

# Playwright E2E tests (requires chromium)
playwright install chromium
pytest tests/test_playwright.py -v
```

All tests must pass before submitting a PR.

## Submitting Changes

1. Fork the repo and create a branch from `main`
2. Make your changes
3. Add tests if you're adding new functionality
4. Run the full test suite
5. Open a pull request with a clear description

## Reporting Issues

Open a [GitHub issue](https://github.com/avkudryashov/ryanair/issues) with:
- Steps to reproduce
- Expected vs actual behavior
- Browser/OS if it's a UI issue

## Code Style

- Follow existing patterns in the codebase
- Python: keep it simple, no type annotations unless already present
- JavaScript: vanilla JS, no frameworks beyond HTMX
- Translations: add all 7 languages (EN, ES, IT, FR, PT, DE, RU) when adding UI strings
