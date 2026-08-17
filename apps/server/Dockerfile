FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install -e .

COPY . .

EXPOSE 8000
CMD ["sh", "-c", "python -m app.initdb && python -m app.seed && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
