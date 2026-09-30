# ngshare-notebook/Dockerfile
#
# In-house build of ngshare, replacing the unmaintained libretexts/ngshare
# Docker Hub image (built Dec 2022, never rebuilt since, never scanned).
#
# WHY A BUILT IMAGE AT ALL, RATHER THAN A STOCK python CONTAINER THAT
# installs everything at pod startup:
#   - Reproducibility: a build is a single, auditable artifact - the exact
#     same bytes run in stg, preview and (eventually) prd, and are pinned by
#     digest in config-ngshare-keycloak.yaml. A container that pip-installs
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
    apt-get clean && \
    apt-get autoremove -y

# pip - pinned transitive deps rather than upstream's loose setup.py floors
# (SQLAlchemy>=1.4.0, tornado>=6.0.3, jupyterhub>=1.1.0, requests>=2.x),
# which is exactly how Tornado 6.2 and requests 2.28.1 (both carrying
# disclosed CVEs) ended up in the Docker Hub image - "whatever pip resolved
# on build day", never a chosen version. requests is pinned here explicitly
# even though it's only a transitive dep (via ngshare's own setup.py) -
# otherwise it's the one package that would still resolve unpinned at the
# `pip install /ngshare` step below.
COPY ngshare-notebook/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# See header comment: vendored, not cloned, and why.
COPY ngshare-notebook/vendor /ngshare
RUN pip install --no-cache-dir /ngshare

# Hardening launcher - wraps ngshare without patching its source, to turn on
# request logging (ngshare's own startup code silently disables Tornado's
# access logger), XSRF/SameSite cookie protection, and a request body-size
# cap - none of which ngshare sets on its own. See run.py's own docstring
# for exactly what it patches and why.
COPY ngshare-notebook/run.py /ngshare/run.py

# Fix ownership: matches the chart's existing pod securityContext
# (runAsUser 65535), stated again here so the image fails safe even
# run outside that chart.
RUN chown -R 65535:65535 /ngshare

USER 65535:65535
WORKDIR /ngshare
ENV PYTHONUNBUFFERED=1
# Default request body-size cap; override per-environment via the chart if needed.
ENV NGSHARE_MAX_BODY_BYTES=26214400

ENTRYPOINT ["python3", "/ngshare/run.py"]
