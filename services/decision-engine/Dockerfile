FROM python:3.11-slim as builder
WORKDIR /app
COPY services/shared/requirements.txt ./services/shared/
COPY services/decision-engine/requirements.txt ./services/decision-engine/
RUN pip install --no-cache-dir -r ./services/decision-engine/requirements.txt

FROM python:3.11-slim
RUN useradd -m -s /bin/bash appuser
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.11/site-packages/ /usr/local/lib/python3.11/site-packages/
COPY --from=builder /usr/local/bin/ /usr/local/bin/
COPY services ./services
RUN chown -R appuser:appuser /app
USER appuser
ENV PYTHONPATH=/app
WORKDIR /app/services/decision-engine

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
