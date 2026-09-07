#!/usr/bin/env pwsh
# Register bge-m3 + bge-reranker-v2-m3 in the Xinference container (CPU).
# Model weights download from ModelScope (faster in CN than HuggingFace).
# Auth is disabled in docker-compose.yml via XINFERENCE_AUTH_ADVANCED=false.

$ErrorActionPreference = "Stop"
$Endpoint = "http://127.0.0.1:9997"
$Service = "enterprise-kb-model-service-1"

function Wait-Xinference {
    for ($i = 0; $i -lt 30; $i++) {
        try {
            $null = Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 "$Endpoint/v1/models"
            return
        } catch {
            Start-Sleep -Seconds 5
        }
    }
    throw "Xinference did not become ready at $Endpoint"
}

function Ensure-Model {
    param(
        [string]$Uid,
        [string]$ModelName,
        [string]$ModelType,
        [string]$VenvPath
    )

    for ($attempt = 1; $attempt -le 3; $attempt++) {
        Write-Host "Launching $ModelName (attempt $attempt/3)..."
        $payload = (@{
            model_uid = $Uid
            model_name = $ModelName
            model_type = $ModelType
            model_format = "pytorch"
            device = "cpu"
            download_hub = "modelscope"
        } | ConvertTo-Json -Compress)
        $body = curl.exe -s -X POST "$Endpoint/v1/models" -H "Content-Type: application/json" -d $payload
        if ($body -match '"model_uid"') {
            Write-Host "$ModelName is ready."
            return
        }
        if ($body -match "sentence-transformers|sentence_transformers") {
            Write-Host "Installing sentence-transformers into the model virtual env..."
            docker exec $Service sh -c `
                "$VenvPath -m pip install -q -U sentence-transformers" `
                | Out-Null
        } else {
            Write-Warning "Unexpected launch response: $body"
        }
        Start-Sleep -Seconds 3
    }
    throw "Failed to launch $ModelName"
}

Wait-Xinference
Ensure-Model `
    -Uid "bge-m3" `
    -ModelName "bge-m3" `
    -ModelType "embedding" `
    -VenvPath "/root/.xinference/virtualenv/v4/bge-m3/default/3.12.13/bin/python"

Ensure-Model `
    -Uid "bge-reranker-v2-m3" `
    -ModelName "bge-reranker-v2-m3" `
    -ModelType "rerank" `
    -VenvPath "/root/.xinference/virtualenv/v4/bge-reranker-v2-m3/default/3.12.13/bin/python"

Write-Host "All local models are ready."
