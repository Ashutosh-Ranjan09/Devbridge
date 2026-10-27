# The only place candidate code runs. Built once: `assess sandbox build`.
#
# Same pytest and pytest-timeout versions the validator uses, so a test means the same
# thing when the reference is checked and when a candidate is scored.
FROM python:3.12-slim

RUN pip install --no-cache-dir pytest==9.1.1 pytest-timeout==2.4.0 \
 && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin candidate

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /work
USER 10001
