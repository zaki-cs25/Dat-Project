#!/bin/bash
#SBATCH --qos=gpu_dedicated_praveent
#SBATCH --gres=gpu:a100_praveent:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --job-name=Qwen36-27b-vllm
#SBATCH --output=job_%j.out
#SBATCH --error=job_%j.err
set -eo pipefail

echo "=== GPU state on $(hostname) ==="
nvidia-smi --query-gpu=index,memory.used,memory.total,utilization.gpu --format=csv


#export CUDA_VISIBLE_DEVICES=7

# --- Conda env (reuses the vllm-env setup from the Qwen3.5 AutoRound deploy) ---
# nounset is disabled here on purpose: conda's own activation hooks (e.g. the
# cuda-nvcc_linux-64 hook that manages NVCC_PREPEND_FLAGS) reference variables
# before they're set and aren't nounset-safe.
set +u
source /export/software/miniconda/etc/profile.d/conda.sh
conda activate vllm-env
set -u

# Known env fixes for this cluster (see prior vLLM/CUDA-toolkit troubleshooting):
unset NVCC_PREPEND_FLAGS NVCC_PREPEND_FLAGS_BACKUP
# ${VAR:-} defaults LIBRARY_PATH/LD_LIBRARY_PATH to empty if they're unset,
# so this is safe under `set -u` instead of needing another set +u/-u toggle.
export CC="$CONDA_PREFIX/bin/x86_64-conda-linux-gnu-gcc"
export CXX="$CONDA_PREFIX/bin/x86_64-conda-linux-gnu-g++"
export CUDA_HOME="$CONDA_PREFIX"
export CPATH="$CONDA_PREFIX/include:$CONDA_PREFIX/targets/x86_64-linux/include${CPATH:+:$CPATH}"
export LIBRARY_PATH="$CONDA_PREFIX/targets/x86_64-linux/lib/stubs:$CONDA_PREFIX/lib${LIBRARY_PATH:+:$LIBRARY_PATH}"
export LD_LIBRARY_PATH="$CONDA_PREFIX/lib:/usr/lib64:/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export VLLM_SERVER_DEV_MODE=1
# Do NOT set PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True here -- it caused
# "CUDA driver error: out of memory" with vLLM's multiprocess EngineCore before.

MODEL="$HOME/downloaded-models/Qwen36-27b"   # swap for a local path if you've already downloaded weights

vllm serve "$MODEL" \
  --data-parallel-size 1 \
  --tensor-parallel-size 1 \
  --max-model-len 200000 \
  --gpu-memory-utilization 0.90 \
  --trust-remote-code \
  --host 0.0.0.0 \
  --port 9000 \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_coder \
  --reasoning-parser qwen3 \
  --language-model-only \
  --speculative-config '{"method": "mtp", "num_speculative_tokens": 1}' \
  --enable-per-request-metrics \
  --served-model-name Qwen3.6-27B
