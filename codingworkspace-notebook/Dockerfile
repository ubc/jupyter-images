# syntax=docker/dockerfile:1.7
# codingworkspace-notebook: a narrow JupyterHub single-user image. Jupyter
# Server provides Hub OAuth/activity and one authenticated named proxy only.
ARG BASE_CONTAINER=quay.io/jupyter/base-notebook:hub-5.5.0@sha256:e6f115af0bc688b884bec4e00523512deb808972e117797608fa1bf29931714a
FROM ${BASE_CONTAINER}

ARG TARGETARCH
ARG CW_REF
ARG GIZMOAPP_REF
ARG OPENCODE_VERSION
LABEL course="AI100" \
      org.opencontainers.image.base.name="quay.io/jupyter/base-notebook:hub-5.5.0@sha256:e6f115af0bc688b884bec4e00523512deb808972e117797608fa1bf29931714a" \
      org.codingworkspace.source-revision="${CW_REF}" \
      org.codingworkspace.starter-revision="${GIZMOAPP_REF}" \
      org.codingworkspace.node-version="22.23.2" \
      org.codingworkspace.opencode-version="${OPENCODE_VERSION}"

USER root

# Every downloaded runtime is version- and digest-pinned. Do not restore the
# mutable NodeSource setup script or OpenCode installer.
# The baseline x64 OpenCode binary avoids an unstated dependency on newer EKS
# CPU instruction sets. arm64 has no separate baseline release asset.
COPY codingworkspace-notebook/RUNTIME_PINS.env /tmp/codingworkspace-runtime-pins.env
RUN set -eux; \
    expected_opencode_version="${OPENCODE_VERSION}"; \
    . /tmp/codingworkspace-runtime-pins.env; \
    test "${OPENCODE_VERSION}" = "${expected_opencode_version}"; \
    install --owner=root --group=root --mode=0444 \
        /tmp/codingworkspace-runtime-pins.env /etc/codingworkspace-runtime-pins.env; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        "bubblewrap=${BUBBLEWRAP_APT_VERSION}" ca-certificates curl git xz-utils; \
    case "${TARGETARCH}" in \
        amd64) node_arch="x64"; node_sha256="${NODE_LINUX_AMD64_SHA256}"; opencode_arch="x64-baseline"; opencode_sha256="${OPENCODE_LINUX_AMD64_BASELINE_SHA256}" ;; \
        arm64) node_arch="arm64"; node_sha256="${NODE_LINUX_ARM64_SHA256}"; opencode_arch="arm64"; opencode_sha256="${OPENCODE_LINUX_ARM64_SHA256}" ;; \
        *) echo "Unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    node_archive="/tmp/node-v${NODE_VERSION}-linux-${node_arch}.tar.xz"; \
    curl --fail --location --retry 5 --output "${node_archive}" \
        "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${node_arch}.tar.xz"; \
    printf '%s  %s\n' "${node_sha256}" "${node_archive}" | sha256sum --check --strict; \
    tar --extract --xz --file "${node_archive}" --directory /usr/local --strip-components=1 --no-same-owner; \
    opencode_archive="/tmp/opencode-linux-${opencode_arch}.tar.gz"; \
    curl --fail --location --retry 5 --output "${opencode_archive}" \
        "https://github.com/anomalyco/opencode/releases/download/v${OPENCODE_VERSION}/opencode-linux-${opencode_arch}.tar.gz"; \
    printf '%s  %s\n' "${opencode_sha256}" "${opencode_archive}" | sha256sum --check --strict; \
    tar --extract --gzip --file "${opencode_archive}" --directory /tmp --no-same-owner opencode; \
    install --owner=root --group=root --mode=0755 /tmp/opencode /usr/local/bin/opencode; \
    test "$(node --version)" = "v${NODE_VERSION}"; \
    test "$(opencode --version)" = "${OPENCODE_VERSION}"; \
    bwrap --version; \
    apt-get clean; \
    rm -f "${node_archive}" "${opencode_archive}" /tmp/opencode /tmp/codingworkspace-runtime-pins.env; \
    rm -rf /var/lib/apt/lists/*

# CodingWorkspace handles imports. install-common.sh is intentionally omitted:
# it adds mutable notebook/Lab/grader extensions this profile never exposes.
# The pinned base lacks aiohttp; install the complete proxy runtime from
# reviewed amd64/arm64 Python 3.13 wheels without dependency resolution.
COPY codingworkspace-notebook/CW_REF /tmp/CW_REF
COPY --chown=${NB_UID}:${NB_GID} --chmod=0444 \
    codingworkspace-notebook/proxy-requirements.txt /tmp/proxy-requirements.txt
USER ${NB_UID}
RUN --mount=type=bind,from=cwsrc,target=/cwsrc \
    set -eux; \
    expected_ref="$(tr -d '[:space:]' < /tmp/CW_REF)"; \
    test "${CW_REF}" = "${expected_ref}"; \
    test "$(git -c safe.directory=/cwsrc -C /cwsrc rev-parse HEAD)" = "${expected_ref}"; \
    mkdir -p /tmp/cwbuild; \
    git -c safe.directory=/cwsrc -C /cwsrc archive --format=tar "${expected_ref}" \
        | tar -C /tmp/cwbuild -xf -; \
    pip install --no-cache-dir --no-deps --only-binary=:all: --require-hashes \
        --requirement /tmp/proxy-requirements.txt; \
    pip install --no-cache-dir --no-deps --no-build-isolation /tmp/cwbuild; \
    pip check; \
    python -c 'import importlib.metadata as m; assert m.version("jupyterhub") == "5.5.0"; assert m.version("jupyter-server-proxy") == "4.5.0"; assert m.version("aiohttp") == "3.14.3"; assert m.version("simpervisor") == "1.0.0"; assert m.version("notebook") == "7.6.1"; assert m.version("jupyterlab") == "4.6.2"'; \
    rm -rf /tmp/cwbuild; \
    rm -f /tmp/proxy-requirements.txt

# Sanitize a full-history exact starter context through upload-pack. This
# prevents CI checkout credentials/config from entering an image layer.
USER root
COPY codingworkspace-notebook/GIZMOAPP_REF /tmp/GIZMOAPP_REF
RUN --mount=type=bind,from=gizmosrc,target=/gizmosrc \
    set -eux; \
    expected_ref="$(tr -d '[:space:]' < /tmp/GIZMOAPP_REF)"; \
    test "${GIZMOAPP_REF}" = "${expected_ref}"; \
    test "$(git -c safe.directory=/gizmosrc -C /gizmosrc rev-parse HEAD)" = "${expected_ref}"; \
    test "$(git -c safe.directory=/gizmosrc -C /gizmosrc rev-parse --is-shallow-repository)" = "false"; \
    git -c safe.directory=/gizmosrc -C /gizmosrc diff --quiet; \
    git -c safe.directory=/gizmosrc -C /gizmosrc diff --cached --quiet; \
    test -z "$(git -c safe.directory=/gizmosrc -C /gizmosrc status --porcelain --untracked-files=normal)"; \
    install -d --owner=root --group=root --mode=0555 /opt/codingworkspace-starters; \
    git -c safe.directory=/gizmosrc clone --no-local --no-hardlinks \
        --upload-pack='git -c safe.directory=/gizmosrc upload-pack' \
        /gizmosrc /opt/codingworkspace-starters/GizmoApp; \
    test "$(git -C /opt/codingworkspace-starters/GizmoApp rev-parse HEAD)" = "${expected_ref}"; \
    git -C /opt/codingworkspace-starters/GizmoApp remote remove origin; \
    chown -R root:root /opt/codingworkspace-starters/GizmoApp; \
    find /opt/codingworkspace-starters/GizmoApp -type d -exec chmod 0555 '{}' +; \
    find /opt/codingworkspace-starters/GizmoApp -type f -exec chmod 0444 '{}' +; \
    rm -f /tmp/CW_REF /tmp/GIZMOAPP_REF

# Root-owned high-precedence config plus JupyterHub's user-config gate prevent
# retained-home configuration from re-enabling Jupyter features.
RUN install -d --owner=root --group=root --mode=0555 \
        /opt/codingworkspace-jupyter/config \
        /opt/codingworkspace-jupyter/runtime \
        /opt/codingworkspace-jupyter/empty-root; \
    install -d --owner=${NB_UID} --group=${NB_GID} --mode=0700 \
        /tmp/codingworkspace-jupyter-runtime; \
    install --owner=root --group=root --mode=0444 /dev/null \
        /opt/codingworkspace-jupyter/runtime/CodingWorkspace.env
COPY --chown=root:root --chmod=0444 codingworkspace-notebook/codingworkspace_jupyter_runtime.py \
    /opt/codingworkspace-jupyter/runtime/codingworkspace_jupyter_runtime.py
COPY --chown=root:root --chmod=0444 codingworkspace-notebook/codingworkspace_server_proxy_config.py \
    /opt/codingworkspace-jupyter/config/jupyter_server_config.py
COPY --chown=root:root --chmod=0555 codingworkspace-notebook/codingworkspace_prestop.py \
    /usr/local/sbin/codingworkspace-prestop

ENV JUPYTERHUB_SINGLEUSER_APP=jupyter_server.serverapp.ServerApp \
    JUPYTERHUB_DISABLE_USER_CONFIG=1 \
    JUPYTERHUB_DEFAULT_URL=/codingworkspace/ \
    JUPYTER_CONFIG_DIR=/opt/codingworkspace-jupyter/config \
    JUPYTER_RUNTIME_DIR=/tmp/codingworkspace-jupyter-runtime \
    PYTHONNOUSERSITE=1 \
    PYTHONSAFEPATH=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    OPENCODE_DISABLE_AUTOUPDATE=1 \
    HOME=/home/jovyan

USER ${NB_UID}
WORKDIR /opt/codingworkspace-jupyter/empty-root
