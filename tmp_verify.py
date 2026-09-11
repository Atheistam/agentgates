import json
import subprocess

t2 = json.load(open('data/tranche2_domains.txt'.replace('.json', ''))) if False else None

# domain ranking bounds, read from the actual files
for name, path in (("t1", 'data/top_domains.txt'), ("t2", 'data/tranche2_domains.txt')):
    lines = [l.strip() for l in open(path) if l.strip()]
    print(name, "count", len(lines), "first", lines[0], "last", lines[-1])

print()
urls = [
    "https://archive.softwareheritage.org/browse/origin/?origin_url=https://github.com/Atheistam/agentgates.git",
    "https://github.com/Atheistam/agentgates/releases/tag/v1.0-run34",
    "https://tmpfiles.org/dl/wQw3mFkwoP83/llms.txt",
]
for u in urls:
    r = subprocess.run(["curl", "-sS", "-o", "/dev/null", "-L", "--max-time", "40",
                        "-w", "%{http_code}", "-A", "AgentGatesBot/1.0", u],
                       capture_output=True, text=True)
    print(r.stdout.strip(), u)
