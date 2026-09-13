"""The daily log must be one encoding, and that encoding is UTF-8.

`Scripts/daily_log_2026-09-12.txt` is not a text file. `file` calls it "data",
grep calls it binary, and it contains three encodings at once because three
different writers append to it with three different defaults:

  daily_log.py (Python)  ->  UTF-8
  Add-Content (PS 5.1)   ->  ANSI/cp1252. Verified: the box-drawing banner
                             U+2550 is transliterated to "---" and an em dash
                             becomes the single byte 0x97, which is not valid
                             UTF-8 at all.
  Tee-Object (PS 5.1)    ->  UTF-16LE. It has no -Encoding parameter before
                             PowerShell 6, so it cannot be told otherwise. The
                             137 NUL bytes in that log start on the line right
                             after "Publishing telemetry to the public repo",
                             which is the one command piped through Tee-Object.

The damage was already being papered over: `run_history.read_log()` reads the
log as bytes and strips NULs before decoding. That is a symptom fix for exactly
this bug, and it only protects the one reader that has it.

So PowerShell gets a single logging function that writes UTF-8 without a BOM,
and nothing else is allowed to write to the log.
"""
import os
import subprocess
import sys
import tempfile

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HELPER = os.path.join(SCRIPTS, "kestrel_log.ps1")
RUNNER = os.path.join(SCRIPTS, "run_daily_job.ps1")

# Every character class the pipeline actually logs: the phase banner, the em
# dash the summaries are full of, an accented company name, an arrow.
SAMPLE = "banner ═══ dash — accent Québec arrow → done"


def _write_via_powershell(path, message):
    cmd = ("$ErrorActionPreference='Stop'; . '{}'; "
           "Write-KestrelLog -Path '{}' -Message '{}'").format(
        HELPER.replace("'", "''"), path.replace("'", "''"), message.replace("'", "''"))
    p = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                        "-Command", cmd], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=120)
    assert p.returncode == 0, p.stdout + p.stderr
    return open(path, "rb").read()


def test_the_helper_exists_at_all():
    assert os.path.exists(HELPER), "PowerShell has no shared log writer"


def test_round_trips_as_utf8():
    with tempfile.TemporaryDirectory() as d:
        raw = _write_via_powershell(os.path.join(d, "log.txt"), SAMPLE)
        assert raw.decode("utf-8").strip() == SAMPLE


def test_no_utf16_nul_bytes():
    """The Tee-Object signature."""
    with tempfile.TemporaryDirectory() as d:
        assert b"\x00" not in _write_via_powershell(os.path.join(d, "log.txt"), SAMPLE)


def test_no_bom_because_python_appends_to_the_same_file():
    """PS 5.1's -Encoding UTF8 writes a BOM. A BOM mid-file, where Python's
    appender left off, is a stray U+FEFF in the middle of the log."""
    with tempfile.TemporaryDirectory() as d:
        assert not _write_via_powershell(os.path.join(d, "log.txt"), SAMPLE).startswith(b"\xef\xbb\xbf")


def test_appends_rather_than_truncates():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "log.txt")
        _write_via_powershell(path, "first line")
        raw = _write_via_powershell(path, "second line")
        text = raw.decode("utf-8")
        assert "first line" in text and "second line" in text


def test_interleaves_cleanly_with_the_python_writer():
    """Both writers touch the same file in a real run."""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "log.txt")
        _write_via_powershell(path, "from powershell ══")
        with open(path, "a", encoding="utf-8") as f:
            f.write("from python → ok\n")
        _write_via_powershell(path, "from powershell again — ok")
        text = open(path, "rb").read().decode("utf-8")  # strict: must not raise
        assert text.count("\n") == 3


def test_nothing_else_writes_to_the_log():
    """Regression guard for the whole class. A new Add-Content or Tee-Object
    aimed at $logFile reintroduces the mixed encoding."""
    src = open(RUNNER, encoding="utf-8", errors="replace").read()
    offenders = [ln.strip() for ln in src.splitlines()
                 if "$logFile" in ln
                 and ("Add-Content" in ln or "Tee-Object" in ln
                      or "Out-File" in ln or "Set-Content" in ln)]
    assert offenders == [], "writers bypassing Write-KestrelLog:\n" + "\n".join(offenders)


def test_the_runner_actually_loads_the_helper():
    src = open(RUNNER, encoding="utf-8", errors="replace").read()
    assert "kestrel_log.ps1" in src


def test_the_runner_carries_a_bom_so_its_own_literals_survive():
    """PowerShell 5.1 reads a BOM-less script as ANSI. The banner literal
    U+2550 in this file was being decoded into three junk characters, and the
    old ANSI writer happened to encode them straight back to the original UTF-8
    bytes - two bugs cancelling out. Writing real UTF-8 removes the second one,
    so the first has to be fixed rather than relied on: the file needs a BOM.
    """
    raw = open(RUNNER, "rb").read()
    text = raw.decode("utf-8-sig")
    if any(ord(ch) > 127 for ch in text):
        assert raw.startswith(b"\xef\xbb\xbf"), (
            "run_daily_job.ps1 has non-ASCII literals but no BOM; "
            "PowerShell 5.1 will decode them as ANSI")


def test_stderr_redirection_is_forced_to_utf8_before_it_is_used():
    """`2>>` is Out-File underneath, and on PowerShell 5.1 that means UTF-16LE.

    Every non-empty daily_stderr_*.txt starts FF FE and is full of NUL bytes for
    this reason. It is not visible interactively, because this shell happens to
    carry a UTF-8 default - it shows up under Task Scheduler, which is where the
    real runs happen. Proven in a clean -NoProfile host: bare redirection wrote
    335 NUL bytes, the same redirection after setting the default wrote none.

    So the script must set it, and set it above the first redirection.
    """
    src = open(RUNNER, encoding="utf-8-sig").read()
    lines = src.splitlines()
    setting = next((i for i, ln in enumerate(lines)
                    if "PSDefaultParameterValues" in ln and "Out-File:Encoding" in ln), None)
    assert setting is not None, "run_daily_job.ps1 never forces the redirection encoding"
    first_redirect = next((i for i, ln in enumerate(lines)
                           if "2>>" in ln and not ln.lstrip().startswith("#")), None)
    if first_redirect is not None:
        assert setting < first_redirect, "the encoding is set after the first 2>> redirection"


def test_redirection_encoding_setting_actually_works(tmp_path):
    """Pin the mechanism itself, in a host with no profile loaded."""
    out = tmp_path / "err.txt"
    cmd = ("$PSDefaultParameterValues['Out-File:Encoding'] = 'utf8'; "
           "& cmd.exe /c \"echo redirect-probe 1>&2\" 2>> '{}'".format(str(out).replace("'", "''")))
    p = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                        "-Command", cmd], capture_output=True, text=True, timeout=120)
    assert out.exists(), p.stdout + p.stderr
    raw = out.read_bytes()
    assert b"\x00" not in raw
    assert b"redirect-probe" in raw.replace(b"\xef\xbb\xbf", b"")


def test_the_helper_stays_ascii_only():
    """kestrel_log.ps1 has no BOM on purpose, so it must not contain anything
    that ANSI decoding would damage."""
    text = open(HELPER, "rb").read().decode("utf-8")
    bad = sorted({ch for ch in text if ord(ch) > 127})
    assert bad == [], f"non-ASCII in a BOM-less script: {bad}"


def test_a_banner_literal_from_the_runner_round_trips():
    """End to end: PowerShell reads the real script, takes its real banner
    string, and writes it through the helper. What lands on disk must be the
    box-drawing character, not mojibake."""
    cmd = ("$ErrorActionPreference='Stop'; . '{}'; "
           "$lines = Get-Content '{}'; "
           "$i = ($lines | Select-String -Pattern 'STARTING PIPELINE' | "
           "Select-Object -First 1).LineNumber; "
           "Write-KestrelLog -Path '{{0}}' -Message $lines[$i - 2]")
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "log.txt")
        full = cmd.format(HELPER.replace("'", "''"), RUNNER.replace("'", "''")).format(
            path.replace("'", "''"))
        p = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                            "-Command", full], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=120)
        assert p.returncode == 0, p.stdout + p.stderr
        written = open(path, "rb").read().decode("utf-8")
        assert "═" in written, f"banner came through as: {written[:120]!r}"
