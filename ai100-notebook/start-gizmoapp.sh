#!/bin/bash
# Launch GizmoApp for jupyter-server-proxy.
#
# Invoked as: start-gizmoapp.sh <port>
# jupyter-server-proxy substitutes {port} and sets GIZMOAPP_URL_PREFIX in the
# environment so GizmoApp generates links under the proxied Jupyter base URL.
#
# GizmoApp lives in the student's home directory after an nbgitpuller pull.
set -euo pipefail

PORT="${1:-8001}"
APP_DIR="${GIZMOAPP_DIR:-${HOME}/GizmoApp}"

if [ ! -d "${APP_DIR}" ]; then
    echo "GizmoApp is not present at ${APP_DIR}." >&2
    echo "Use the nbgitpuller link to pull the repo, then start GizmoApp again." >&2
    exit 1
fi

cd "${APP_DIR}"

# The student's app gets its own AI identity (GIZMO_LLM_*). Drop the coding
# agent's credentials so a bare OpenAI() in app code fails loudly instead of
# silently spending the agent's budget.
unset OPENAI_API_KEY OPENAI_BASE_URL ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN ANTHROPIC_BASE_URL COHERE_API_KEY

# server.wsgi calls create_app(), which runs the (idempotent) DB migrations on
# import, so no separate init step is needed. --chdir keeps the `server`
# package importable for gunicorn.
exec gunicorn \
    --chdir "${APP_DIR}" \
    --bind "127.0.0.1:${PORT}" \
    --workers 2 \
    --timeout 120 \
    server.wsgi:app
