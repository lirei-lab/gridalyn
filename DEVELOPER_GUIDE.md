# Developer Guide

This guide provides instructions for developers on coding standards, validation, and the pre-commit process to ensure code quality and consistency across the project.

## Coding and Validation Workflow

To maintain a high standard of code, we use a combination of linting, formatting, and type-checking tools. These are enforced through a pre-commit framework that automatically runs checks before any code is committed.

### 1. Code Formatting

We use `black` for code formatting and `isort` for organizing imports. These tools ensure a consistent and readable code style.

- **black**: An uncompromising code formatter that enforces a strict and uniform style.
- **isort**: A Python utility to sort imports alphabetically and automatically separate them into sections.

### 2. Linting and Static Analysis

We use `flake8` for linting and `mypy` for static type checking to catch errors before they become bugs.

- **flake8**: A tool that checks your code against PEP 8 style guidelines, programming errors, and code complexity.
- **mypy**: A static type checker for Python that helps identify type-related errors, improving code reliability.

### 3. Pre-commit Validation

All of these checks are integrated into a pre-commit framework, which automates the validation process. Before committing any changes, the pre-commit hooks will run and prevent the commit if any issues are found.

To run all checks manually, execute the following command:

```bash
uv run pre-commit run --all-files
```

If any of the checks fail, they will report the issues to the console. You must fix these issues before you can successfully commit your changes. This ensures that all code in our repository adheres to our quality standards.