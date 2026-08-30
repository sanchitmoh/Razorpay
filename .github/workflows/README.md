# GitHub Actions CI/CD Pipeline Documentation

This directory contains GitHub Actions workflows for the Razorpay Reconciliation Agent project.

## 📋 Available Workflows

### 1. CI - Testing & Quality Checks (`ci-test.yml`)

**Triggers:**
- Push to `main` or `develop` branches
- Pull requests to `main` or `develop`
- Manual trigger via workflow dispatch

**Jobs:**
- **test**: Runs test suite on Python 3.10, 3.11, and 3.12
  - Installs dependencies
  - Creates test environment
  - Runs database migrations
  - Executes pytest with coverage
  - Uploads coverage to Codecov (Python 3.12 only)

- **lint**: Code quality checks
  - Ruff (fast Python linter)
  - Black (code formatting)
  - isort (import sorting)
  - mypy (type checking)

- **security**: Security scanning
  - Bandit (security linter)
  - Safety (dependency vulnerability check)

- **integration-test**: End-to-end integration tests
  - Runs full reconciliation workflow tests
  - Tests batch processing and API endpoints

- **build-status**: Summary job that reports overall build status

### 2. CD - Deployment (`cd-deploy.yml`)

**Triggers:**
- Push to `main` branch
- Version tags (v*.*.*)
- Manual trigger with environment selection

**Jobs:**
- **build-and-push**: Builds Docker image and pushes to GitHub Container Registry
  - Uses Docker Buildx for efficient builds
  - Caches layers for faster subsequent builds
  - Tags images with version, branch, and SHA

- **deploy-staging**: Deploys to staging environment
  - Triggered on main branch commits
  - Runs smoke tests after deployment

- **deploy-production**: Deploys to production
  - Triggered on version tags or manual workflow
  - Requires staging deployment to succeed
  - Includes rollback logic on failure

- **release**: Creates GitHub release
  - Generates changelog from commits
  - Attaches artifacts
  - Only runs on version tags

### 3. Scheduled Tests & Maintenance (`scheduled-tests.yml`)

**Triggers:**
- Daily at 2 AM UTC
- Manual trigger

**Jobs:**
- **scheduled-tests**: Nightly full test suite
  - Runs all tests with parallelization
  - Performance benchmarks
  - Notifications on failure

- **dependency-audit**: Security audit
  - Safety check for known vulnerabilities
  - pip-audit for dependency issues
  - Lists outdated packages

- **database-migration-test**: Migration verification
  - Tests migration up/down/re-up
  - Verifies database schema integrity

### 4. PR Checks (`pr-checks.yml`)

**Triggers:**
- Pull request opened, synchronized, reopened, or marked ready for review

**Jobs:**
- **pr-validation**: Validates PR metadata
  - Checks PR title format (conventional commits)
  - Detects large files
  - Scans for potential secrets
  - Warns on large PRs

- **test-on-pr**: Quick test suite
  - Runs tests in parallel with fail-fast
  - Comments results on PR
  - Faster feedback for developers

- **code-review**: Automated code analysis
  - Cyclomatic complexity
  - Maintainability index
  - Code metrics

## 🔧 Setup Instructions

### 1. Repository Secrets

Configure the following secrets in your GitHub repository settings:

**Required:**
- `CODECOV_TOKEN`: Token for Codecov coverage reporting (optional but recommended)

**Optional (for deployment):**
- `DEPLOY_SSH_KEY`: SSH key for deployment to servers
- `STAGING_SERVER`: Staging server hostname
- `PRODUCTION_SERVER`: Production server hostname
- Custom secrets for your deployment infrastructure

### 2. Environment Configuration

Create GitHub Environments for deployment workflows:
1. Go to Settings → Environments
2. Create `staging` and `production` environments
3. Add environment-specific secrets if needed
4. Configure protection rules (approvals, branch restrictions)

### 3. Enable GitHub Container Registry

To use the Docker build and push functionality:
1. Enable GitHub Packages in your repository
2. Ensure the workflow has `packages: write` permission (already configured)

### 4. Codecov Integration (Optional)

To enable coverage reporting:
1. Sign up at [codecov.io](https://codecov.io)
2. Add your repository
3. Copy the upload token
4. Add it as `CODECOV_TOKEN` secret in GitHub

## 🚀 Usage

### Running Tests Locally

Before pushing, you can run tests locally to match CI:

```bash
cd reconcile-agent

# Install dependencies
pip install -r requirements.txt
pip install pytest-cov ruff black isort mypy

# Run tests
pytest tests/ -v --cov=app

# Run linting
ruff check app/ tests/
black --check app/ tests/
isort --check-only app/ tests/
mypy app/ --ignore-missing-imports
```

### Manual Workflow Triggers

You can manually trigger workflows from the GitHub Actions tab:
1. Go to Actions tab
2. Select the workflow
3. Click "Run workflow"
4. Fill in any required inputs
5. Click "Run workflow"

### Creating a Release

To trigger a production deployment:

```bash
# Tag the release
git tag -a v1.0.0 -m "Release version 1.0.0"
git push origin v1.0.0
```

This will:
1. Trigger CI tests
2. Build and push Docker image
3. Deploy to staging
4. Deploy to production (requires approval if configured)
5. Create GitHub release with changelog

## 📊 Status Badges

Add these badges to your README.md:

```markdown
![CI Tests](https://github.com/YOUR_USERNAME/Razorpay/workflows/CI%20-%20Testing%20%26%20Quality%20Checks/badge.svg)
![CD Deploy](https://github.com/YOUR_USERNAME/Razorpay/workflows/CD%20-%20Deployment/badge.svg)
![Scheduled Tests](https://github.com/YOUR_USERNAME/Razorpay/workflows/Scheduled%20Tests%20%26%20Maintenance/badge.svg)
[![codecov](https://codecov.io/gh/YOUR_USERNAME/Razorpay/branch/main/graph/badge.svg)](https://codecov.io/gh/YOUR_USERNAME/Razorpay)
```

## 🔍 Troubleshooting

### Tests Failing in CI but Passing Locally

- Ensure you're using the same Python version as CI (3.12)
- Check for environment-specific issues (file paths, line endings)
- Review the CI logs for detailed error messages

### Docker Build Failures

- Check Dockerfile syntax
- Ensure all required files are not in `.dockerignore`
- Review build logs for missing dependencies

### Deployment Issues

- Verify environment secrets are correctly set
- Check deployment scripts for errors
- Review server logs if deployment succeeds but app fails

### Rate Limiting Issues

If you hit GitHub API rate limits:
- Use personal access token for authentication
- Reduce frequency of scheduled jobs
- Use caching to reduce API calls

## 📝 Best Practices

1. **Keep workflows fast**: Use caching, parallel jobs, and fail-fast strategies
2. **Test before merging**: Always run tests on PRs
3. **Use semantic versioning**: Follow semver for releases
4. **Monitor workflows**: Set up notifications for failed workflows
5. **Keep secrets secure**: Never commit secrets, always use GitHub Secrets
6. **Document changes**: Update this README when modifying workflows

## 🔗 Additional Resources

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Docker Best Practices](https://docs.docker.com/develop/dev-best-practices/)
- [Pytest Documentation](https://docs.pytest.org/)
- [Codecov Documentation](https://docs.codecov.com/)

## 🤝 Contributing

When modifying workflows:
1. Test changes in a feature branch
2. Use `workflow_dispatch` trigger for testing
3. Document changes in this README
4. Consider backward compatibility
5. Update status badge links if renaming workflows
