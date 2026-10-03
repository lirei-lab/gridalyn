FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /workspace

RUN pip install \
    mkdocs>=1.6.1 \
    mkdocs-material>=9.6.17 \
    pymdown-extensions>=10.0

EXPOSE 8090

CMD ["mkdocs", "serve", "-f", "docs/mkdocs.yml", "-a", "0.0.0.0:8090"]