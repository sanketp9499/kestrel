"""daily_log.py -- Shared logging and profile loading for all pipeline scripts."""
import datetime, os, json, sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if not os.path.exists(WORKSPACE):
    WORKSPACE = "/sessions/eager-pensive-meitner/mnt/Job Hunter"
SCRIPTS      = os.path.join(WORKSPACE, "Scripts")
PROFILE_PATH = os.path.join(SCRIPTS, "profile.json")

_log_file = None

def init_log():
    global _log_file
    today = datetime.date.today().isoformat()
    _log_file = os.path.join(SCRIPTS, "daily_log_{}.txt".format(today))

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
