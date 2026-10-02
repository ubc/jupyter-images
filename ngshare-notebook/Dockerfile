# ngshare-notebook/Dockerfile
#
# In-house build of ngshare, replacing the unmaintained libretexts/ngshare
# Docker Hub image (built Dec 2022, never rebuilt since, never scanned).
#
# WHY A BUILT IMAGE AT ALL, RATHER THAN A STOCK python CONTAINER THAT
# installs everything at pod startup:
#   - Reproducibility: a build is a single, auditable artifact - the exact
#     same bytes can run in stg, preview and (eventually) prd, referenced
#     by tag in config-ngshare-keycloak.yaml - see that repo for which tag
#     it currently points at. A container that pip-installs
#     on every pod start has no such guarantee: a transient PyPI outage, a
#     changed package, or a network blip becomes a spawn failure instead of
#     a build-time failure, and two pods started minutes apart could
#     silently run different dependency versions.
#   - Scanning: ECR only scans what actually gets pushed as an image. Code
#     pulled and installed at container start is invisible to scan-on-push -
#     which is the exact blind spot that let the Docker Hub image sit
#     unscanned for ~46 months in the first place.
#   - Startup time and blast radius: installing pip/apt packages at pod
#     start means every restart depends on the network, and a bad push to a
#     dependency breaks every running pod on its next restart simultaneously
#     rather than on the next deliberate rebuild.
#   - This is the same reasoning already applied to every other image in
#     this repo (scipy-notebook, tensorflow-notebook, r-notebook): build
#     once, pin by digest, deploy the artifact.
#
# WHY VENDORED SOURCE (ngshare-notebook/vendor/) INSTEAD OF CLONING
# github.com/LibreTexts/ngshare AT BUILD TIME:
#   - ngshare is a single-maintainer project with no release since
#     v0.6.0 (Dec 2022) and 12 open issues. Pinning a commit SHA protects
#     against the CODE changing under us, but not against the REPOSITORY
#     disappearing - deleted, made private, org transferred. A build that
#     does `git clone https://github.com/LibreTexts/ngshare` on every build
#     would break permanently the day that happens, even with an exact
#     commit pinned, because the clone step itself needs the remote to
#     still exist.
#   - Vendoring copies the pinned commit's source into THIS repo's own git
#     history once, so every future build (and every future audit of what
#     shipped) depends only on jupyter-images staying available, not on a
#     third party's GitHub org.
#   - Tradeoff, accepted deliberately: bumping the pinned ngshare commit is
#     now a manual re-vendor (re-clone, checkout, rm -rf .git, replace this
#     directory) rather than changing one ARG. That friction is intentional -
#     a commit bump on an unmaintained, single-maintainer project deserves a
#     deliberate review, not an automatic pull.
#
# Vendored from LibreTexts/ngshare master, commit
# 6a3125e10d94d3fab7f8785c7ecf7e8464906810, resolved 2026-09-29.
# To bump: re-clone upstream, git checkout <new sha>, rm -rf .git, replace
# ngshare-notebook/vendor/ wholesale, update this comment and the one below.

# Base pinned by digest, same pattern as scipy-notebook/tensorflow-notebook.
# Resolve a fresh one with:
#   docker pull python:3.12-slim-bookworm && \
#   docker inspect --format='{{index .RepoDigests 0}}' python:3.12-slim-bookworm
ARG BASE_CONTAINER=python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e
FROM $BASE_CONTAINER

LABEL maintainer="Ryoko <ryoko.norden@ubc.ca>"

USER root

# apt-get upgrade pulls in Debian security patches released after this base
# image was last published but before this build runs - the base image tag
# alone only reflects packages current as of ITS last publish date. Combined
# with apt-get update in one RUN so Docker's build cache can never reuse a
# stale package index against a fresh upgrade.
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get autoremove -y && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# pip - constraints.txt pins the full transitive closure (same convention
# as scipy-notebook/r-notebook's root constraints.txt: PIP_CONSTRAINT caps
# whatever pip resolves, rather than letting jupyterhub/alembic's own
# dependencies float between builds a day apart). This is exactly how
# Tornado 6.2 and requests 2.28.1 (both carrying disclosed CVEs) ended up
# in the Docker Hub image, as unpinned transitives of a loose setup.py
# floor. requests is a transitive dep of jupyterhub, not of ngshare's own
# setup.py (which lists only SQLAlchemy/alembic/tornado/jupyterhub).
# Regenerate against this exact base image with:
#   docker run --rm -v "$PWD":/work -w /work \
#     python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e \
#     bash -c 'pip install --quiet pip-tools && \
#       pip-compile --no-header --no-annotate --strip-extras \
#         -o ngshare-notebook/constraints.txt ngshare-notebook/requirements.txt'
COPY ngshare-notebook/requirements.txt /tmp/requirements.txt
COPY ngshare-notebook/constraints.txt /tmp/constraints.txt
RUN PIP_CONSTRAINT=/tmp/constraints.txt pip install --no-cache-dir -r /tmp/requirements.txt

# See header comment: vendored, not cloned, and why.
COPY ngshare-notebook/vendor /ngshare
# Vendored test modules install as importable submodules of the ngshare
# package (find_packages() has no notion of "test file", only "package
# directory") but are never imported at runtime - except
# database/test_database.py, which database/__init__.py imports
# clear_db/init_db/dump_db from, so that one stays. vendor/ itself is left
# byte-identical to the pinned upstream commit; this only trims what gets
# installed into the image.
RUN rm -f /ngshare/ngshare/test_ngshare.py \
          /ngshare/ngshare/test_dbutil.py \
          /ngshare/ngshare/vngshare.py && \
    PIP_CONSTRAINT=/tmp/constraints.txt pip install --no-cache-dir /ngshare

# Hardening launcher - wraps ngshare without patching its source, to turn on
# request logging (ngshare's own startup code silently disables Tornado's
# access/application/general loggers), XSRF/SameSite/HttpOnly/Secure
# cookie protection with the token-authenticated exemption JupyterHub's own
# HubAuth makes, and a request body-size cap - none of which ngshare sets
# on its own. See run.py's own docstring for exactly what it patches and why.
COPY ngshare-notebook/run.py /ngshare/run.py

# Root-owned, read-only for the runtime user - it only needs to execute
# this code, never modify it. (Database/file storage live outside
# /ngshare, under args.database/args.storage, so this doesn't affect them.)
RUN chmod -R a+rX /ngshare

USER 65535:65535
WORKDIR /ngshare
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python3", "/ngshare/run.py"]
