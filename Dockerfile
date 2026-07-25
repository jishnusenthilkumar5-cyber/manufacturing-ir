FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md CHANGELOG.md ./
COPY mir ./mir
COPY webapp ./webapp
COPY examples ./examples

RUN pip install --no-cache-dir ".[web]"

EXPOSE 8000

CMD ["uvicorn", "webapp.server:app", "--host", "0.0.0.0", "--port", "8000"]
