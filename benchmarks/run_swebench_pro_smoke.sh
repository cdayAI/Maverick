#!/usr/bin/env bash
# One-shot smoke runner for SWE-bench Pro. Validates the full
# producer-then-scorer pipeline on 5 instances so you know the
# wiring works before spending real money on the 1865-instance run.
#
# Costs: ~$10-30 depending on which pipelines you enable.
# Time: ~15-30 min (first run includes Docker image builds).
#
# Usage:
#   ./benchmarks/run_swebench_pro_smoke.sh             # default 5 inst, maverick + sonnet_single
#   ./benchmarks/run_swebench_pro_smoke.sh 10          # 10 instances
#   ./benchmarks/run_swebench_pro_smoke.sh 5 all       # all four pipelines
#
# Reads the manifest from ~/.maverick/swebench-pro/manifest.jsonl;
# create it with the script in RUNBOOK_SWE_BENCH_PRO.md step 1.

set -euo pipefail

INSTANCES="${1:-5}"
PIPELINES_ARG="${2:-default}"

MANIFEST="${HOME}/.maverick/swebench-pro/manifest.jsonl"
WORKDIR="$(mktemp -d -t maverick-swe-XXXXXX)"
SMOKE_MANIFEST="${WORKDIR}/smoke.jsonl"
PREDS_CSV="${WORKDIR}/predictions.csv"
PREDS_JSONL="${WORKDIR}/preds.jsonl"

if [[ ! -f "${MANIFEST}" ]]; then
    echo "ERROR: manifest not found at ${MANIFEST}" >&2
    echo "Run step 1 of benchmarks/RUNBOOK_SWE_BENCH_PRO.md first." >&2
    exit 2
fi

if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
    echo "ERROR: ANTHROPIC_API_KEY not set." >&2
    exit 2
fi

if [[ "${PIPELINES_ARG}" == "all" ]]; then
    PIPELINES="maverick,sonnet_single,sonnet_tools,sonnet_self_consistency_n8"
else
    PIPELINES="maverick,sonnet_single"
fi

# Cascaded routing makes Maverick affordable; force it on for smoke
# so the cost numbers are representative of a real Pareto run.
export MAVERICK_CASCADE_ROUTING=1

echo "[smoke] manifest:   ${MANIFEST}"
echo "[smoke] instances:  ${INSTANCES}"
echo "[smoke] pipelines:  ${PIPELINES}"
echo "[smoke] workdir:    ${WORKDIR}"
echo

head -n "${INSTANCES}" "${MANIFEST}" > "${SMOKE_MANIFEST}"

# ---- producer ----
echo "[smoke] running producer..."
python "$(dirname "$0")/swe_bench.py" \
    --instances "${SMOKE_MANIFEST}" \
    --pipelines "${PIPELINES}" \
    --out "${PREDS_CSV}"

echo
echo "[smoke] predictions written to ${PREDS_CSV}"
echo "[smoke] inspect with:  csvtool col 1,2,9,11 ${PREDS_CSV} | head"
echo

# ---- producer-only sanity ----
PATCH_COUNT=$(awk -F, 'NR>1 && $9 ~ /^---/ {n++} END {print n+0}' "${PREDS_CSV}")
TOTAL_ROWS=$(($(wc -l < "${PREDS_CSV}") - 1))
echo "[smoke] ${PATCH_COUNT}/${TOTAL_ROWS} rows have a unified-diff-shaped patch"

if [[ "${PATCH_COUNT}" -eq 0 ]]; then
    echo
    echo "[smoke] FAIL: no rows have a valid patch. Common causes:"
    echo "  - the agent emitted prose instead of a diff (add a worker-prompt hint)"
    echo "  - the model hit max_dollars before producing FINAL (raise the cap)"
    echo "  - the brief format confused the agent (inspect SMOKE_MANIFEST)"
    echo
    echo "Look at the worst row:"
    echo "  csvtool col 1,2,11,9 ${PREDS_CSV} | head -20"
    exit 1
fi

# ---- scorer (optional; needs Docker + the `swebench` PyPI package) ----
if ! command -v docker >/dev/null 2>&1; then
    echo "[smoke] docker not on PATH; skipping evaluator step."
    echo "[smoke] producer pipeline OK. Install Docker + 'pip install swebench' to score."
    exit 0
fi

if ! python -c "import swebench" 2>/dev/null; then
    echo "[smoke] swebench python pkg not installed; skipping evaluator step."
    echo "[smoke] producer pipeline OK. Run 'pip install swebench>=2.0' to score."
    exit 0
fi

echo
echo "[smoke] running official SWE-bench evaluator (this builds Docker images; slow first time)..."

python -c "
import csv, json, sys
with open('${PREDS_CSV}') as f, open('${PREDS_JSONL}', 'w') as out:
    r = csv.DictReader(f)
    for row in r:
        if row['pipeline'] != 'maverick':
            continue
        out.write(json.dumps({
            'instance_id': row['instance_id'],
            'model_patch': row['predicted_patch'].replace('\\\\n', chr(10)),
            'model_name_or_path': row['model_id'] or 'maverick',
        }) + chr(10))
"

python -m swebench.harness.run_evaluation \
    --predictions_path "${PREDS_JSONL}" \
    --dataset_name Scale/swe-bench-pro \
    --split test \
    --max_workers 2 \
    --run_id "maverick-smoke-$$"

echo
echo "[smoke] DONE. Pareto table on these 5 instances is meaningless"
echo "         statistically but proves the wiring. Now schedule the"
echo "         real 1865-instance run per RUNBOOK_SWE_BENCH_PRO.md step 4."
