FROM python:3.9-slim

WORKDIR /app

# Install tini - a proper init process for containers
RUN apt-get update && apt-get install -y --no-install-recommends tini && rm -rf /var/lib/apt/lists/*

COPY chatroom_server.py .

RUN pip install fastapi uvicorn

EXPOSE 8890

# Use tini as the entry point with exec form
ENTRYPOINT ["/usr/bin/tini", "-s", "--"]
CMD ["python", "chatroom_server.py"] 