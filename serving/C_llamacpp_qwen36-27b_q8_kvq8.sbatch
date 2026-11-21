#!/bin/bash
#SBATCH --qos=gpu_dedicated_praveent
#SBATCH --gres=gpu:a100_praveent:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=128G
#SBATCH --job-name=qwen36_27b_q8kv
#SBATCH --output=job_%j.out
#SBATCH --error=job_%j.err
set -eo pipefail

echo "Slurm assigned CUDA_VISIBLE_DEVICES=$CUDA_VISIBLE_DEVICES"
echo "=== Running on $(hostname) ==="
nvidia-smi --query-gpu=index,memory.used,memory.total,utilization.gpu --format=csv

MODEL_DIR="/export/home/zaki.cse.iith/downloaded-models/unsloth-qwen3.6-27b"
MODEL_FILE="$MODEL_DIR/Qwen3.6-27B-Q8_0.gguf"

if [ ! -f "$MODEL_FILE" ]; then
  echo "ERROR: model not found at $MODEL_FILE" >&2
  exit 1
fi

/export/home/zaki.cse.iith/.llama-app/llama serve \
  -m "$MODEL_FILE" \
  --alias qwen3.6-27b \
  --host 0.0.0.0 --port 8001 \
  --metrics \
  --slots \
  --n-gpu-layers all \
  --flash-attn on \
  --cache-type-k q8_0 \
  --cache-type-v q8_0 \
  --ctx-size 262144 \
  --parallel 4 \
  --batch-size 2048 \
  --ubatch-size 2048 \
  --n-predict 32768 \
  --reasoning on \
  --reasoning-format deepseek \
  --reasoning-budget 8192 \
  --temp 0.6 \
  --top-p 0.95 \
  --top-k 20 \
  --min-p 0.0 \
  --presence-penalty 0.0 \
  --threads 8 --threads-batch 8
