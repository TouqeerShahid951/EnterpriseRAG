param(
  [string]$BundleDir = $PSScriptRoot,
  [string]$InstallRoot = "C:\AgenticRAG",
  [switch]$ReplaceSource,
  [switch]$RefreshCaches,
  [switch]$SkipOllamaCheck
)

$ErrorActionPreference = "Stop"

function Require-File([string]$Path) {
  if (-not (Test-Path -LiteralPath $Path)) {
    throw "Required file not found: $Path"
  }
}

function Docker-Ok {
  docker version *> $null
  if ($LASTEXITCODE -ne 0) {
    throw "Docker is not available. Start Docker Desktop with Linux containers."
  }
}

function Directory-HasEntries([string]$Path) {
  if (-not (Test-Path -LiteralPath $Path)) {
    return $false
  }
  $entry = Get-ChildItem -LiteralPath $Path -Force | Select-Object -First 1
  return $null -ne $entry
}

function Import-CacheDirectory([string]$TargetDir, [string]$ArchiveName) {
  $archive = Join-Path $BundleDir $ArchiveName
  Require-File $archive
  New-Item -ItemType Directory -Force $TargetDir | Out-Null
  if ((-not (Directory-HasEntries $TargetDir)) -or $RefreshCaches) {
    tar -xzf $archive -C $TargetDir
    if ($LASTEXITCODE -ne 0) { throw "Failed to import $ArchiveName into $TargetDir" }
  } else {
    Write-Host "Cache folder already has files, skipping import: $TargetDir"
  }
}

function Read-EnvValue([string]$Name, [string]$Default) {
  foreach ($line in Get-Content -LiteralPath $EnvFile) {
    $trimmed = $line.Trim()
    if (($trimmed -eq "") -or $trimmed.StartsWith("#")) { continue }
    $parts = $trimmed -split "=", 2
    if (($parts.Length -eq 2) -and ($parts[0].Trim() -eq $Name)) {
      return $parts[1].Trim().Trim('"').Trim("'")
    }
  }
  return $Default
}

function Verify-RerankerCache {
  $sparseModel = Read-EnvValue "RAG_SPARSE_MODEL" "Qdrant/bm25"
  docker run --rm `
    -e "RAG_SPARSE_MODEL=$sparseModel" `
    -e RAG_SPARSE_CACHE_DIR=/models/fastembed `
    -e RAG_RERANKER_CACHE_DIR=/models/fastembed `
    -e AIRGAP_RUNTIME_OFFLINE=1 `
    -e HF_HUB_OFFLINE=1 `
    -e TRANSFORMERS_OFFLINE=1 `
    -e HF_DATASETS_OFFLINE=1 `
    -v "${FastembedCacheDir}:/models/fastembed" `
    agenticrag-api `
    python -m rag.ops.prewarm_fastembed --verify-only --all-rerankers
  if ($LASTEXITCODE -ne 0) { throw "FastEmbed sparse/reranker cache verification failed." }
}

function Verify-DoclingCache {
  $ocrBackend = Read-EnvValue "DOCLING_OCR_BACKEND" "onnxruntime"
  $ocrLangs = Read-EnvValue "DOCLING_OCR_LANGS" "english"
  docker run --rm `
    -e DOCLING_ARTIFACTS_PATH=/models/docling `
    -e "DOCLING_OCR_BACKEND=$ocrBackend" `
    -e "DOCLING_OCR_LANGS=$ocrLangs" `
    -e AIRGAP_RUNTIME_OFFLINE=1 `
    -e HF_HUB_OFFLINE=1 `
    -e TRANSFORMERS_OFFLINE=1 `
    -e HF_DATASETS_OFFLINE=1 `
    -v "${DoclingCacheDir}:/models/docling" `
    agenticrag-ingestion-worker `
    python -m rag_ingestion.ops.prewarm_docling --verify-only
  if ($LASTEXITCODE -ne 0) { throw "Docling/OCR cache verification failed." }
}

$BundleDir = (Resolve-Path -LiteralPath $BundleDir).Path
$ProjectDir = Join-Path $InstallRoot "AgenticRAG"
$FastembedCacheDir = Join-Path $ProjectDir "model-cache\fastembed"
$DoclingCacheDir = Join-Path $ProjectDir "model-cache\docling"
$EnvFile = Join-Path $BundleDir ".env.windows-airgap"
$SourceArchive = Join-Path $BundleDir "AgenticRAG-source.tgz"
$ImageArchive = Join-Path $BundleDir "agenticrag-runtime-images.tar"

Require-File $EnvFile
Require-File $SourceArchive
Require-File $ImageArchive
Require-File (Join-Path $BundleDir "backend-reranker-cache.tgz")
Require-File (Join-Path $BundleDir "backend-docling-cache.tgz")
Docker-Ok

if (-not $SkipOllamaCheck) {
  try {
    Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 5 | Out-Null
  } catch {
    throw "Ollama is not reachable at http://localhost:11434. Start Ollama or rerun with -SkipOllamaCheck."
  }
}

New-Item -ItemType Directory -Force $InstallRoot | Out-Null
if (Test-Path -LiteralPath $ProjectDir) {
  if (-not $ReplaceSource) {
    throw "$ProjectDir already exists. Rerun with -ReplaceSource to move it aside and deploy this bundle."
  }
  $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
  Rename-Item -LiteralPath $ProjectDir -NewName "AgenticRAG.backup-$stamp"
}

tar -xzf $SourceArchive -C $InstallRoot
if ($LASTEXITCODE -ne 0) { throw "Failed to extract source archive." }
Copy-Item -Force $EnvFile (Join-Path $ProjectDir ".env.windows-airgap")

docker load --input $ImageArchive
if ($LASTEXITCODE -ne 0) { throw "Failed to load Docker images." }

Import-CacheDirectory $FastembedCacheDir "backend-reranker-cache.tgz"
Import-CacheDirectory $DoclingCacheDir "backend-docling-cache.tgz"
Verify-RerankerCache
Verify-DoclingCache

Set-Location $ProjectDir
docker compose --env-file .env.windows-airgap up -d --no-build --pull never --wait
if ($LASTEXITCODE -ne 0) { throw "Docker Compose deployment failed." }

Write-Host ""
Write-Host "AgenticRAG is deployed."
Write-Host "Frontend: http://localhost:3000"
Write-Host "API:      http://localhost:8000"
Write-Host "Check:    docker compose --env-file .env.windows-airgap ps"
