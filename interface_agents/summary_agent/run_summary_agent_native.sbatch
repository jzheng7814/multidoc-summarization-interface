#!/bin/bash
#
#SBATCH --job-name=summary_agent_native_run
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=32
#SBATCH --gres=gpu:a40:4
#SBATCH --partition="nlprx-lab"
#SBATCH --qos="short"
#SBATCH --exclude=conroy
#SBATCH --output=agent_logs/%x-%j.out
#SBATCH --exclude=gundam,dendrite,puma,xaea-12,spot,hk47,consu,nestor,chappie,spd-13,sonny,heistotron,uniblab,perseverance,qt-1,cheetah,clippy

echo "========================================="
echo "START TIME: $(date)"
echo "RUNNING ON: $(hostname)"
echo "SLURM_NODELIST: ${SLURM_JOB_NODELIST}"
echo "========================================="

set -euo pipefail
set -x

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${INTERFACE_SUMMARY_AGENT_ENV_FILE:-${SCRIPT_DIR}/.env}"
if [[ -f "$ENV_FILE" ]]; then
  set -o allexport
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +o allexport
fi

BASE_DIR="${INTERFACE_SUMMARY_AGENT_BASE_DIR:-${SCRIPT_DIR}}"
EXTRACTION_BASE_DIR="${INTERFACE_SUMMARY_AGENT_EXTRACTION_BASE_DIR:-${INTERFACE_CHECKLIST_AGENT_BASE_DIR:-$(cd "${SCRIPT_DIR}/../checklist_agent" && pwd)}}"
PYTHON_BIN="${INTERFACE_SUMMARY_AGENT_PYTHON_BIN:-python}"
export HF_HOME="${INTERFACE_SUMMARY_AGENT_HF_HOME:-${HF_HOME:-${HOME}/.cache/huggingface}}"
export HUGGINGFACE_HUB_CACHE="${INTERFACE_SUMMARY_AGENT_HUGGINGFACE_HUB_CACHE:-${HUGGINGFACE_HUB_CACHE:-${HF_HOME}/hub}}"
export TRANSFORMERS_CACHE="${INTERFACE_SUMMARY_AGENT_TRANSFORMERS_CACHE:-${TRANSFORMERS_CACHE:-${HUGGINGFACE_HUB_CACHE}}}"
export PATH="$(dirname "${PYTHON_BIN}"):${PATH}"

corpus_id=${CORPUS_ID:-"45696"}
model_name=${MODEL_NAME:-"unsloth/gpt-oss-20b-BF16"}
max_steps=${MAX_STEPS:-"200"}
reasoning_effort=${REASONING_EFFORT:-"medium"}
resume=${RESUME:-"false"}
debug=${DEBUG:-"false"}
output_base_dir=${OUTPUT_BASE_DIR:-"output"}
data_dir=${DATA_DIR:-"20_human_eval_cases"}
request_json=${REQUEST_JSON:-""}
k_recent_tool_outputs=${K_RECENT_TOOL_OUTPUTS:-"5"}
prompt_config=${PROMPT_CONFIG:-"native/prompts_gpt_oss_summary_native.yaml"}

if [[ -z "$request_json" ]]; then
  echo "ERROR: REQUEST_JSON is required in --export." >&2
  exit 2
fi

model_suffix=$(echo "$model_name" | awk -F'/' '{print $NF}')

CORPUS_PATH="${EXTRACTION_BASE_DIR}/data/${data_dir}/${corpus_id}"
OUTPUT_DIR="${BASE_DIR}/${output_base_dir}/${model_suffix}/${corpus_id}/summary_agent"

mkdir -p "$OUTPUT_DIR"
mkdir -p "${BASE_DIR}/agent_logs"
mkdir -p "${HUGGINGFACE_HUB_CACHE}"

if [[ "$debug" == "true" ]]; then
  log_path="${OUTPUT_DIR}/debug.log"
else
  log_name="${corpus_id}_summary_agent_steps${max_steps}"
  if [[ "$resume" == "true" ]]; then
    log_name="${log_name}_resume"
  fi
  log_path="${BASE_DIR}/agent_logs/${model_suffix}/${corpus_id}/${log_name}.log"
  mkdir -p "$(dirname "$log_path")"
fi

echo ""
echo "========================================="
echo "Summary Agent Native Configuration"
echo "========================================="
echo "Corpus ID: ${corpus_id}"
echo "Model: ${model_name}"
echo "Max Steps: ${max_steps}"
echo "Reasoning Effort: ${reasoning_effort}"
echo "Resume: ${resume}"
echo "Debug: ${debug}"
echo "Output Base Dir: ${output_base_dir}"
echo "Data Dir: ${data_dir}"
echo "Request JSON: ${request_json}"
echo "Prompt Config: ${prompt_config}"
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

srun "${PYTHON_BIN}" run_summary_agent_native.py "${CORPUS_PATH}" \
  --request-json "${request_json}" \
  --model "${model_name}" \
  --max-steps ${max_steps} \
  --reasoning-effort "${reasoning_effort}" \
  --summary-state-path "${OUTPUT_DIR}/summary_state.json" \
  --ledger-path "${OUTPUT_DIR}/ledger.jsonl" \
  --k-recent-tool-outputs ${k_recent_tool_outputs} \
  --prompt-config "${prompt_config}" \
  ${cmd_args} \
  2>&1 | tee "$log_path"

exit_status=${PIPESTATUS[0]}

echo ""
echo "========================================="
if [[ $exit_status -eq 0 ]]; then
  echo "Summary agent completed successfully!"
  echo "Results saved to: ${OUTPUT_DIR}"
else
  echo "Summary agent terminated with errors (exit code: $exit_status)"
  echo "Check log file: ${log_path}"
fi
echo "========================================="
echo "END TIME: $(date)"
echo "========================================="

exit $exit_status
