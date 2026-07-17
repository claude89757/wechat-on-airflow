FROM python:3.12-slim@sha256:804ddf3251a60bbf9c92e73b7566c40428d54d0e79d3428194edf40da6521286

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home app

WORKDIR /app

COPY docker/sender/requirements.lock .
RUN python -m pip install --no-cache-dir --requirement requirements.lock

COPY --chown=app:app sender_agent sender_agent
COPY --chown=app:app wechat_sender wechat_sender

USER 10001:10001

EXPOSE 7001

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7001/healthz', timeout=3)"]

CMD ["uvicorn", "sender_agent.app:app", "--host", "0.0.0.0", "--port", "7001", "--workers", "1"]
