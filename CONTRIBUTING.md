# Contributing to hledger-textual

Thank you for your interest in contributing! Your help is essential for keeping
this project great.

Please note that this project is released with a
[Contributor Code of Conduct](CODE_OF_CONDUCT.md). By participating you agree to
abide by its terms.

## Issues

Issues are the best way to report bugs or suggest new features. Before opening a
new issue, please search existing ones to avoid duplicates.

When reporting a bug, include:

- Steps to reproduce the problem
- What you expected to happen
- What actually happened
- Your Python version and OS

When suggesting a feature, describe the use case and why it would be useful.

## Pull Requests

Pull requests are welcome. For non-trivial changes, please open an issue first
to discuss your approach.

### Getting Started

1. Fork and clone the repository
2. Create a virtual environment and install dependencies:
   ```bash
   uv sync
   ```
3. Verify the tests pass:
   ```bash
   uv run pytest tests/ -x -q
   ```
4. Create a new branch from `main`:
   ```bash
   git checkout -b feat/your-feature main
   ```
5. Make your changes, add tests, and ensure all tests pass
6. Push to your fork and submit a pull request

### Branch Naming

Use a descriptive prefix:

- `feat/` for new features
- `fix/` for bug fixes
- `docs/` for documentation changes

### Commit Messages

Follow the [Conventional Commits](https://www.conventionalcommits.org/) standard:

```
<type>: <short summary>
```

**Types:** `feat`, `fix`, `docs`, `test`, `style`, `refactor`, `chore`

Guidelines:

- Use the imperative mood ("add feature" not "added feature")
- Keep the summary under 72 characters
- Do not end the summary with a period
- Add a blank line and a body for complex changes

Examples:

```
feat: add default commodity configuration
fix: use absolute image URLs in README
docs: update installation instructions
test: add coverage for budget form validation
```

### Code Style

- Write all code, comments, and docstrings in English
- Add docstrings to functions, classes, and modules
- Follow the existing code style and conventions
- Ensure `uv run pytest tests/ -x -q` passes before submitting

## Resources

- [How to Contribute to Open Source](https://opensource.guide/how-to-contribute/)
- [GitHub Pull Request documentation](https://docs.github.com/en/pull-requests)
