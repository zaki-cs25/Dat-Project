#!/bin/bash
#SBATCH --qos=gpu_dedicated_praveent
#SBATCH --gres=gpu:a100_praveent:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=128G
#SBATCH --job-name=gemma4_judge8004
#SBATCH --output=job_%j.out
#SBATCH --error=job_%j.err
set -eo pipefail


echo "Slurm assigned CUDA_VISIBLE_DEVICES=$CUDA_VISIBLE_DEVICES"
echo "=== GPU state on $(hostname) ==="
nvidia-smi --query-gpu=index,memory.used,memory.total,utilization.gpu --format=csv

export LLAMA_CACHE="/export/home/zaki.cse.iith/downloaded-models/unsloth-gemma"
/export/home/zaki.cse.iith/.llama-app/llama serve \
	-hf unsloth/gemma-4-26B-A4B-it-GGUF:UD-Q8_K_XL \
  --host 0.0.0.0 --port 8004 \
  --n-gpu-layers all \
  --flash-attn on \
  --ctx-size 1048576 \
  --parallel 4 \
  --batch-size 2048 \
  --ubatch-size 2048 \
  --n-predict 32768 \
  --reasoning on \
  --reasoning-format deepseek \
  --reasoning-budget 8192 \
  --image-min-tokens 1120 \
  --image-max-tokens 1120 \
  --temp 1.0 \
  --top-p 0.95 \
  --top-k 64 \
  --min-p 0.0 \
  --threads 8 --threads-batch 8
