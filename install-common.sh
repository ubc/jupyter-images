#!/bin/bash
set -e

echo "Installing common Python packages..."
pip install nbgitpuller \
    jupyterlab-lsp \
    jupyterlab-code-formatter \
    jupyterlab-spreadsheet-editor \
    jupyterlab_templates \
    jupyter-resource-usage \
    otter-grader \
    jupytext

echo "Installation complete!"
