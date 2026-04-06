#!/bin/bash
#
#SBATCH --job-name=legal_agent_native_run
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=32
#SBATCH --gres=gpu:a40:4
#SBATCH --partition="nlprx-lab"
#SBATCH --qos="short"
#SBATCH --output=agent_logs/%x-%j.out
#SBATCH --exclude=gundam,dendrite,puma,xaea-12,spot,hk47,consu,nestor,chappie,spd-13,sonny,heistotron,uniblab,perseverance,qt-1,cheetah

echo "========================================="
echo "START TIME: $(date)"
echo "RUNNING ON: $(hostname)"
echo "SLURM_NODELIST: ${SLURM_JOB_NODELIST}"
echo "========================================="

set -euo pipefail
set -x

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${INTERFACE_AGENT_ENV_FILE:-${SCRIPT_DIR}/.env}"
if [[ -f "$ENV_FILE" ]]; then
    set -o allexport
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +o allexport
fi

BASE_DIR="${INTERFACE_AGENT_BASE_DIR:-${SCRIPT_DIR}}"
PYTHON_BIN="${INTERFACE_AGENT_PYTHON_BIN:-python}"
export HF_HOME="${INTERFACE_AGENT_HF_HOME:-${HF_HOME:-${HOME}/.cache/huggingface}}"
export HUGGINGFACE_HUB_CACHE="${INTERFACE_AGENT_HUGGINGFACE_HUB_CACHE:-${HUGGINGFACE_HUB_CACHE:-${HF_HOME}/hub}}"
export TRANSFORMERS_CACHE="${INTERFACE_AGENT_TRANSFORMERS_CACHE:-${TRANSFORMERS_CACHE:-${HUGGINGFACE_HUB_CACHE}}}"
export PATH="$(dirname "${PYTHON_BIN}"):${PATH}"

case_id=${CASE_ID:-"45696"}
model_name=${MODEL_NAME:-"unsloth/gpt-oss-20b-BF16"}
checklist_config=${CHECKLIST_CONFIG:-"config/checklist_configs/all/all_26_items.yaml"}
max_steps=${MAX_STEPS:-"200"}
reasoning_effort=${REASONING_EFFORT:-"medium"}
resume=${RESUME:-"false"}
debug=${DEBUG:-"false"}
output_base_dir=${OUTPUT_BASE_DIR:-"output"}
data_dir=${DATA_DIR:-"20_human_eval_cases"}

model_suffix=$(echo "$model_name" | awk -F'/' '{print $NF}')
config_suffix=$(basename "$checklist_config" .yaml)

if [[ "$checklist_config" == *"/all/"* ]]; then
    config_category="all"
elif [[ "$checklist_config" == *"/grouped/"* ]]; then
    config_category="grouped"
elif [[ "$checklist_config" == *"/individual/"* ]]; then
    config_category="individual"
else
    config_category="custom"
fi

CORPUS_PATH="${BASE_DIR}/data/${data_dir}/${case_id}"
OUTPUT_DIR="${BASE_DIR}/${output_base_dir}/${model_suffix}/${case_id}/${config_category}/${config_suffix}"

mkdir -p "$OUTPUT_DIR"
mkdir -p "${BASE_DIR}/agent_logs"
mkdir -p "${HUGGINGFACE_HUB_CACHE}"

if [[ "$debug" == "true" ]]; then
    log_path="${OUTPUT_DIR}/debug.log"
    echo "Debug mode: Log will be saved to output directory"
else
    log_name="${case_id}_${config_category}_${config_suffix}_steps${max_steps}"
    if [[ "$resume" == "true" ]]; then
        log_name="${log_name}_resume"
    fi
    log_path="${BASE_DIR}/agent_logs/${model_suffix}/${case_id}/${log_name}.log"
    mkdir -p "$(dirname "$log_path")"
fi

echo ""
echo "========================================="
echo "Legal Agent Native Configuration"
echo "========================================="
echo "Case ID: ${case_id}"
echo "Model: ${model_name}"
echo "Checklist Config: ${checklist_config}"
echo "Config Category: ${config_category}"
echo "Config Name: ${config_suffix}"
echo "Max Steps: ${max_steps}"
echo "Reasoning Effort: ${reasoning_effort}"
echo "Resume: ${resume}"
echo "Debug: ${debug}"
echo "Output Base Dir: ${output_base_dir}"
echo "Data Dir: ${data_dir}"
echo "Corpus Path: ${CORPUS_PATH}"
echo "Output Directory: ${OUTPUT_DIR}"
echo "Log Path: ${log_path}"
echo "========================================="
echo ""

cmd_args=""
if [[ "$resume" == "true" ]]; then
    cmd_args="${cmd_args} --resume"
fi
if [[ "$debug" == "true" ]]; then
    cmd_args="${cmd_args} --debug"
fi

cd "$BASE_DIR"

srun "${PYTHON_BIN}" native/run_agent_native.py "${CORPUS_PATH}" \
    --model "${model_name}" \
    --checklist-config "${checklist_config}" \
    --max-steps ${max_steps} \
    --reasoning-effort "${reasoning_effort}" \
    --store-path "${OUTPUT_DIR}/checklist.json" \
    --ledger-path "${OUTPUT_DIR}/ledger.jsonl" \
    --k-recent-tool-outputs 5 \
    ${cmd_args} \
    2>&1 | tee "$log_path"

exit_status=${PIPESTATUS[0]}

echo ""
echo "========================================="
if [[ $exit_status -eq 0 ]]; then
    echo "Native agent completed successfully!"
    echo "Results saved to: ${OUTPUT_DIR}"
    if [[ -f "${OUTPUT_DIR}/stats.json" ]]; then
        echo ""
        echo "Token Usage Summary:"
        "${PYTHON_BIN}" -c "
import json
with open('${OUTPUT_DIR}/stats.json', 'r') as f:
    stats = json.load(f)
    print(f\"  Model: {stats.get('model', 'N/A')}\")
    print(f\"  Total Steps: {stats.get('steps', 0)}\")
    print(f\"  Total System Tokens: {stats.get('total_system_prompt_tokens', 0):,}\")
    print(f\"  Total User Tokens: {stats.get('total_user_prompt_tokens', 0):,}\")
    print(f\"  Total Completion Tokens: {stats.get('total_completion_tokens', 0):,}\")
    total = stats.get('total_system_prompt_tokens', 0) + stats.get('total_user_prompt_tokens', 0) + stats.get('total_completion_tokens', 0)
    print(f\"  Total All Tokens: {total:,}\")
" 2>/dev/null || echo "  Could not read stats file"
    fi
else
    echo "Native agent terminated with errors (exit code: $exit_status)"
    echo "Check the log file: ${log_path}"
fi
echo "========================================="
echo "END TIME: $(date)"
echo "========================================="

exit $exit_status
