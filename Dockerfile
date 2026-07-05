FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY portfolio_monitor ./portfolio_monitor
COPY config ./config

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir ".[pdf,excel]"

ENTRYPOINT ["portfolio-monitor"]
CMD ["--help"]
