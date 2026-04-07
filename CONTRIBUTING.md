# Contributing to Proxi

Thank you for your interest in contributing to Proxi! This document provides guidelines and instructions for contributing to the project, whether through code, documentation, bug reports, or feature requests.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Branching and Workflow](#branching-and-workflow)
- [Coding Standards](#coding-standards)
- [Testing](#testing)
- [Submitting Changes](#submitting-changes)
- [Reporting Issues](#reporting-issues)
- [Communication](#communication)

## Code of Conduct

This project adheres to the terms outlined in [CODE_OF_CONDUCT.md](./CodeOfConduct.md). All contributors are expected to treat each other with respect and foster an inclusive, welcoming environment.

## Getting Started

### Prerequisites

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/) for Python package management
- [`bun`](https://bun.sh) for Node.js dependencies (TUI, frontend, Discord relay)
- Git for version control

### Initial Setup

1. **Fork and clone the repository:**
   ```bash
   git clone https://github.com/gkpodder/Proxi.git
   cd Proxi
   ```

2. **Set up the Python environment:**
   ```bash
   uv sync
   ```

3. **Install Node dependencies:**
   ```bash
   uv run proxi setup
   ```
   This will install dependencies for `cli_ink` (TUI), `react_frontend` (GUI), and `discord_relay`.

4. **Verify your setup:**
   ```bash
   uv run proxi --help
   uv run pytest tests/ -v
   ```

## Development Setup

### Project Structure

- **`proxi/`** – Core Python backend including agents, gateway, integrations, and tools
- **`react_frontend/`** – React-based GUI
- **`cli_ink/`** – Terminal UI built with Ink and TypeScript
- **`discord_relay/`** – Discord integration for chat-based access
- **`tests/`** – Test suite for core modules
- **`docs/`** – Documentation and design artifacts
- **`config/`** – Configuration files (API keys, integrations, tokens)
- **`scripts/`** – Utility scripts for setup and deployment

### Running Proxi During Development

**TUI (Terminal UI):**
```bash
uv run proxi
```

**React Frontend (GUI):**
```bash
cd react_frontend
bun install  # if dependencies not yet installed
bun run dev
```

**Gateway (backend server):**
```bash
uv run proxi gateway start
```

**Tests:**
```bash
uv run pytest tests/ -v
```

## Branching and Workflow

### Branch Naming Conventions

Use descriptive branch names following these patterns:

- **Feature:** `feature/brief-description` (e.g., `feature/add-gmail-integration`)
- **Bug fix:** `fix/brief-description` (e.g., `fix/gateway-session-leak`)
- **Documentation:** `docs/brief-description` (e.g., `docs/update-readme`)
- **Testing:** `test/brief-description` (e.g., `test/add-gateway-tests`)
- **Refactoring:** `refactor/brief-description` (e.g., `refactor/consolidate-logging`)

### Workflow Steps

1. **Create a feature branch from `main` or an appropriate base branch:**
   ```bash
   git checkout -b feature/your-feature
   ```

2. **Make your changes** – commit frequently with clear, descriptive messages.

3. **Keep your branch up to date:**
   ```bash
   git fetch origin
   git rebase origin/main
   ```

4. **Push your branch and open a pull request:**
   ```bash
   git push origin feature/your-feature
   ```

## Coding Standards

### Python

- Follow [PEP 8](https://pep8.org/) style guidelines
- Use type hints where practical
- Keep functions focused and well-documented with docstrings
- Maximum line length: 100 characters (preferred) or 120 (acceptable)

**Example:**
```python
def process_user_input(user_text: str, session_id: str) -> dict:
    """
    Process a user input string and return a structured response.
    
    Args:
        user_text: The raw user input.
        session_id: Unique identifier for the session.
    
    Returns:
        A dict containing the response and any metadata.
    """
    # Your implementation here
    pass
```

### TypeScript / React

- Follow modern TypeScript best practices
- Use meaningful prop and variable names
- Add JSDoc comments for complex components
- Keep component files focused and testable

**Example:**
```typescript
/**
 * Renders a user message in the chat interface.
 * @param message - The message text to display.
 * @param timestamp - When the message was sent.
 */
interface UserMessageProps {
  message: string;
  timestamp: Date;
}

export const UserMessage: React.FC<UserMessageProps> = ({ message, timestamp }) => {
  return <div className="user-message">{message}</div>;
};
```

## Testing

### Running Tests

```bash
uv run pytest tests/ -v
```

### Writing Tests

- Place unit tests in `tests/` with a filename matching the module (e.g., `test_gateway.py`)
- Use clear, descriptive test names that explain what is being tested
- Aim for reasonable coverage of happy paths, edge cases, and error conditions

**Example:**
```python
def test_gateway_session_creation():
    """Verify that a new session is created with valid parameters."""
    gateway = Gateway()
    session = gateway.create_session("user123")
    assert session.id is not None
    assert session.user_id == "user123"

def test_gateway_session_not_created_without_user_id():
    """Verify that session creation fails gracefully with no user ID."""
    gateway = Gateway()
    with pytest.raises(ValueError):
        gateway.create_session(None)
```

## Submitting Changes

### Pull Request Checklist

Before submitting a pull request, ensure:

- [ ] Your code follows the project's coding standards
- [ ] You have added tests for new functionality
- [ ] All tests pass: `uv run pytest tests/ -v`
- [ ] Your branch is up to date with `main`
- [ ] Your commit messages are clear and descriptive
- [ ] You have updated relevant documentation (README, docstrings, etc.)
- [ ] You reference related GitHub issues (e.g., "Fixes #123")

### Pull Request Description

Write a clear, concise description that includes:

1. **What:** A summary of the changes made
2. **Why:** Motivation and reasoning for the changes
3. **How:** A brief overview of the implementation approach
4. **Testing:** How the changes were tested
5. **Related issues:** Links to any related GitHub issues

**Example:**
```
## What
Add prompt caching support to reduce token usage on repeated requests.

## Why
Reduces API costs and improves response latency for common workflows.

## How
- Implemented prompt caching in the LLM client using Anthropic's cache API
- Added configuration flag to enable/disable caching per session
- Updated tool search to avoid redundant context passing

## Testing
- Added unit tests for cache hit/miss scenarios
- Verified token counts are lower with caching enabled
- Tested backward compatibility with non-caching workflows

Fixes #456
```

## Reporting Issues

### Bug Reports

Include the following information:

- **System information** (OS, Python version, Proxi version)
- **Steps to reproduce** the issue
- **Expected behavior**
- **Actual behavior**
- **Logs or error messages** (if applicable)
- **Screenshots or examples** (if helpful)

### Feature Requests

Describe:

- **Use case** – What problem does this feature solve?
- **Proposed solution** – Your idea for how to implement it
- **Alternatives** – Other approaches you considered
- **Additional context** – Any background or examples

## Communication

### Channels

- **GitHub Issues** – Bug reports, feature requests, and general discussion
- **Discord** – Real-time chat for team coordination (if a community server is established)
- **Pull Request Reviews** – Technical discussion tied to code changes

### Review Process

All pull requests will be reviewed for:

- Correctness and quality of implementation
- Alignment with project architecture and goals
- Test coverage and documentation
- Code style and maintainability

Reviewers will provide constructive feedback. Please be responsive to comments and iterate as needed.

## License

By contributing to Proxi, you agree that your contributions will be licensed under the same license as the project. Please refer to [LICENSE](./LICENSE) for details.

## Questions?

Feel free to:

- Open an issue with your question
- Check existing documentation in `docs/
- Review the [README](./README.md) for project overview and setup instructions

Thank you for contributing to Proxi!