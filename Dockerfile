# AgentScope API server. Mount your runs directory at /app/runs.
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY sdk ./sdk
RUN pip install --no-cache-dir .

EXPOSE 8724
CMD ["agentscope", "serve", "--host", "0.0.0.0", "--db", "runs/agentscope.db"]
