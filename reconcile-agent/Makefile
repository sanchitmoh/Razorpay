# Makefile for Razorpay Reconciliation Agent
# Windows users: Use 'make' if you have it installed, or run commands directly

.PHONY: help install install-dev test test-cov test-fast lint format security clean run migrate docker-build docker-run

# Default target
help:
	@echo "Razorpay Reconciliation Agent - Available Commands"
	@echo "=================================================="
	@echo "Setup:"
	@echo "  make install        - Install production dependencies"
	@echo "  make install-dev    - Install development dependencies"
	@echo "  make setup          - Full setup (install + migrate)"
	@echo ""
	@echo "Testing:"
	@echo "  make test           - Run all tests"
	@echo "  make test-cov       - Run tests with coverage report"
	@echo "  make test-fast      - Run tests in parallel"
	@echo "  make test-unit      - Run unit tests only"
	@echo "  make test-integration - Run integration tests only"
	@echo ""
	@echo "Code Quality:"
	@echo "  make lint           - Run all linters"
	@echo "  make format         - Format code with black and isort"
	@echo "  make typecheck      - Run mypy type checker"
	@echo "  make security       - Run security scans"
	@echo "  make complexity     - Check code complexity"
	@echo ""
	@echo "Development:"
	@echo "  make run            - Run development server"
	@echo "  make migrate        - Run database migrations"
	@echo "  make migrate-down   - Rollback migrations"
	@echo "  make clean          - Clean generated files"
	@echo ""
	@echo "Docker:"
	@echo "  make docker-build   - Build Docker image"
	@echo "  make docker-run     - Run Docker container"
	@echo "  make docker-clean   - Remove Docker containers and images"
	@echo ""
	@echo "Pre-commit:"
	@echo "  make pre-commit-install - Install pre-commit hooks"
	@echo "  make pre-commit-run     - Run pre-commit on all files"

# Installation
install:
	pip install -r requirements.txt

install-dev:
	pip install -r requirements.txt
	pip install -r requirements-dev.txt

setup: install-dev migrate
	@echo "Setup complete! Run 'make run' to start the server"

# Testing
test:
	pytest tests/ -v

test-cov:
	pytest tests/ -v --cov=app --cov-report=html --cov-report=term

test-fast:
	pytest tests/ -v -n auto

test-unit:
	pytest tests/ -v -m unit

test-integration:
	pytest tests/ -v -m integration

test-security:
	pytest tests/ -v -m security

test-watch:
	pytest-watch tests/ -v

# Code Quality
lint:
	@echo "Running Ruff..."
	ruff check app/ tests/
	@echo "Running Black check..."
	black --check app/ tests/
	@echo "Running isort check..."
	isort --check-only app/ tests/

format:
	@echo "Formatting with Black..."
	black app/ tests/
	@echo "Sorting imports with isort..."
	isort app/ tests/
	@echo "Auto-fixing with Ruff..."
	ruff check --fix app/ tests/

typecheck:
	mypy app/ --ignore-missing-imports

security:
	@echo "Running Bandit security scan..."
	bandit -r app/ -ll
	@echo "Running Safety dependency check..."
	safety check --json --file requirements.txt || true

complexity:
	@echo "Cyclomatic Complexity:"
	radon cc app/ -a -nb
	@echo ""
	@echo "Maintainability Index:"
	radon mi app/ -nb

# Development
run:
	uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

run-prod:
	uvicorn app.main:app --host 0.0.0.0 --port 8000

migrate:
	alembic upgrade head

migrate-down:
	alembic downgrade -1

migrate-reset:
	alembic downgrade base
	alembic upgrade head

# Database
db-shell:
	sqlite3 reconcile.db

# Clean
clean:
	@echo "Cleaning generated files..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .coverage htmlcov/ .mypy_cache .ruff_cache
	rm -f reconcile.db test_reconcile.db
	@echo "Clean complete!"

# Docker
docker-build:
	docker build -t reconcile-agent:latest .

docker-run:
	docker run -p 8000:8000 --env-file .env reconcile-agent:latest

docker-compose-up:
	docker-compose up -d

docker-compose-down:
	docker-compose down

docker-clean:
	docker-compose down -v
	docker rmi reconcile-agent:latest || true

# Pre-commit
pre-commit-install:
	pre-commit install

pre-commit-run:
	pre-commit run --all-files

# CI Simulation
ci-local: format lint typecheck security test-cov
	@echo "✅ All CI checks passed!"

# Utilities
check-connections:
	python test_connections.py

check-env:
	@echo "Checking environment configuration..."
	@python -c "from app.core.config import settings; print('✅ Configuration loaded successfully')" || echo "❌ Configuration error"

version:
	@python -c "from app.main import app; print(app.version)"

# Development helpers
seed-data:
	python scripts/generate_synthetic_data.py

seed-razorpay:
	python scripts/seed_razorpay_test_account.py
