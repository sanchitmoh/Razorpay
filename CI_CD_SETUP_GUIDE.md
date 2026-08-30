# CI/CD Pipeline Setup Guide

Complete guide for setting up and using the GitHub Actions CI/CD pipeline for the Razorpay Reconciliation Agent.

---

## 📋 Table of Contents

- [Quick Start (5 Steps)](#quick-start-5-steps)
- [Architecture Overview](#architecture-overview)
- [What's Included](#whats-included)
- [Detailed Setup](#detailed-setup)
- [Configuration](#configuration)
- [Testing the Pipeline](#testing-the-pipeline)
- [Troubleshooting](#troubleshooting)
- [Best Practices](#best-practices)

---

## 🚀 Quick Start (5 Steps)

Get your CI/CD pipeline running in under 30 minutes.

### Step 1: Verify Local Setup (5 minutes)

Run the verification script:

```powershell
cd "c:\class project\Razorpay"
.\verify_cicd_setup.ps1
```

Expected output: ✅ All checks passed!

### Step 2: Configure GitHub Secrets (5 minutes)

1. Go to your GitHub repository
2. Navigate to **Settings → Secrets and variables → Actions**
3. Click **New repository secret**
4. Add the following secrets:

**Required:**
```
RAZORPAY_KEY_ID=rzp_test_your_key_here
RAZORPAY_KEY_SECRET=your_secret_here
RAZORPAY_WEBHOOK_SECRET=whsec_your_webhook_secret
OPENROUTER_API_KEY=sk-or-your_key_here
GEMINI_API_KEY=your_gemini_key
```

**Optional:**
```
CODECOV_TOKEN=your_codecov_token (for coverage reporting)
SLACK_WEBHOOK_URL=your_webhook_url (for notifications)
```

### Step 3: Create GitHub Environments (5 minutes)

1. Go to **Settings → Environments**
2. Click **New environment**
3. Create `staging` environment:
   - Name: `staging`
   - Add URL (optional): `https://staging.your-domain.com`
4. Create `production` environment:
   - Name: `production`
   - Add URL (optional): `https://your-domain.com`
   - Enable **Required reviewers** (recommended)
   - Add yourself as a reviewer

### Step 4: Push Workflows to GitHub (2 minutes)

```powershell
# Add all CI/CD files
git add .github/ reconcile-agent/Dockerfile reconcile-agent/.dockerignore
git add reconcile-agent/docker-compose.yml reconcile-agent/pyproject.toml
git add reconcile-agent/.pre-commit-config.yaml CONTRIBUTING.md

# Commit
git commit -m "ci: add comprehensive GitHub Actions CI/CD pipeline

- Add CI test workflow with multi-version Python testing
- Add CD deployment workflow with Docker containerization
- Add scheduled tests for maintenance
- Add PR checks for code quality"

# Push to GitHub
git push origin main
```

### Step 5: Verify Workflows Run (3 minutes)

1. Go to your GitHub repository
2. Click on the **Actions** tab
3. You should see workflows running
4. Wait for workflows to complete
5. Check that all jobs pass ✅

---

## 🏗️ Architecture Overview

The CI/CD pipeline consists of four main workflows:

```
┌─────────────────────────────────────────────────────────────┐
│                     GitHub Actions CI/CD                     │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │   CI Tests   │  │  PR Checks   │  │  Scheduled   │      │
│  │ • Unit Tests │  │ • Validation │  │ • Nightly    │      │
│  │ • Linting    │  │ • Quick Test │  │ • Security   │      │
│  │ • Security   │  │ • Metrics    │  │ • Audit      │      │
│  │ • Coverage   │  └──────────────┘  └──────────────┘      │
│  └──────┬───────┘                                            │
│         ▼                                                    │
│  ┌──────────────┐                                            │
│  │ CD Deployment│                                            │
│  │ • Build      │──────┐                                    │
│  │ • Staging    │      │                                    │
│  │ • Production │      ▼                                    │
│  │ • Release    │  ┌──────────────┐                        │
│  └──────────────┘  │   Docker     │                        │
│                     │  Container   │                        │
│                     └──────────────┘                        │
└─────────────────────────────────────────────────────────────┘
```

### Workflow Files

Located in `.github/workflows/`:

1. **ci-test.yml** - Main CI pipeline with testing, linting, security
2. **cd-deploy.yml** - Deployment pipeline with Docker containerization
3. **scheduled-tests.yml** - Nightly tests and dependency audits
4. **pr-checks.yml** - Pull request validation and automated reviews

---

## 📦 What's Included

### GitHub Actions Workflows (4 files)
- ✅ Multi-version Python testing (3.10, 3.11, 3.12)
- ✅ Code quality checks (Ruff, Black, isort, mypy)
- ✅ Security scanning (Bandit, Safety)
- ✅ Coverage reporting with Codecov
- ✅ Docker build and push to GHCR
- ✅ Multi-environment deployment
- ✅ PR validation and metrics

### Docker Configuration (3 files)
- ✅ **Dockerfile** - Multi-stage production-ready container
- ✅ **.dockerignore** - Optimized build context
- ✅ **docker-compose.yml** - Local and production orchestration

### Python Configuration (5 files)
- ✅ **pyproject.toml** - Tool configurations (pytest, black, ruff, mypy)
- ✅ **.pre-commit-config.yaml** - Pre-commit hooks
- ✅ **requirements-dev.txt** - Development dependencies
- ✅ **Makefile** - Convenient command shortcuts
- ✅ **verify_cicd_setup.ps1** - Setup verification script

### Documentation
- ✅ **CONTRIBUTING.md** - Developer guidelines
- ✅ **.github/workflows/README.md** - Workflow documentation
- ✅ **CI_CD_SETUP_GUIDE.md** - This guide

---

## 🔧 Detailed Setup

### Prerequisites

Before enabling CI/CD, ensure you have:

- [ ] GitHub repository with admin access
- [ ] Python 3.10+ installed locally
- [ ] Git installed and configured
- [ ] (Optional) Docker installed for local testing
- [ ] Razorpay test account credentials
- [ ] LLM API keys (OpenRouter or Gemini)

### Enable GitHub Actions

1. Go to **Settings → Actions → General**
2. Enable "Allow all actions and reusable workflows"
3. Set workflow permissions to "Read and write permissions"
4. Enable "Allow GitHub Actions to create and approve pull requests"

### Enable GitHub Container Registry

1. Go to **Settings → Packages**
2. Ensure package visibility is set appropriately
3. No additional configuration needed - workflows will automatically push to GHCR

### Add Status Badges to README

```markdown
## CI/CD Status

![CI Tests](https://github.com/YOUR_USERNAME/Razorpay/workflows/CI%20-%20Testing%20%26%20Quality%20Checks/badge.svg)
![CD Deploy](https://github.com/YOUR_USERNAME/Razorpay/workflows/CD%20-%20Deployment/badge.svg)
[![codecov](https://codecov.io/gh/YOUR_USERNAME/Razorpay/branch/main/graph/badge.svg)](https://codecov.io/gh/YOUR_USERNAME/Razorpay)
```

---

## 🧪 Testing the Pipeline

### Test 1: Create a Test PR

```powershell
# Create a test branch
git checkout -b test/ci-pipeline

# Make a small change
echo "# CI/CD Test" >> reconcile-agent/README.md

# Commit and push
git add reconcile-agent/README.md
git commit -m "test: verify CI/CD pipeline"
git push origin test/ci-pipeline
```

Then:
1. Go to GitHub and create a PR
2. Watch the PR checks run
3. Verify all checks pass
4. Close the PR (don't merge)

### Test 2: Run Workflows Manually

1. Go to **Actions** tab
2. Select **CI - Testing & Quality Checks**
3. Click **Run workflow**
4. Select branch: `main`
5. Click **Run workflow**
6. Watch it complete successfully

### Test 3: Test Docker Build Locally

```powershell
cd reconcile-agent

# Build Docker image
docker build -t reconcile-agent:test .

# Run container
docker run -p 8000:8000 --env-file .env reconcile-agent:test

# Test endpoint (in another terminal)
curl http://localhost:8000/api/v1/health

# Stop container
docker ps  # Get container ID
docker stop <container-id>
```

---

## ⚙️ Configuration

### Customizing Test Matrix

Edit `.github/workflows/ci-test.yml`:

```yaml
strategy:
  matrix:
    python-version: ['3.10', '3.11', '3.12']  # Modify versions
    os: [ubuntu-latest]  # Add: windows-latest, macos-latest
```

### Adjusting Test Coverage Threshold

Add to `pyproject.toml`:

```toml
[tool.coverage.report]
fail_under = 80  # Fail if coverage below 80%
```

### Customizing Deployment

Edit `.github/workflows/cd-deploy.yml`:

```yaml
- name: Deploy to production
  run: |
    # SSH deployment
    ssh user@server "cd /app && docker pull $IMAGE && docker-compose up -d"
    
    # Kubernetes
    kubectl set image deployment/reconcile-agent app=$IMAGE
    
    # Google Cloud Run
    gcloud run deploy reconcile-agent --image $IMAGE
```

### Scheduling Adjustments

Edit `.github/workflows/scheduled-tests.yml`:

```yaml
schedule:
  - cron: '0 2 * * *'  # Daily at 2 AM UTC
  # Change to:
  - cron: '0 */6 * * *'  # Every 6 hours
  - cron: '0 0 * * 0'    # Weekly on Sunday
```

### Setting Up Notifications

Add Slack notifications to workflows:

```yaml
- name: Notify Slack on failure
  if: failure()
  uses: slackapi/slack-github-action@v1
  with:
    webhook-url: ${{ secrets.SLACK_WEBHOOK_URL }}
    payload: |
      {
        "text": "❌ CI Failed on ${{ github.repository }}",
        "blocks": [{
          "type": "section",
          "text": {
            "type": "mrkdwn",
            "text": "*Build Failed*\n<${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}|View Run>"
          }
        }]
      }
```

---

## 🐛 Troubleshooting

### Tests Pass Locally but Fail in CI

**Problem:** Tests work on your machine but fail in GitHub Actions

**Solution:**
1. Check Python version matches (use 3.12)
2. Review CI logs for error details
3. Test with same environment variables
4. Check for timezone or OS-specific issues

```powershell
# Use same Python version as CI
python --version
# Should be 3.12

# Run tests locally
pytest tests/ -v
```

### Docker Build Fails

**Problem:** Docker image build fails

**Solution:**
1. Test build locally: `docker build -t test .`
2. Check Dockerfile syntax
3. Verify `requirements.txt` exists
4. Review `.dockerignore` - ensure required files aren't excluded

### Secrets Not Working

**Problem:** Workflows fail with "secret not found"

**Solution:**
1. Go to Settings → Secrets → Actions
2. Verify secret names match exactly (case-sensitive)
3. Re-create secrets if needed
4. Check for trailing whitespace in values

### Workflows Not Appearing

**Problem:** No workflows show in Actions tab

**Solution:**
1. Verify `.github/workflows/*.yml` files are pushed
2. Check files have `.yml` extension (not `.yaml`)
3. Validate YAML syntax: https://www.yamllint.com/

### Can't Push to GitHub

**Problem:** Push rejected or permission denied

**Solution:**
1. Check you have write access to repository
2. Verify git remote: `git remote -v`
3. Check branch protection rules
4. Try SSH instead of HTTPS (or vice versa)

---

## 📈 Best Practices

### Development Workflow

1. **Always work on branches**
   ```powershell
   git checkout -b feature/my-new-feature
   ```

2. **Commit often with good messages**
   ```powershell
   git commit -m "feat: add new feature"
   ```

3. **Wait for CI to pass** before requesting review

4. **Address review feedback** and push updates

5. **Merge when approved** and CI is green

### Code Quality

- Run formatting before committing: `black app/ tests/`
- Run linting to catch issues: `ruff check app/ tests/`
- Run tests to verify changes: `pytest tests/ -v`
- Use pre-commit hooks: `pre-commit install`

### Testing

- Write tests for new features
- Maintain >80% code coverage
- Use markers: `@pytest.mark.unit`, `@pytest.mark.integration`
- Run fast tests during development: `pytest -m unit`

### Deployment

- Always deploy to staging first
- Run smoke tests after deployment
- Have a rollback plan
- Monitor logs after deployment

### Branch Protection

Configure in **Settings → Branches**:

```
Protection rules for main:
✅ Require pull request before merging
✅ Require approvals (1-2 reviewers)
✅ Require status checks to pass
✅ Require branches to be up to date
□ Allow force pushes (keep disabled)
```

---

## 🔒 Security Best Practices

1. **Never commit secrets** - Use GitHub Secrets
2. **Use environment variables** for configuration
3. **Enable branch protection** - Require PR reviews
4. **Regular dependency updates** - Use Dependabot
5. **Scan for vulnerabilities** - Included in workflows
6. **Principle of least privilege** - Minimize token permissions

### Enable Dependabot

Create `.github/dependabot.yml`:

```yaml
version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/reconcile-agent"
    schedule:
      interval: "weekly"
    open-pull-requests-limit: 10

  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
```

---

## 🎯 Success Criteria

Your CI/CD pipeline is properly set up when:

- ✅ All workflows run without errors
- ✅ Tests pass consistently in CI
- ✅ Coverage reports generate successfully
- ✅ Docker images build and push to registry
- ✅ Deployments complete without manual intervention
- ✅ Team receives notifications on failures
- ✅ PRs cannot merge until checks pass

---

## 📚 Additional Resources

### GitHub Actions
- [Quickstart Guide](https://docs.github.com/en/actions/quickstart)
- [Workflow Syntax](https://docs.github.com/en/actions/reference/workflow-syntax-for-github-actions)
- [Using Secrets](https://docs.github.com/en/actions/security-guides/encrypted-secrets)

### Docker
- [Get Started](https://docs.docker.com/get-started/)
- [Best Practices](https://docs.docker.com/develop/dev-best-practices/)

### Python Testing
- [pytest Documentation](https://docs.pytest.org/en/stable/)
- [Testing Best Practices](https://docs.python-guide.org/writing/tests/)

---

## 🆘 Getting Help

If you're stuck:

1. **Check the documentation** - most answers are already documented
2. **Review workflow logs** - GitHub Actions provides detailed logs
3. **Search GitHub Issues** - someone may have had the same problem
4. **Check .github/workflows/README.md** - detailed workflow documentation

---

## 🎉 Congratulations!

You've successfully set up a production-grade CI/CD pipeline! The pipeline will now:

- ✅ Test every code change automatically
- ✅ Enforce code quality standards
- ✅ Scan for security vulnerabilities
- ✅ Build and publish Docker images
- ✅ Deploy to staging and production
- ✅ Run nightly maintenance checks

**Happy coding! 🚀**
