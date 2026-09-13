"""daily_log.py -- Shared logging and profile loading for all pipeline scripts."""
import datetime, os, json, sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# KESTREL_WORKSPACE lets this run off the laptop; the Actions scan sets it to
# the runner's checkout.
WORKSPACE = os.environ.get("KESTREL_WORKSPACE") or r"E:\Job Hunter 2026\Job Hunter"
if not os.path.exists(WORKSPACE):
    _sandbox = "/sessions/eager-pensive-meitner/mnt/Job Hunter"
    if os.path.exists(_sandbox):
        WORKSPACE = _sandbox
SCRIPTS      = os.path.join(WORKSPACE, "Scripts")
PROFILE_PATH = os.path.join(SCRIPTS, "sanket_profile.json")

_log_file = None

def init_log():
    """Pick today's log file, or a throwaway one when running under pytest.

    The daily log is the pipeline's run record: run_history.py reads these files
    to report, publicly, which days the machine actually worked. A test run that
    appends to the same file writes fixture traffic into that record, so the
    suite gets its own file that nothing reads.
    """
    global _log_file
    today = datetime.date.today().isoformat()
    if os.environ.get("KESTREL_TEST_LOG") or "PYTEST_CURRENT_TEST" in os.environ:
        name = "test_log_{}.txt".format(today)
    else:
        name = "daily_log_{}.txt".format(today)
    _log_file = os.path.join(SCRIPTS, name)


def use_test_log():
    """Send the rest of this process's logging to the throwaway file.

    init_log() keys off pytest's environment, which covers the suite but not an
    adapter a human runs by hand with --dry-run to check it still works. That
    traffic is not an application, and in the run record it is indistinguishable
    from one: a `--dry-run` against a nonexistent Greenhouse board appended
    "Greenhouse: resume upload failed at ..." to daily_log_2026-09-12.txt.

    Safe to call after logging has already started - adapters log their startup
    line before they finish parsing arguments.
    """
    global _log_file
    _log_file = os.path.join(
        SCRIPTS, "test_log_{}.txt".format(datetime.date.today().isoformat()))

def log(msg):
    if _log_file is None:
        init_log()
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    line = "[{}] {}".format(ts, msg)
    print(line, flush=True)
    with open(_log_file, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def load_profile():
    """Profile plus secrets, from whichever of them exist.

    The cloud scan runs with neither file: sanket_profile.json carries a phone
    number and resume paths, and secrets.local.json carries credentials, so
    neither belongs in a repo a runner checks out. Both are optional here and
    the environment fills in what matters, which for the scan is just the API
    tokens.
    """
    profile = {}
    if os.path.exists(PROFILE_PATH):
        with open(PROFILE_PATH, encoding="utf-8") as f:
            profile = json.load(f)
    secrets_path = os.path.join(SCRIPTS, "secrets.local.json")
    if os.path.exists(secrets_path):
        with open(secrets_path, encoding="utf-8") as f:
            profile.update(json.load(f))
    if os.environ.get("APIFY_TOKEN"):
        profile["apify_token"] = os.environ["APIFY_TOKEN"]
    if os.environ.get("FIRECRAWL_KEY"):
        profile["firecrawl_key"] = os.environ["FIRECRAWL_KEY"]
    return profile
