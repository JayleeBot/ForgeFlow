# Runs the continuous poller: `managed_agent run` loops every 60s, which neither
# a Butterbase function (300s ceiling) nor a GitHub Actions job can host.
# The agent loop still runs on Anthropic; this container only executes the
# host-side tools, so it needs the Outlook and Butterbase credentials.
FROM python:3.11-slim

# curl is for the healthcheck; nothing in the app shells out.
RUN apt-get update && apt-get install --no-install-recommends -y curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first so a source edit doesn't invalidate the pip layer.
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

# Never run the agent's host-side tools as root.
RUN useradd --create-home --uid 10001 forgeflow
USER forgeflow

ENV PYTHONUNBUFFERED=1

# `run` polls forever. Override with `scan` for one pass, or `health` to check
# credentials without starting work:
#   docker run --env-file .env forgeflow health
ENTRYPOINT ["python", "-m", "forgeflow.managed_agent"]
CMD ["run"]
