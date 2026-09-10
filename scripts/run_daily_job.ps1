# run_daily_job.ps1 — Wrapper that loads secrets and runs the daily job pipeline
# Called by Windows Task Scheduler at 08:00 AM
#
# This script:
# 1. Reads secrets.local.json (if present) and extracts API credentials
# 2. Sets $env:APIFY_TOKEN and $env:FIRECRAWL_KEY from the JSON
# 3. Invokes the Claude CLI to run RUN_PIPELINE.md
# 4. Logs all output to a dated log file

$workspace = "E:\Job Hunter 2026\Job Hunter"
$scriptDir = Join-Path $workspace "Scripts"
$secretsFile = Join-Path $scriptDir "secrets.local.json"
$pipelinePrompt = Join-Path $workspace "Scripts\RUN_PIPELINE.md"
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

# Exit code 0 is not proof that anything ran. On 2026-09-08 the run produced a
# clarifying question and no phases at all, returned 0, and this wrapper logged
# PIPELINE COMPLETE. Nobody found out for a day. So the output has to show
# evidence that the phases executed before the attempt counts as a success.
$ranMarker = 'Phase\s*1|Phase\s*5|PIPELINE COMPLETE'

# The marker above catches the symptom. The cause is here: the CLI was handed a
# bare file path as its prompt, so it read the run as "look at this file" rather
# than "do this". Scripts/daily_log_2026-08-30.txt has it verbatim, the agent
# answering "Path alone, no verb. What you want?" and exiting 0. Thirty-four
# runs ended that way. A path carries no verb and does not say that nobody is
# at the keyboard, so say both.
#
# Keep these literals ASCII. This file is UTF-8 with no BOM, so PowerShell 5.1
# reads it as ANSI and a single em dash silently terminates the string.
$pipelineInstruction = "Read the file at $pipelinePrompt and execute it end to end, starting now at Phase 1. This is the unattended 08:00 scheduled run: no operator is at the keyboard and nobody will read a question. Do not ask for confirmation and do not stop to clarify. Where the spec is ambiguous, follow the file and log the decision you made. Scripts/SAFE_MODE.json decides whether anything is actually submitted or emailed; honour it and never override it."

for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
    if ($attempt -gt 1) {
        $waitSeconds = 60 * ($attempt - 1)
        Add-Content -Path $logFile -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Retry $attempt of $maxAttempts in $waitSeconds s"
        Start-Sleep -Seconds $waitSeconds
    }

    $runOutput = $null
    try {
        # Not Tee-Object: -FilePath and -Variable are different parameter sets,
        # so asking for both threw "Parameter set cannot be resolved using the
        # specified named parameters" on every single attempt, before the CLI
        # was ever reached. Capture first, then write the log by hand.
        $runOutput = & $claudePath --print $pipelineInstruction 2>> $stderrFile
        $pipelineExitCode = $LASTEXITCODE
        if ($runOutput) { Add-Content -Path $logFile -Value $runOutput }
    }
    catch {
        Add-Content -Path $logFile -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Attempt ${attempt}: exception while running Claude CLI: $_"
        $pipelineExitCode = 1
    }

    $joined = ($runOutput -join "`n")
    if ($pipelineExitCode -eq 0 -and $joined -notmatch $ranMarker) {
        Add-Content -Path $logFile -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Attempt ${attempt}: exit 0 but no phase ran. The run answered instead of executing. Treating as a failure."
        $pipelineExitCode = 2
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

# --- 4. Publish the dashboard ---------------------------------------------
# Deliberately after the COMPLETE banner. run_history.py reads that banner to
# decide whether a day finished, so publishing first meant the run record was
# always built from a log that had not finished yet: today's run published as
# "incomplete, no duration" no matter how well it went.
# The pipeline runs here; GitHub cannot see E:. So rebuild locally and push,
# and the hosted dashboard is never more than one run behind. Telemetry-only
# by default: the public repo gets run status and counts, never company names.
# Set KESTREL_PRIVATE_REPO to also push the full dashboard to a private repo.
$publicRepo = "C:\Users\Sanket\Projects\kestrel"
$syncScript = Join-Path $scriptDir "sync_dashboard.py"
if (Test-Path (Join-Path $publicRepo ".git")) {
    Add-Content -Path $logFile -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Publishing telemetry to the public repo"
    & python $syncScript --mode public --repo $publicRepo 2>> $stderrFile | Tee-Object -FilePath $logFile -Append
}
if ($env:KESTREL_PRIVATE_REPO -and (Test-Path (Join-Path $env:KESTREL_PRIVATE_REPO ".git"))) {
    Add-Content -Path $logFile -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Publishing full dashboard to the private repo"
    & python $syncScript --mode private --repo $env:KESTREL_PRIVATE_REPO --no-rebuild 2>> $stderrFile | Tee-Object -FilePath $logFile -Append
}

exit $pipelineExitCode
