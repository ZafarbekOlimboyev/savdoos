FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install -e .

COPY . .

# start.sh Windows'da yaratilgan bo'lsa CRLF bo'lishi mumkin — LF ga o'tkazamiz
RUN sed -i 's/\r$//' start.sh && chmod +x start.sh

# Railway $PORT beradi — bo'lmasa 8000. start.sh orqali (shell doim to'liq o'qiydi: initdb + seed + uvicorn)
CMD ["sh", "start.sh"]
