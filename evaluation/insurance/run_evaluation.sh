#!/bin/bash                                                                                                                        
set -euo pipefail
#{ time bash run_evaluation.sh; } 2>&1 | tee test_Qwen3.6-27B.log                                                                                                                  
                                                                                                                                    
# ---------------- Default Configuration ----------------                                                                          
# These can be overridden by environment variables or arguments                                                                    
AGENT="${AGENT:-insurance}"                                                                                                        
DATASET="${DATASET:-/Users/userd/Agent-Garden/harness/golden/golden_120.jsonl}"                                                    
ENDPOINT="${ENDPOINT:-http://localhost:9000/v1}" 
MODEL="${MODEL:-Qwen3.6-27B}"                                                                                                         
API_KEY="${API_KEY:-not-needed}"                                                                                                   
TARGET="${TARGET:-self-hosted}"                                                                                                    
GPU_COST_PER_HOUR="${GPU_COST_PER_HOUR:-180}"                                                                                      
WORKERS_SMOKE=1                                                                                                                    
WORKERS_FULL=8 # change it to 1 if not using  A100 GPU                                                                                                                 
REPO_DIR="/Users/userd/Agent-Garden"                                                                                               
BASE_RESULTS_DIR="${REPO_DIR}/results"                                                                                             
                                                                                                                                    
# Flags                                                                                                                            
USE_MOCK=false                                                                                                                     
                                                                                                                                    
# ---------------- Argument Parsing ----------------                                                                               
# Usage: ./run_evaluation.sh [--mock] [optional overrides]                                                                         
while [[ $# -gt 0 ]]; do                                                                                                           
    case $1 in                                                                                                                       
    --mock)                                                                                                                        
        USE_MOCK=true                                                                                                                
        shift                                                                                                                        
        ;;                                                                                                                           
    --model)                                                                                                                       
        MODEL="$2"                                                                                                                   
        shift 2                                                                                                                      
        ;;                                                                                                                           
    --dataset)                                                                                                                     
        DATASET="$2"                                                                                                                 
        shift 2                                                                                                                      
        ;;                                                                                                                           
    *)                                                                                                                             
        echo "Unknown argument: $1"                                                                                                  
        exit 1                                                                                                                       
        ;;                                                                                                                           
    esac                                                                                                                             
done                                                                                                                               
                                                                                                                                    
TIMESTAMP=$(date +%Y%m%d_%H%M%S)                                                                                                   
SMOKE_DIR="${BASE_RESULTS_DIR}/smoke_test_${TIMESTAMP}"                                                                            
FULL_DIR="${BASE_RESULTS_DIR}/full_eval_${TIMESTAMP}"                                                                              
                                                                                                                                    
# ---------------- Pre-flight checks ----------------                                                                              
cd "$REPO_DIR"                                                                                                                     
                                                                                                                                    
if [ ! -f "$DATASET" ]; then                                                                                                       
    echo "ERROR: Dataset not found: $DATASET"                                                                                      
    exit 1                                                                                                                         
fi                                                                                                                                 
                                                                                                                                    
if [ "$USE_MOCK" = false ]; then                                                                                                   
    echo "Checking model server connectivity..."                                                                                   
    if ! curl -sf --max-time 10 "${ENDPOINT}/models" > /dev/null; then                                                             
        echo "ERROR: Cannot reach ${ENDPOINT}/models. Is your SSH tunnel/server up?"                                               
        exit 1                                                                                                                     
    fi                                                                                                                             
    echo "Model server reachable."                                                                                                 
else                                                                                                                               
    echo "RUNNING IN MOCK MODE (No network check required)."                                                                       
fi                                                                                                                                 
                                                                                                                                    
echo "============================================================"                                                                
echo "  $(echo "$MODEL" | tr '[:lower:]' '[:upper:]') Insurance Evaluation Runner"                                                 
echo "============================================================"                                                                
echo "Agent:     $AGENT"                                                                                                           
echo "Dataset:   $DATASET"                                                                                                         
echo "Endpoint:  $ENDPOINT"                                                                                                        
echo "Model:     $MODEL"                                                                                                           
echo "Mode:      $( [ "$USE_MOCK" = true ] && echo "MOCK" || echo "LIVE" )"                                                        
echo "Timestamp: $TIMESTAMP"                                                                                                       
echo "============================================================"                                                                
                                                                                                                                    
# ---------------- Harness runner ----------------                                                                                 
run_harness() {                                                                                                                    
    local out_dir="$1"                                                                                                             
    local limit="$2"                                                                                                               
    local workers="$3"                                                                                                             
                                                                                                                                    
    local args=(                                                                                                                   
        --agent "$AGENT"                                                                                                           
        --dataset "$DATASET"                                                                                                       
        --target "$TARGET"                                                                                                         
        --endpoint "$ENDPOINT"                                                                                                     
        --model "$MODEL"                                                                                                           
        --api-key "$API_KEY"                                                                                                       
        --gpu-cost-per-hour "$GPU_COST_PER_HOUR"                                                                                   
        --out-dir "$out_dir"                                                                                                       
        --workers "$workers"                                                                                                       
    )                                                                                                                              
                                                                                                                                    
    if [ "$USE_MOCK" = true ]; then                                                                                                
        args+=(--mock)                                                                                                             
    fi                                                                                                                             
                                                                                                                                    
    if [ -n "$limit" ] && [ "$limit" != "" ]; then                                                                                 
        args+=(--limit "$limit")                                                                                                   
    fi                                                                                                                             
                                                                                                                                    
    echo "Executing: python3 -m harness ${args[*]}"                                                                                
    python3 -m harness "${args[@]}"                                                                                                
}                                                                                                                                  
                                                                                                                                    
# ---------------- 1. Smoke test (3 cases) ----------------                                                                        
echo "[1/2] Starting Smoke Test (3 cases)..."                                                                                      
mkdir -p "$SMOKE_DIR"                                                                                                              
if run_harness "$SMOKE_DIR" 3 "$WORKERS_SMOKE"; then                                                                               
    echo "SUCCESS: Smoke test completed."                                                                                          
else                                                                                                                               
    echo "FAILURE: Smoke test failed. Check $SMOKE_DIR for logs/errors."                                                           
    exit 1                                                                                                                         
fi                                                                                                                                 
                                                                                                                                    
# ---------------- 2. Full run (120 cases) ----------------                                                                        
echo "[2/2] Starting Full Evaluation..."                                                                                           
mkdir -p "$FULL_DIR"                                                                                                               
if run_harness "$FULL_DIR" "" "$WORKERS_FULL"; then                                                                                
    echo "SUCCESS: Full evaluation completed."                                                                                     
    echo "------------------------------------------------------------"                                                            
    echo "RESULTS SUMMARY:"                                                                                                        
    echo "Full Eval Dir:  $FULL_DIR"                                                                                               
    echo "Smoke Test Dir: $SMOKE_DIR"                                                                                              
    echo "------------------------------------------------------------"                                                            
else                                                                                                                               
    echo "FAILURE: Full evaluation failed. Check $FULL_DIR for logs/errors."                                                       
    exit 1                                                                                                                         
fi                                                                                                                                 
