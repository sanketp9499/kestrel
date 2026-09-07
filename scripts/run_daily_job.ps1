# run_daily_job.ps1 — Wrapper that loads secrets and runs the daily job pipeline
# Called by Windows Task Scheduler at 08:00 AM
#
# This script:
# 1. Reads secrets.local.json (if present) and extracts API credentials
# 2. Sets $env:APIFY_TOKEN and $env:FIRECRAWL_KEY from the JSON
# 3. Invokes the Claude CLI to run RUN_PIPELINE.md
# 4. Logs all output to a dated log file

# Repo root = parent of this script's folder
$workspace = Split-Path -Parent $PSScriptRoot
$scriptDir = Join-Path $workspace "scripts"
$secretsFile = Join-Path $scriptDir "secrets.local.json"
$pipelinePrompt = Join-Path $workspace "scripts\RUN_PIPELINE.md"
$logFile = Join-Path $scriptDir "daily_log_$(Get-Date -Format 'yyyy-MM-dd').txt"

# Pipeline scripts log Unicode (arrows, box-drawing). Without this, Python
# defaults to cp1252 on Windows and dies with UnicodeEncodeError.
$env:PYTHONIOENCODING = "utf-8"

# ── 1. Load secrets from JSON if present ──────────────────────────────────────

if (Test-Path $secretsFile) {
    try {
        $secretsJson = Get-Content -Raw $secretsFile | ConvertFrom-Json

        if ($secretsJson.apify_token) {
            $env:APIFY_TOKEN = $secretsJson.apify_token
            Add-Content -Path $logFile -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Loaded APIFY_TOKEN from secrets.local.json"
        }

        if ($secretsJson.firecrawl_key) {
            $env:FIRECRAWL_KEY = $secretsJson.firecrawl_key
            Add-Content -Path $logFile -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Loaded FIRECRAWL_KEY from secrets.local.json"
        }
    }
    catch {
        Add-Content -Path $logFile -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] WARNING: Failed to parse secrets.local.json: $_"
    }
}
else {
    Add-Content -Path $logFile -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] INFO: secrets.local.json not found; skipping credential setup"
}

# ── 2. Resolve the Claude CLI binary ──────────────────────────────────────────

$claudePath = (Get-Command claudecode -ErrorAction SilentlyContinue).Source
if (-not $claudePath) {
    $claudePath = (Get-Command claude -ErrorAction SilentlyContinue).Source
}

if (-not $claudePath) {
    Add-Content -Path $logFile -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] ERROR: Neither 'claudecode' nor 'claude' found on PATH"
    exit 1
}

Add-Content -Path $logFile -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Resolved Claude CLI: $claudePath"

# ── 3. Run the pipeline ───────────────────────────────────────────────────────

Add-Content -Path $logFile -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] ════════════════════════════════════════════════════════════════════════════════"
Add-Content -Path $logFile -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] STARTING PIPELINE: RUN_PIPELINE.md"
Add-Content -Path $logFile -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] ════════════════════════════════════════════════════════════════════════════════"

# On 2026-09-06 the CLI returned "Error: No messages returned from query" and the
# whole day's run was lost — no jobs sourced, no applications, no summary email.
# That is a transient empty response, not a bad prompt, so a single attempt is the
# wrong shape for an unattended 08:00 job. Retry up to three times with backoff.
#
# stderr is written to its own file rather than merged with 2>&1: in Windows
# PowerShell 5.1, redirecting a native executable's stderr wraps every line in a
# NativeCommandError record, which is what made the Sep 6 log unreadable.

$maxAttempts = 3
$pipelineExitCode = 1
$stderrFile = Join-Path $scriptDir "daily_stderr_$(Get-Date -Format 'yyyy-MM-dd').txt"

for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
    if ($attempt -gt 1) {
        $waitSeconds = 60 * ($attempt - 1)
        Add-Content -Path $logFile -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Retry $attempt of $maxAttempts in $waitSeconds s"
        Start-Sleep -Seconds $waitSeconds
    }

    try {
        & $claudePath --print $pipelinePrompt 2>> $stderrFile | Tee-Object -FilePath $logFile -Append
        $pipelineExitCode = $LASTEXITCODE
    }
    catch {
        Add-Content -Path $logFile -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Attempt ${attempt}: exception while running Claude CLI: $_"
        $pipelineExitCode = 1
    }

    if ($pipelineExitCode -eq 0) { break }

    Add-Content -Path $logFile -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Attempt ${attempt} failed (exit code: $pipelineExitCode)"
}

if ((Test-Path $stderrFile) -and ((Get-Item $stderrFile).Length -gt 0)) {
    Add-Content -Path $logFile -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] stderr captured in: $stderrFile"
}

if ($pipelineExitCode -ne 0) {
    # Keep non-ASCII out of PowerShell string literals here. This file is UTF-8
    # with no BOM, so Windows PowerShell 5.1 reads it as ANSI: an em dash decodes
    # to a smart quote, which silently terminates the string and breaks the parse.
    Add-Content -Path $logFile -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] FATAL: pipeline failed $maxAttempts times, no applications were sent today"
}

Add-Content -Path $logFile -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] ════════════════════════════════════════════════════════════════════════════════"
Add-Content -Path $logFile -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] PIPELINE COMPLETE (exit code: $pipelineExitCode)"
Add-Content -Path $logFile -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] ════════════════════════════════════════════════════════════════════════════════"

exit $pipelineExitCode
