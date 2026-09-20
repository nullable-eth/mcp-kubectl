FROM python:3.13-slim AS build
WORKDIR /src
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# kubectl, pinned and checksum-verified. Keep KUBECTL_VERSION within one minor
# of the cluster's API server (kubectl's supported skew).
FROM debian:bookworm-slim AS tools
ARG KUBECTL_VERSION=v1.36.4
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*
RUN set -eux; \
    base="https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64"; \
    curl -fsSL -o /usr/local/bin/kubectl "${base}/kubectl"; \
    curl -fsSL -o /tmp/kubectl.sha256 "${base}/kubectl.sha256"; \
    echo "$(cat /tmp/kubectl.sha256)  /usr/local/bin/kubectl" | sha256sum -c -; \
    chmod +x /usr/local/bin/kubectl; \
    kubectl version --client

FROM python:3.13-slim
COPY --from=build /install /usr/local
COPY --from=tools /usr/local/bin/kubectl /usr/local/bin/kubectl
COPY kubectlmcp/ /srv/kubectlmcp/
WORKDIR /srv
# HOME must be writable: kubectl writes a discovery cache under it.
ENV HOME=/tmp PORT=8080 PYTHONUNBUFFERED=1
USER 65534
EXPOSE 8080
CMD ["python", "-m", "kubectlmcp.server"]
