[CmdletBinding()]
param(
    [string]$DataCenterId = "EUR-IS-2",
    [int]$VolumeInGb = 50,
    [string]$PodName = "paperclip-gpu-worker"
)

$ErrorActionPreference = "Stop"
$gpuTypeId = "NVIDIA RTX PRO 6000 Blackwell Server Edition MIG 1g.24gb"
$bootstrapPath = Join-Path $PSScriptRoot "youtube-automation\bootstrap.sh"

if (-not (Test-Path $bootstrapPath)) {
    throw "Bootstrap script not found: $bootstrapPath"
}

$apiKey = $env:RUNPOD_API_KEY
if ([string]::IsNullOrWhiteSpace($apiKey)) {
    $secureApiKey = Read-Host "Enter RunPod API key" -AsSecureString
    $apiKeyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureApiKey)
    try {
        $apiKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($apiKeyPointer)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($apiKeyPointer)
    }
}

$bootstrap = Get-Content -Path $bootstrapPath -Raw
$bootstrapBase64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($bootstrap))

$query = @'
mutation DeployPod($input: PodFindAndDeployOnDemandInput) {
  podFindAndDeployOnDemand(input: $input) {
    id
    name
    desiredStatus
    machineId
    costPerHr
  }
}
'@

$variables = @{
    input = @{
        cloudType             = "SECURE"
        containerDiskInGb     = 50
        dataCenterId          = $DataCenterId
        dockerArgs            = "echo '$bootstrapBase64' | base64 -d | /bin/bash"
        env                   = @(
            @{ key = "HOME"; value = "/workspace/paperclip-home" }
            @{ key = "OLLAMA_MODELS"; value = "/workspace/ollama-models" }
            @{ key = "OLLAMA_HOST"; value = "127.0.0.1:11434" }
            @{ key = "PAPERCLIP_TELEMETRY_DISABLED"; value = "1" }
        )
        gpuCount              = 1
        gpuTypeId             = $gpuTypeId
        imageName             = "runpod/pytorch:1.1.0-cu1281-torch280-ubuntu2204-cluster"
        minVcpuCount          = 2
        name                  = $PodName
        ports                 = ""
        volumeInGb            = $VolumeInGb
        volumeMountPath       = "/workspace"
    }
}

$body = @{
    query     = $query
    variables = $variables
} | ConvertTo-Json -Depth 10

$response = Invoke-RestMethod -Method Post `
    -Uri "https://api.runpod.io/graphql" `
    -Headers @{ Authorization = "Bearer $apiKey" } `
    -ContentType "application/json" `
    -Body $body

if ($response.errors) {
    throw ($response.errors | ConvertTo-Json -Depth 10)
}

$pod = $response.data.podFindAndDeployOnDemand
if (-not $pod.id) {
    throw "RunPod did not return a Pod ID."
}

Write-Host "Pod created: $($pod.id) ($($pod.desiredStatus))"
Write-Host "Check status and connection details in the RunPod console."