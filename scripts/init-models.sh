#!/usr/bin/env bash
# Register bge-m3 + bge-reranker-v2-m3 in the Xinference container (CPU).
# Requires: docker compose services up (model-service), auth disabled in compose.
set -euo pipefail

ENDPOINT="${XINFERENCE_ENDPOINT:-http://127.0.0.1:9997}"
SERVICE="${MODEL_SERVICE_CONTAINER:-enterprise-kb-model-service-1}"

wait_xinference() {
  for _ in $(seq 1 30); do
    if curl -sf "${ENDPOINT}/v1/models" >/dev/null 2>&1; then
      return 0
    fi
    sleep 5
  done
  echo "Xinference did not become ready at ${ENDPOINT}" >&2
  exit 1
}

ensure_model() {
  local uid="$1" name="$2" type="$3" venv="$4"
  for attempt in 1 2 3; do
    echo "Launching ${name} (attempt ${attempt}/3)..."
    local body
    body="$(curl -s -X POST "${ENDPOINT}/v1/models" \
      -H "Content-Type: application/json" \
      -d "{\"model_uid\":\"${uid}\",\"model_name\":\"${name}\",\"model_type\":\"${type}\",\"model_format\":\"pytorch\",\"device\":\"cpu\",\"download_hub\":\"modelscope\"}")"
    if [[ "${body}" == *"\"model_uid\""* ]]; then
      echo "${name} is ready."
      return 0
    fi
    if [[ "${body}" == *"sentence-transformers"* || "${body}" == *"sentence_transformers"* ]]; then
      echo "Installing sentence-transformers into the model virtual env..."
      docker compose exec -T "${SERVICE}" sh -c "${venv} -m pip install -q -U sentence-transformers" >/dev/null
    else
      echo "Unexpected launch response: ${body}" >&2
    fi
    sleep 3
  done
  echo "Failed to launch ${name}" >&2
  exit 1
}

wait_xinference
ensure_model "bge-m3" "bge-m3" "embedding" \
  "/root/.xinference/virtualenv/v4/bge-m3/default/3.12.13/bin/python"
ensure_model "bge-reranker-v2-m3" "bge-reranker-v2-m3" "rerank" \
  "/root/.xinference/virtualenv/v4/bge-reranker-v2-m3/default/3.12.13/bin/python"
echo "All local models are ready."
