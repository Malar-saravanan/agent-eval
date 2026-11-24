FROM python:3.12-slim
ENV DEBIAN_FRONTEND=noninteractive PATH="/root/.local/bin:/root/.hermes/bin:/usr/local/bin:$PATH"
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl git ca-certificates ripgrep xz-utils sqlite3 nodejs npm bash \
    && apt-get clean
RUN npm install -g opencode-ai
# Hermes Agent (official installer)
RUN curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
# Agents run as unprivileged per-trial users: they must be able to execute the harnesses installed under /root.
RUN chmod 755 /root && chmod -R a+rX /root/.hermes /root/.local && mkdir -p /opt/cache && chmod 777 /opt/cache
ENV XDG_CACHE_HOME=/opt/cache
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
WORKDIR /app
COPY . /app
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
