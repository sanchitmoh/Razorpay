# Contributing to Razorpay Reconciliation Agent

Thank you for your interest in contributing to the Razorpay Reconciliation Agent! This document provides guidelines and instructions for contributing.

## 📋 Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Workflow](#development-workflow)
- [Testing](#testing)
- [Code Style](#code-style)
- [Commit Messages](#commit-messages)
- [Pull Request Process](#pull-request-process)
- [CI/CD Pipeline](#cicd-pipeline)

## 🤝 Code of Conduct

- Be respectful and inclusive
- Provide constructive feedback
- Focus on what is best for the community
- Show empathy towards others

## 🚀 Getting Started

### Prerequisites

- Python 3.10 or higher
- Git
- Virtual environment tool (venv, virtualenv, or conda)
- (Optional) Docker for containerized development

### Setup Development Environment

1. **Fork and clone the repository**

```bash
git clone https://github.com/YOUR_USERNAME/Razorpay.git
cd Razorpay/reconcile-agent
```

2. **Create virtual environment**

```bash
python -m venv venv
# On Windows:
venv\Scripts\activate
# On Unix or MacOS:
source venv/bin/activate
```

3. **Install dependencies**

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt  # If exists
# Install development tools
pip install pytest-cov ruff black isort mypy pre-commit
```

4. **Set up pre-commit hooks**

```bash
pre-commit install
```

5. **Configure environment variables**

```bash
cp .env.example .env
# Edit .env with your configuration
```

6. **Run database migrations**

```bash
alembic upgrade head
```

7. **Verify installation**

```bash
python test_connections.py
pytest tests/ -v
```

## 🔄 Development Workflow

### Branch Strategy

We use **Git Flow** branching model:

- `main` - Production-ready code
- `develop` - Integration branch for features
- `feature/*` - New features
- `fix/*` - Bug fixes
- `hotfix/*` - Critical production fixes
- `test/*` - Testing and experiments

### Creating a Feature Branch

```bash
# Update develop branch
git checkout develop
git pull origin develop

# Create feature branch
git checkout -b feature/your-feature-name

# Make changes and commit
git add .
git commit -m "feat: add new feature"

# Push to your fork
git push origin feature/your-feature-name
```

## 🧪 Testing

### Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_matcher.py -v

# Run with coverage
pytest tests/ --cov=app --cov-report=html

# Run specific test markers
pytest -m "unit" -v
pytest -m "integration" -v
pytest -m "slow" -v

# Run tests in parallel
pytest tests/ -n auto
```

### Writing Tests

- Place tests in `tests/` directory
- Name test files with `test_` prefix
- Name test functions with `test_` prefix
- Use pytest fixtures from `conftest.py`
- Aim for >80% code coverage

**Example test:**

```python
import pytest
from app.services.matcher import Matcher

@pytest.mark.unit
def test_exact_match():
    """Test exact UTR matching."""
    matcher = Matcher()
    result = matcher.match_by_utr("UTR123", "UTR123")
    assert result.is_match is True
    assert result.confidence == 1.0

@pytest.mark.integration
async def test_full_reconciliation(db_session):
    """Test complete reconciliation workflow."""
    # Your integration test here
    pass
```

### Test Categories

Mark your tests appropriately:

```python
@pytest.mark.unit          # Fast, isolated unit tests
@pytest.mark.integration   # Tests with database/external services
@pytest.mark.slow          # Long-running tests
@pytest.mark.security      # Security-focused tests
@pytest.mark.adversarial   # Edge case/adversarial tests
```

## 🎨 Code Style

### Python Code Standards

We follow **PEP 8** with some modifications:

- Line length: 100 characters (enforced by Black)
- Use type hints where possible
- Docstrings for all public functions/classes
- Use f-strings for formatting

### Automated Formatting

```bash
# Format code with Black
black app/ tests/

# Sort imports with isort
isort app/ tests/

# Lint with Ruff
ruff check app/ tests/

# Type check with mypy
mypy app/ --ignore-missing-imports
```

### Pre-commit Hooks

Install pre-commit hooks to automatically format code:

```bash
pre-commit install
```

This will run before each commit:
- Black (formatting)
- isort (import sorting)
- Ruff (linting)
- Trailing whitespace removal
- End-of-file fixer

### Code Structure

```python
"""Module docstring explaining purpose.

This module handles reconciliation matching logic.
"""

from typing import List, Optional
import asyncio

from sqlalchemy.ext.asyncio import AsyncSession
from app.models.payment import Payment


class Matcher:
    """Matcher class for reconciliation.
    
    Attributes:
        threshold: Confidence threshold for fuzzy matching
    """
    
    def __init__(self, threshold: float = 0.8):
        """Initialize matcher.
        
        Args:
            threshold: Minimum confidence score for match (0.0-1.0)
        """
        self.threshold = threshold
    
    async def match_payments(
        self, 
        db: AsyncSession,
        batch_id: str
    ) -> List[Payment]:
        """Match payments in a batch.
        
        Args:
            db: Database session
            batch_id: UUID of batch to process
            
        Returns:
            List of matched Payment objects
            
        Raises:
            ValueError: If batch_id is invalid
            DatabaseError: If database query fails
        """
        # Implementation
        pass
```

## 📝 Commit Messages

### Conventional Commits

We use [Conventional Commits](https://www.conventionalcommits.org/) format:

```
<type>(<scope>): <subject>

<body>

<footer>
```

**Types:**
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation only
- `style`: Code style changes (formatting, etc.)
- `refactor`: Code refactoring
- `test`: Adding or updating tests
- `chore`: Maintenance tasks
- `perf`: Performance improvements
- `ci`: CI/CD changes
- `build`: Build system changes
- `revert`: Revert previous commit

**Examples:**

```bash
feat(matcher): add fuzzy UTR matching algorithm

Implements Levenshtein distance for UTR matching with configurable
threshold. Improves match rate by 15% in test scenarios.

Closes #123

---

fix(api): handle null values in CSV upload

Previous implementation crashed on empty cells. Now properly handles
null values and skips invalid rows with logging.

Fixes #456

---

docs: update API endpoint documentation

Added examples for /api/v1/qa endpoint with request/response samples.

---

test(security): add webhook signature verification tests

Covers HMAC-SHA256 validation, replay attacks, and timing attacks.
```

## 🔀 Pull Request Process

### Before Creating PR

1. **Ensure tests pass locally**
```bash
pytest tests/ -v
```

2. **Run linting and formatting**
```bash
black app/ tests/
isort app/ tests/
ruff check app/ tests/
```

3. **Update documentation if needed**
- Update README.md
- Add docstrings
- Update API documentation

4. **Rebase on latest develop**
```bash
git fetch origin
git rebase origin/develop
```

### Creating the PR

1. **Push your branch**
```bash
git push origin feature/your-feature-name
```

2. **Open Pull Request on GitHub**
   - Use descriptive title following conventional commits
   - Fill out the PR template
   - Link related issues
   - Add appropriate labels
   - Request reviewers

3. **PR Template**

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix (non-breaking change)
- [ ] New feature (non-breaking change)
- [ ] Breaking change
- [ ] Documentation update

## How Has This Been Tested?
Describe the tests you ran

## Checklist
- [ ] Tests pass locally
- [ ] Code follows style guidelines
- [ ] Self-review completed
- [ ] Comments added for complex code
- [ ] Documentation updated
- [ ] No new warnings generated
- [ ] Tests added for new features
- [ ] Dependent changes merged
```

### PR Review Process

1. **Automated Checks** (GitHub Actions)
   - All tests must pass
   - Linting checks must pass
   - Security scans must pass
   - Code coverage must meet threshold

2. **Code Review**
   - At least one approval required
   - Address all review comments
   - Update PR based on feedback

3. **Merge**
   - Squash and merge (preferred)
   - Rebase and merge (for clean history)
   - Merge commit (for feature branches)

## 🤖 CI/CD Pipeline

### Automated Workflows

When you create a PR, the following checks run automatically:

1. **Test Suite** (Python 3.10, 3.11, 3.12)
   - Unit tests
   - Integration tests
   - Coverage report

2. **Code Quality**
   - Ruff linting
   - Black formatting check
   - isort import check
   - mypy type checking

3. **Security**
   - Bandit security scan
   - Safety dependency check

4. **PR Validation**
   - Title format check
   - Large file detection
   - Secret scanning
   - PR size check

### Viewing CI Results

1. Go to your PR page
2. Check status at bottom of PR
3. Click "Details" to view logs
4. Fix any failures and push changes

### Running CI Checks Locally

```bash
# Full CI simulation
pytest tests/ -v --cov=app
black --check app/ tests/
isort --check-only app/ tests/
ruff check app/ tests/
mypy app/ --ignore-missing-imports
bandit -r app/
```

### CI Failure Troubleshooting

**Tests fail in CI but pass locally:**
- Check Python version (use 3.12)
- Verify environment variables
- Check file paths (use pathlib)
- Review CI logs carefully

**Linting errors:**
```bash
# Auto-fix most issues
black app/ tests/
isort app/ tests/
ruff check --fix app/ tests/
```

## 🐛 Bug Reports

### Before Reporting

1. Search existing issues
2. Check if already fixed in develop
3. Verify it's reproducible

### Bug Report Template

```markdown
**Describe the bug**
Clear description of the bug

**To Reproduce**
Steps to reproduce:
1. Go to '...'
2. Click on '...'
3. See error

**Expected behavior**
What should happen

**Actual behavior**
What actually happens

**Screenshots**
If applicable

**Environment:**
- OS: [e.g., Windows 11]
- Python version: [e.g., 3.12]
- Package version: [e.g., 1.0.0]

**Additional context**
Any other relevant information
```

## 💡 Feature Requests

### Feature Request Template

```markdown
**Is your feature request related to a problem?**
Description of the problem

**Describe the solution you'd like**
Clear description of desired solution

**Describe alternatives considered**
Alternative solutions or features

**Additional context**
Any other relevant information, mockups, examples
```

## 📚 Resources

- [Project README](README.md)
- [CI/CD Setup Guide](CI_CD_SETUP_GUIDE.md)
- [API Documentation](http://localhost:8000/docs)
- [Architecture Overview](FEATURES_VERIFICATION.md)

## ❓ Questions?

- Open a [GitHub Discussion](https://github.com/YOUR_USERNAME/Razorpay/discussions)
- Create an issue with the `question` label
- Contact maintainers

## 🏆 Recognition

Contributors will be recognized in:
- README.md contributors section
- Release notes
- GitHub contributor graph

Thank you for contributing! 🎉
