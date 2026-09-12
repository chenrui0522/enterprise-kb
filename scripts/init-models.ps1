#!/usr/bin/env pwsh
# Launch bge-m3 + bge-reranker-v2-m3 in the Xinference container.
#
# GPU (default):
#   powershell -ExecutionPolicy Bypass -File scripts\init-models.ps1
# CPU fallback:
#   powershell -ExecutionPolicy Bypass -File scripts\init-models.ps1 -Device cpu
param(
    [string]$Endpoint = "http://127.0.0.1:9997",
    [ValidateSet("cuda", "cpu")][string]$Device = "cuda",
    [int]$GpuIndex = 0,
    [int]$TimeoutMinutes = 30
)
$ErrorActionPreference = "Stop"

function Get-ModelSnapshot {
    try {
        $response = Invoke-RestMethod -Uri "$Endpoint/v1/models" -TimeoutSec 5
        return [pscustomobject]@{ Ok = $true; Ids = @($response.data | ForEach-Object { $_.id }) }
    } catch {
        return [pscustomobject]@{ Ok = $false; Ids = @() }
    }
}

function Wait-Endpoint {
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        $snapshot = Get-ModelSnapshot
        if ($snapshot.Ok) { return }
        Start-Sleep -Seconds 5
    }
    throw "Xinference endpoint not reachable at $Endpoint"
}

function Wait-Model {
    param([string]$Uid)
    $deadline = (Get-Date).AddMinutes($TimeoutMinutes)
    while ((Get-Date) -lt $deadline) {
        $snapshot = Get-ModelSnapshot
        if ($snapshot.Ok -and ($snapshot.Ids -contains $Uid)) {
            Write-Host "$Uid is online."
            return
        }
        Start-Sleep -Seconds 5
    }
    throw "Timed out waiting for model $Uid"
}

function Ensure-Model {
    param(
        [string]$Uid,
        [string]$ModelName,
        [string]$ModelType
    )
    $snapshot = Get-ModelSnapshot
    if ($snapshot.Ok -and ($snapshot.Ids -contains $Uid)) {
        Write-Host "$Uid already online, skipping launch."
        return
    }
    $payload = @{
        model_uid    = $Uid
        model_name   = $ModelName
        model_type   = $ModelType
        model_engine = "sentence_transformers"
        model_format = "pytorch"
        download_hub = "modelscope"
        n_gpu        = if ($Device -eq "cuda") { 1 } else { 0 }
    }
    if ($Device -eq "cuda") { $payload["gpu_idx"] = @($GpuIndex) }
    $body = $payload | ConvertTo-Json -Compress
    Write-Host "Launching $ModelName on $Device ..."
    Invoke-RestMethod -Uri "$Endpoint/v1/models?wait_ready=False" -Method Post `
        -ContentType "application/json" -Body $body -TimeoutSec 30 | Out-Null
    Wait-Model -Uid $Uid
}

Wait-Endpoint
Ensure-Model -Uid "bge-m3" -ModelName "bge-m3" -ModelType "embedding"
Ensure-Model -Uid "bge-reranker-v2-m3" -ModelName "bge-reranker-v2-m3" -ModelType "rerank"

$models = (Invoke-RestMethod -Uri "$Endpoint/v1/models" -TimeoutSec 10).data
foreach ($model in $models) {
    $accelerators = ($model.accelerators -join ",")
    Write-Host ("{0} ({1}) accelerators=[{2}]" -f $model.id, $model.model_type, $accelerators)
}
Write-Host "All local models are ready on $Device."