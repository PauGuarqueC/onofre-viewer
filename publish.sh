#!/bin/bash
# ============================================================
# publish.sh — ONOFRE Viewer (v2, escala Europa)
# Executa el notebook ONOFRE, genera els frames pel visor web,
# neteja els runs antics (nomès es fa servir "latest"), i publica
# els canvis al repo (que GitHub Pages serveix).
#
# Accepta un paràmetre opcional amb l'hora del run (0 o 12):
#   ./publish.sh        -> run de les 00Z (per defecte)
#   ./publish.sh 12     -> run de les 12Z
#
# Pensat per anar-hi via cron a labfire.ctfc.cat (dos cops al dia).
# ============================================================
set -euo pipefail

RUN_HOUR="${1:-0}"
export ONOFRE_RUN_HOUR="$RUN_HOUR"

REPO_DIR="/home/pguarque/onofre-viewer"
NOTEBOOK="/home/pguarque/GRAF_2026_amb_export.ipynb"
VENV_DIR="/home/pguarque/graf_env"
LOG_DIR="/home/pguarque/onofre-viewer-logs"
LOG_FILE="$LOG_DIR/publish_$(date -u +'%Y%m%d_%H%M')_${RUN_HOUR}Z.log"

mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "════════════════════════════════════════════════════"
echo "  Run iniciat: $(date -u +'%Y-%m-%d %H:%M:%SZ')  (run ICON-EU: ${RUN_HOUR}Z)"
echo "════════════════════════════════════════════════════"

cd "$REPO_DIR"
git pull --ff-only

# ── 1. Executa el notebook (genera els frames dins docs/data/) ──────────────
source "$VENV_DIR/bin/activate"

jupyter nbconvert \
    --to notebook --execute \
    --ExecutePreprocessor.timeout=7200 \
    --output "/tmp/GRAF_2026_executed_${RUN_HOUR}Z.ipynb" \
    "$NOTEBOOK"

echo "✓ Notebook executat correctament (run ${RUN_HOUR}Z)."

# ── 2. Neteja runs antics — el visor nomès llegeix "latest/", la resta és
#       brossa acumulada. Sense això, el repo creix sense control (~100+MB
#       per dia a escala Europa). ────────────────────────────────────────────
BEFORE_SIZE=$(du -sh "$REPO_DIR/docs/data" 2>/dev/null | cut -f1)
find "$REPO_DIR/docs/data" -mindepth 2 -maxdepth 2 -type d ! -name 'latest_00' ! -name 'latest_12' -exec rm -rf {} +
AFTER_SIZE=$(du -sh "$REPO_DIR/docs/data" 2>/dev/null | cut -f1)
echo "✓ Runs antics netejats. Mida docs/data: $BEFORE_SIZE → $AFTER_SIZE"

# ── 3. Publica al repo ───────────────────────────────────────────────────────
cd "$REPO_DIR"
git add docs/data
if git diff --cached --quiet; then
    echo "Sense canvis, no cal fer commit."
else
    git commit -m "Actualització automàtica ${RUN_HOUR}Z $(date -u +'%Y-%m-%d %H:%MZ')"
    git push
    echo "✓ Publicat a GitHub Pages."
fi

echo "════════════════════════════════════════════════════"
echo "  Run acabat: $(date -u +'%Y-%m-%d %H:%M:%SZ')"
echo "════════════════════════════════════════════════════"
