"""Runs once per GitHub Actions trigger: checks Rutgers, alerts Discord on newly opened sections."""
import json
import os
import urllib.request

CFG = json.load(open("config.json"))
YEAR, TERM, CAMPUS = CFG["year"], CFG["term"], CFG["campus"]
WANTED = set(CFG["indexes"])
WEBHOOK = os.environ["DISCORD_WEBHOOK"]
STATE_FILE = "state.json"
HEADERS = {"User-Agent": "rutgers-class-notifier (personal use)"}
BASE = "https://classes.rutgers.edu/soc/api"
Q = f"year={YEAR}&term={TERM}&campus={CAMPUS}"


def get_json(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def send(text):
    body = json.dumps({"content": text}).encode("utf-8")
    req = urllib.request.Request(WEBHOOK, data=body,
                                 headers={**HEADERS, "Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=30).read()


try:
    was_open = set(json.load(open(STATE_FILE)))
except Exception:
    was_open = set()

open_now = set(get_json(f"{BASE}/openSections.json?{Q}")) & WANTED
newly = sorted(open_now - was_open)

if newly:
    names = {}
    try:
        for c in get_json(f"{BASE}/courses.json?{Q}"):
            for s in c.get("sections", []):
                if s.get("index") in newly:
                    names[s["index"]] = f"{c.get('title', '').title()} ({c.get('courseString', '')}) sec {s.get('number', '')}"
    except Exception:
        pass
    for idx in newly:
        link = f"https://sims.rutgers.edu/webreg/editSchedule.htm?login=cas&semesterSelection={TERM}{YEAR}&indexList={idx}"
        send(f"@here **OPEN:** {names.get(idx, 'Index ' + idx)}\nIndex **{idx}**\nRegister now: {link}")

print("open now:", sorted(open_now) or "none", "| new alerts:", newly or "none")
json.dump(sorted(open_now), open(STATE_FILE, "w"))
