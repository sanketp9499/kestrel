"""daily_log.py -- Shared logging and profile loading for all pipeline scripts."""
import datetime, os, json, sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

WORKSPACE = r"E:\Job Hunter 2026\Job Hunter"
if not os.path.exists(WORKSPACE):
    WORKSPACE = "/sessions/eager-pensive-meitner/mnt/Job Hunter"
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

def log(msg):
    if _log_file is None:
        init_log()
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    line = "[{}] {}".format(ts, msg)
    print(line, flush=True)
    with open(_log_file, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def load_profile():
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
