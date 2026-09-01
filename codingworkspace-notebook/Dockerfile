# syntax=docker/dockerfile:1.7
# codingworkspace-notebook: a narrow JupyterHub single-user image. Jupyter
# Server provides Hub OAuth/activity and one authenticated named proxy only.
ARG BASE_CONTAINER=quay.io/jupyter/base-notebook:hub-5.5.0@sha256:e6f115af0bc688b884bec4e00523512deb808972e117797608fa1bf29931714a
FROM ${BASE_CONTAINER} AS codingworkspace-wheelhouse-build

ARG TARGETARCH
ARG GIZMOAPP_REF
ARG OPENCODE_VERSION
ARG DEPENDENCY_WHEELHOUSE_LAYER_VERSION
ARG DEPENDENCY_BUILDER_REF
ARG DEPENDENCY_BUILDER_BLOB
ARG DEPENDENCY_WHEEL_INDEX_URL
LABEL course="AI100" \
      org.opencontainers.image.base.name="quay.io/jupyter/base-notebook:hub-5.5.0@sha256:e6f115af0bc688b884bec4e00523512deb808972e117797608fa1bf29931714a" \
      org.codingworkspace.node-version="22.23.2" \
      org.codingworkspace.opencode-version="${OPENCODE_VERSION}"

USER root

# Every downloaded runtime is version- and digest-pinned. Do not restore the
# mutable NodeSource setup script or OpenCode installer.
# The baseline x64 OpenCode binary avoids an unstated dependency on newer EKS
# CPU instruction sets. This reviewed release is explicitly amd64-only.
COPY codingworkspace-notebook/RUNTIME_PINS.env /tmp/codingworkspace-runtime-pins.env
COPY codingworkspace-notebook/DEPENDENCY_LAYER.env /tmp/codingworkspace-dependency-layer.env
RUN set -eux; \
    expected_opencode_version="${OPENCODE_VERSION}"; \
    expected_dependency_layer_version="${DEPENDENCY_WHEELHOUSE_LAYER_VERSION}"; \
    expected_dependency_builder_ref="${DEPENDENCY_BUILDER_REF}"; \
    expected_dependency_builder_blob="${DEPENDENCY_BUILDER_BLOB}"; \
    expected_dependency_wheel_index_url="${DEPENDENCY_WHEEL_INDEX_URL}"; \
    . /tmp/codingworkspace-runtime-pins.env; \
    . /tmp/codingworkspace-dependency-layer.env; \
    test "${OPENCODE_VERSION}" = "${expected_opencode_version}"; \
    test "${DEPENDENCY_WHEELHOUSE_LAYER_VERSION}" = "${expected_dependency_layer_version}"; \
    test "${DEPENDENCY_BUILDER_REF}" = "${expected_dependency_builder_ref}"; \
    test "${DEPENDENCY_BUILDER_BLOB}" = "${expected_dependency_builder_blob}"; \
    test "${DEPENDENCY_WHEEL_INDEX_URL}" = "${expected_dependency_wheel_index_url}"; \
    install --owner=root --group=root --mode=0444 \
        /tmp/codingworkspace-runtime-pins.env /etc/codingworkspace-runtime-pins.env; \
    install --owner=root --group=root --mode=0444 \
        /tmp/codingworkspace-dependency-layer.env \
        /etc/codingworkspace-dependency-layer.env; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        "bubblewrap=${BUBBLEWRAP_APT_VERSION}" ca-certificates curl git xz-utils; \
    test "${TARGETARCH}" = "amd64"; \
    case "${TARGETARCH}" in \
        amd64) node_arch="x64"; node_sha256="${NODE_LINUX_AMD64_SHA256}"; opencode_arch="x64-baseline"; opencode_sha256="${OPENCODE_LINUX_AMD64_BASELINE_SHA256}" ;; \
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
    mkdir -p /tmp/opencode-dist; \
    tar --extract --gzip --file "${opencode_archive}" --directory /tmp/opencode-dist --no-same-owner opencode; \
    install --owner=root --group=root --mode=0755 /tmp/opencode-dist/opencode /usr/local/bin/opencode; \
    test "$(node --version)" = "v${NODE_VERSION}"; \
    test "$(opencode --version)" = "${OPENCODE_VERSION}"; \
    bwrap --version; \
    apt-get clean; \
    rm -rf "${node_archive}" "${opencode_archive}" /tmp/opencode-dist /tmp/opencode \
        /tmp/codingworkspace-runtime-pins.env \
        /tmp/codingworkspace-dependency-layer.env; \
    rm -rf /var/lib/apt/lists/*

# Reconstruct the full-history exact starter from its bundle-only context. The
# bundle contains Git objects, not CI checkout credentials or configuration.
USER root
COPY codingworkspace-notebook/GIZMOAPP_REF /tmp/GIZMOAPP_REF
RUN --mount=type=bind,from=gizmosrc,target=/gizmosrc \
    set -eux; \
    expected_ref="$(sed -e 's/[[:space:]]//g' -e '/^$/d' -e '/^#/d' /tmp/GIZMOAPP_REF)"; \
    test "${#expected_ref}" -eq 40; \
    printf '%s' "${expected_ref}" | grep -Eq '^[0-9a-f]{40}$'; \
    test "${GIZMOAPP_REF}" = "${expected_ref}"; \
    test "$(git bundle list-heads /gizmosrc/source.bundle)" = "${expected_ref} HEAD"; \
    install -d --owner=root --group=root --mode=0555 /opt/codingworkspace-starters; \
    git clone --quiet --no-local --no-hardlinks /gizmosrc/source.bundle \
        /opt/codingworkspace-starters/GizmoApp; \
    test "$(git -C /opt/codingworkspace-starters/GizmoApp rev-parse HEAD)" = "${expected_ref}"; \
    test "$(git -C /opt/codingworkspace-starters/GizmoApp rev-parse --is-shallow-repository)" = "false"; \
    test -z "$(git -C /opt/codingworkspace-starters/GizmoApp status --porcelain --untracked-files=normal)"; \
    git -C /opt/codingworkspace-starters/GizmoApp remote remove origin; \
    chown -R root:root /opt/codingworkspace-starters/GizmoApp; \
    find /opt/codingworkspace-starters/GizmoApp -type d -exec chmod 0555 '{}' +; \
    find /opt/codingworkspace-starters/GizmoApp -type f -exec chmod 0444 '{}' +; \
    # The starter stays root-owned and read-only on purpose, but the notebook
    # user must still be able to clone it: CODINGWORKSPACE_STARTER_REPO_URL
    # points here, and git refuses to read a repository owned by another user
    # ("detected dubious ownership") unless it is marked safe. Both entries are
    # required - marking only the work tree still fails on the .git directory.
    git config --system --add safe.directory /opt/codingworkspace-starters/GizmoApp; \
    git config --system --add safe.directory /opt/codingworkspace-starters/GizmoApp/.git; \
    rm -f /tmp/GIZMOAPP_REF

# Build the architecture-specific binary wheelhouse with the exact interpreter
# that runs CodingWorkspace. The reviewed builder is a file-only context
# extracted from its immutable private-repository commit; no checkout metadata,
# Git configuration, or source credential reaches BuildKit.
RUN install -d --owner=root --group=root --mode=0555 \
    /opt/codingworkspace-jupyter/runtime
COPY --chown=root:root --chmod=0444 \
    codingworkspace-notebook/codingworkspace_dependency_contract.py \
    /opt/codingworkspace-jupyter/runtime/codingworkspace_dependency_contract.py
RUN --mount=type=bind,from=cwbuildersrc,target=/cwbuildersrc \
    set -eux; \
    test "$(git hash-object /cwbuildersrc/build_dependency_wheelhouse.py)" \
        = "${DEPENDENCY_BUILDER_BLOB}"; \
    install --owner=root --group=root --mode=0444 \
        /cwbuildersrc/build_dependency_wheelhouse.py \
        /tmp/build_dependency_wheelhouse.py; \
    dependency_probe_id="codingworkspace-wheelhouse-probe-${DEPENDENCY_WHEELHOUSE_LAYER_VERSION}"; \
    env -u PIP_EXTRA_INDEX_URL \
        PIP_CONFIG_FILE=/dev/null \
        PIP_INDEX_URL="${DEPENDENCY_WHEEL_INDEX_URL}" \
        /opt/conda/bin/python /tmp/build_dependency_wheelhouse.py \
        --requirements /opt/codingworkspace-starters/GizmoApp/server/requirements.txt \
        --install-script /opt/codingworkspace-starters/GizmoApp/scripts/install_checkout.sh \
        --output-dir /opt/codingworkspace-dependency-wheelhouse \
        --runtime-id "${dependency_probe_id}"; \
    dependency_runtime_id="$( \
        PYTHONPATH=/opt/codingworkspace-jupyter/runtime \
        /opt/conda/bin/python -c \
        'import sys; from pathlib import Path; from codingworkspace_dependency_contract import finalize_dependency_manifest; print(finalize_dependency_manifest(Path(sys.argv[1]), sys.argv[2])["runtime_id"])' \
        /opt/codingworkspace-dependency-wheelhouse/manifest.json \
        "${DEPENDENCY_WHEELHOUSE_LAYER_VERSION}" \
    )"; \
    PYTHONPATH=/opt/codingworkspace-jupyter/runtime \
        /opt/conda/bin/python -c \
        'import sys; from pathlib import Path; from codingworkspace_dependency_contract import dependency_manifest_metadata; metadata = dependency_manifest_metadata(Path(sys.argv[1]).read_bytes(), sys.argv[2], require_current_python=True); sys.exit("finalized dependency runtime ID mismatch") if metadata["runtime_id"] != sys.argv[3] else None' \
        /opt/codingworkspace-dependency-wheelhouse/manifest.json \
        "${DEPENDENCY_WHEELHOUSE_LAYER_VERSION}" "${dependency_runtime_id}"; \
    test "$(stat -c '%u:%g:%a' /opt/codingworkspace-dependency-wheelhouse)" = "0:0:555"; \
    test -z "$(find /opt/codingworkspace-dependency-wheelhouse \
        -mindepth 1 -maxdepth 1 -type f \
        \( ! -user root -o ! -group root -o ! -perm 0444 \) \
        -print -quit)"; \
    rm -f /tmp/build_dependency_wheelhouse.py

# The trusted workflow exports this target first. It obtains the runtime ID and
# raw manifest hash from the artifact built above, then supplies both to the
# final cached build so they can be verified and recorded as OCI labels.
FROM scratch AS dependency-wheelhouse-evidence
COPY --from=codingworkspace-wheelhouse-build \
    /opt/codingworkspace-dependency-wheelhouse/manifest.json /manifest.json

FROM codingworkspace-wheelhouse-build AS codingworkspace-notebook

ARG CW_REF
ARG CW_CANDIDATE_SHA
ARG GIZMOAPP_REF
ARG OPENCODE_VERSION
ARG DEPENDENCY_WHEELHOUSE_LAYER_VERSION
ARG DEPENDENCY_BUILDER_REF
ARG DEPENDENCY_BUILDER_BLOB
ARG DEPENDENCY_WHEEL_INDEX_URL
ARG DEPENDENCY_RUNTIME_ID
ARG DEPENDENCY_WHEELHOUSE_MANIFEST_SHA256
RUN set -eux; \
    PYTHONPATH=/opt/codingworkspace-jupyter/runtime \
        /opt/conda/bin/python -c \
        'import sys; from pathlib import Path; from codingworkspace_dependency_contract import dependency_manifest_metadata; metadata = dependency_manifest_metadata(Path(sys.argv[1]).read_bytes(), sys.argv[2], require_current_python=True); sys.exit("dependency identity differs from the exported artifact") if (metadata["runtime_id"], metadata["manifest_sha256"]) != (sys.argv[3], sys.argv[4]) else None' \
        /opt/codingworkspace-dependency-wheelhouse/manifest.json \
        "${DEPENDENCY_WHEELHOUSE_LAYER_VERSION}" "${DEPENDENCY_RUNTIME_ID}" \
        "${DEPENDENCY_WHEELHOUSE_MANIFEST_SHA256}"; \
    printf '%s\n' \
        "DEPENDENCY_WHEELHOUSE_LAYER_VERSION=${DEPENDENCY_WHEELHOUSE_LAYER_VERSION}" \
        "DEPENDENCY_RUNTIME_ID=${DEPENDENCY_RUNTIME_ID}" \
        "DEPENDENCY_WHEELHOUSE_MANIFEST_SHA256=${DEPENDENCY_WHEELHOUSE_MANIFEST_SHA256}" \
        > /tmp/codingworkspace-dependency-wheelhouse.env; \
    install --owner=root --group=root --mode=0444 \
        /tmp/codingworkspace-dependency-wheelhouse.env \
        /etc/codingworkspace-dependency-wheelhouse.env; \
    rm -f /tmp/codingworkspace-dependency-wheelhouse.env
LABEL org.codingworkspace.dependency-wheelhouse.layer-version="${DEPENDENCY_WHEELHOUSE_LAYER_VERSION}" \
      org.codingworkspace.dependency-wheelhouse.builder-revision="${DEPENDENCY_BUILDER_REF}" \
      org.codingworkspace.dependency-wheelhouse.builder-blob="${DEPENDENCY_BUILDER_BLOB}" \
      org.codingworkspace.dependency-wheelhouse.index-url="${DEPENDENCY_WHEEL_INDEX_URL}" \
      org.codingworkspace.dependency-wheelhouse.runtime-id="${DEPENDENCY_RUNTIME_ID}" \
      org.codingworkspace.dependency-wheelhouse.manifest-sha256="${DEPENDENCY_WHEELHOUSE_MANIFEST_SHA256}"

# CodingWorkspace handles imports. install-common.sh is intentionally omitted:
# it adds mutable notebook/Lab/grader extensions this profile never exposes.
# Keep this frequently changing source layer after the stable starter wheelhouse.
# The pinned base lacks aiohttp; install the complete proxy runtime from the
# reviewed hash-locked Python 3.13 wheels without dependency resolution.
COPY codingworkspace-notebook/CW_REF /tmp/CW_REF
COPY --chown=${NB_UID}:${NB_GID} --chmod=0444 \
    codingworkspace-notebook/proxy-requirements.txt /tmp/proxy-requirements.txt
USER ${NB_UID}
RUN --mount=type=bind,from=cwsrc,target=/cwsrc \
    set -eux; \
    tracked_ref="$(sed -e 's/[[:space:]]//g' -e '/^$/d' -e '/^#/d' /tmp/CW_REF)"; \
    test "${#tracked_ref}" -eq 40; \
    printf '%s' "${tracked_ref}" | grep -Eq '^[0-9a-f]{40}$'; \
    build_ref="${tracked_ref}"; \
    if [ -n "${CW_CANDIDATE_SHA}" ]; then \
        test "${#CW_CANDIDATE_SHA}" -eq 40; \
        printf '%s' "${CW_CANDIDATE_SHA}" | grep -Eq '^[0-9a-f]{40}$'; \
        build_ref="${CW_CANDIDATE_SHA}"; \
    fi; \
    test "${CW_REF}" = "${build_ref}"; \
    test "$(git bundle list-heads /cwsrc/source.bundle)" = "${build_ref} HEAD"; \
    git clone --quiet --no-local /cwsrc/source.bundle /tmp/cwrepo; \
    test "$(git -C /tmp/cwrepo rev-parse HEAD)" = "${build_ref}"; \
    test "$(git -C /tmp/cwrepo rev-parse --is-shallow-repository)" = "false"; \
    mkdir -p /tmp/cwbuild; \
    git -C /tmp/cwrepo archive --format=tar "${build_ref}" \
        | tar -C /tmp/cwbuild -xf -; \
    pip install --no-cache-dir --no-deps --only-binary=:all: --require-hashes \
        --requirement /tmp/proxy-requirements.txt; \
    pip install --no-cache-dir --no-deps --no-build-isolation /tmp/cwbuild; \
    pip check; \
    python -c 'import importlib.metadata as m; assert m.version("jupyterhub") == "5.5.0"; assert m.version("jupyter-server-proxy") == "4.5.0"; assert m.version("aiohttp") == "3.14.3"; assert m.version("simpervisor") == "1.0.0"; assert m.version("notebook") == "7.6.1"; assert m.version("jupyterlab") == "4.6.2"'; \
    rm -rf /tmp/cwbuild /tmp/cwrepo; \
    rm -f /tmp/proxy-requirements.txt
USER root
LABEL org.codingworkspace.source-revision="${CW_REF}" \
      org.codingworkspace.starter-revision="${GIZMOAPP_REF}" \
      org.codingworkspace.opencode-version="${OPENCODE_VERSION}"

# Root-owned high-precedence config plus JupyterHub's user-config gate prevent
# retained-home configuration from re-enabling Jupyter features.
RUN rm -f /tmp/CW_REF; \
    install -d --owner=root --group=root --mode=0555 \
        /opt/codingworkspace-jupyter/config \
        /opt/codingworkspace-jupyter/runtime \
        /opt/codingworkspace-jupyter/empty-root; \
    install -d --owner=${NB_UID} --group=${NB_GID} --mode=0700 \
        /tmp/codingworkspace-jupyter-runtime; \
    install --owner=root --group=root --mode=0444 /dev/null \
        /opt/codingworkspace-jupyter/runtime/CodingWorkspace.env; \
    install --owner=root --group=root --mode=0444 /dev/null \
        /opt/codingworkspace-jupyter/config/migrated
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
