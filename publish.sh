#!/bin/bash
# ============================================================
# publish.sh — ONOFRE Viewer
# Executa el notebook ONOFRE, genera els frames pel visor web,
# i publica els canvis al repo (que GitHub Pages serveix).
#
# Pensat per anar-hi via cron a labfire.ctfc.cat, just després
# de la descàrrega ICON-EU / del run ONOFRE habitual.
# ============================================================
set -euo pipefail

REPO_DIR="/home/pguarque/onofre-viewer"      # ← el clone del repo al servidor
NOTEBOOK="/home/pguarque/GRAF_2026_amb_export.ipynb"
CONDA_ENV="graf_env"

cd "$REPO_DIR"
git pull --ff-only

# ── 1. Executa el notebook (genera els frames dins $REPO_DIR/docs/data) ──
source /home/labfire/miniforge3/etc/profile.d/conda.sh
conda activate "$CONDA_ENV"

jupyter nbconvert \
    --to notebook --execute \
    --ExecutePreprocessor.timeout=3600 \
    --output /tmp/GRAF_2026_executed.ipynb \
    "$NOTEBOOK"

# ── 2. Publica al repo ────────────────────────────────────────
cd "$REPO_DIR"
git add docs/data
if git diff --cached --quiet; then
    echo "Sense canvis, no cal fer commit."
else
    git commit -m "Actualització automàtica $(date -u +'%Y-%m-%d %H:%MZ')"
    git push
    echo "✓ Publicat."
fi
