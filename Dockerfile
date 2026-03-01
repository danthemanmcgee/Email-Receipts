# Stage 1: builder – install Python dependencies with compile-time tools
FROM python:3.12-slim AS builder

# Set ENABLE_WEASYPRINT=true at build time to include the optional WeasyPrint
# HTML-to-PDF dependency (requires extra native libraries in the runtime stage).
# Default: false — WeasyPrint is NOT installed.
ARG ENABLE_WEASYPRINT=false

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-optional.txt ./
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt \
    && if [ "$ENABLE_WEASYPRINT" = "true" ]; then \
         pip install --no-cache-dir --prefix=/install -r requirements-optional.txt; \
       fi

# Stage 2: runtime – slim image without build tools
FROM python:3.12-slim AS runtime

# Re-declare so the value is visible in this stage
ARG ENABLE_WEASYPRINT=false

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Always install libpq5 for PostgreSQL.
# WeasyPrint's native libraries (libpango, libcairo, etc.) are only added
# when ENABLE_WEASYPRINT=true is passed at build time.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && if [ "$ENABLE_WEASYPRINT" = "true" ]; then \
         apt-get install -y --no-install-recommends \
             libpango-1.0-0 \
             libpangocairo-1.0-0 \
             libcairo2 \
             libgdk-pixbuf-2.0-0 \
             libffi8 \
             shared-mime-info; \
       fi \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local
COPY . .

RUN useradd --no-create-home --shell /bin/false appuser \
    && mkdir -p /tmp/receipts \
    && chown appuser /tmp/receipts

USER appuser

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
