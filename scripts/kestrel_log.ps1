# kestrel_log.ps1 - the one way PowerShell is allowed to write the daily log.
#
# The log is shared with daily_log.py, which appends UTF-8. PowerShell 5.1's
# defaults do not match it and cannot be made to:
#
#   Add-Content  writes ANSI/cp1252 by default. The phase banner U+2550 came
#                out as "---" and an em dash as the single byte 0x97, which is
#                not valid UTF-8, so the file stopped being decodable.
#   Add-Content -Encoding UTF8  writes a BOM on this edition. A BOM lands
#                mid-file wherever PowerShell happens to append, leaving a
#                stray U+FEFF inside the text.
#   Tee-Object   writes UTF-16LE and has no -Encoding parameter before
#                PowerShell 6. Every NUL byte in daily_log_2026-09-12.txt came
#                from the one line piped through it.
#
# So the bytes are written through .NET with an explicit encoder instead of
# through any cmdlet default. Keep this file ASCII-only: PowerShell 5.1 reads a
# BOM-less script as ANSI, and a non-ASCII literal here would be corrupted
# before it ever reached the encoder.

$script:KestrelUtf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Write-KestrelLog {
    <#
    .SYNOPSIS
      Append a line to a Kestrel log file as UTF-8 with no BOM.
    .PARAMETER Path
      The log file. Created if missing.
    .PARAMETER Message
      Text to append. Accepts pipeline input so command output can be piped
      straight in, which is what Tee-Object was being used for.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true, ValueFromPipeline = $true)]
        [AllowEmptyString()][string]$Message
    )
    process {
        [System.IO.File]::AppendAllText($Path, ($Message + "`r`n"), $script:KestrelUtf8NoBom)
    }
}

function Write-KestrelLogStamped {
    <#
    .SYNOPSIS
      Append a line prefixed with the same [yyyy-MM-dd HH:mm:ss] stamp the rest
      of the pipeline uses.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Message
    )
    Write-KestrelLog -Path $Path -Message ("[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] " + $Message)
}

function Write-KestrelLogTee {
    <#
    .SYNOPSIS
      Replacement for `... | Tee-Object -FilePath $log -Append`: echo each line
      to the console and append it to the log in the right encoding.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true, ValueFromPipeline = $true)]
        [AllowEmptyString()][string]$Message
    )
    process {
        Write-Output $Message
        Write-KestrelLog -Path $Path -Message $Message
    }
}
