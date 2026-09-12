#!/usr/bin/env bash
# Launch bge-m3 + bge-reranker-v2-m3 in the Xinference container.
#
# GPU (default):
#   bash scripts/init-models.sh
# CPU fallback:
#   MODEL_DEVICE=cpu bash scripts/init-models.sh
set -euo pipefail

ENDPOINT="${XINFERENCE_ENDPOINT:-http://127.0.0.1:9997}"
DEVICE="${MODEL_DEVICE:-cuda}"
GPU_INDEX="${GPU_INDEX:-0}"
TIMEOUT_SECONDS="${MODEL_READY_TIMEOUT_SECONDS:-1800}"

model_ids() {
    curl -sf --max-time 5 "$ENDPOINT/v1/models"
}

wait_endpoint() {
    for _ in $(seq 1 60); do
        if model_ids >/dev/null 2>&1; then
            return 0
        fi
        sleep 5
    done
    echo "Xinference endpoint not reachable at $ENDPOINT" >&2
    exit 1
}

wait_model() {
    local uid="$1"
    local deadline=$(( $(date +%s) + TIMEOUT_SECONDS ))
    while [ "$(date +%s)" -lt "$deadline" ]; do
        if model_ids 2>/dev/null | grep -q "\"id\":\"$uid\""; then
            echo "$uid is online."
            return 0
        fi
        sleep 5
    done
    echo "Timed out waiting for model $uid" >&2
    exit 1
}

ensure_model() {
    local uid="$1" name="$2" type="$3" payload
    if model_ids 2>/dev/null | grep -q "\"id\":\"$uid\""; then
        echo "$uid already online, skipping launch."
        return 0
    fi
    if [ "$DEVICE" = "cuda" ]; then
        payload=$(printf '{"model_uid":"%s","model_name":"%s","model_type":"%s","model_engine":"sentence_transformers","model_format":"pytorch","download_hub":"modelscope","n_gpu":1,"gpu_idx":[%s]}' "$uid" "$name" "$type" "$GPU_INDEX")
    else
        payload=$(printf '{"model_uid":"%s","model_name":"%s","model_type":"%s","model_engine":"sentence_transformers","model_format":"pytorch","download_hub":"modelscope","n_gpu":0}' "$uid" "$name" "$type")
    fi
    echo "Launching $name on $DEVICE ..."
    curl -sf -X POST "$ENDPOINT/v1/models?wait_ready=False" \
        -H "Content-Type: application/json" -d "$payload" >/dev/null
    wait_model "$uid"
}

wait_endpoint
ensure_model bge-m3 bge-m3 embedding
ensure_model bge-reranker-v2-m3 bge-reranker-v2-m3 rerank
curl -sf "$ENDPOINT/v1/models"
echo
echo "All local models are ready on $DEVICE."