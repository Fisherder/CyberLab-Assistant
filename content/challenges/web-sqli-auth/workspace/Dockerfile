FROM debian:bookworm-slim
RUN useradd -m -u 10001 student \
    && apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates curl python3 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /workspace
USER student
ENV TARGET_BASE_URL=http://target:8080
CMD ["/bin/bash"]
