#!/usr/bin/env python3
"""Did the IndexNow acceptance actually put anything in an index?

Last run we pushed 22 URLs at IndexNow and got HTTP 202, and wrote next to that
result: "an accepted push is a claim about a queue, not a claim about an index."
This probe tries to settle it from the outside.

Three traps this probe is built to avoid, because the first version of it fell
into all three and scored every engine as a success:

  1. Query echo. A results page repeats your query in its <title>, its og:url and
     its search box. A substring search for the domain therefore always hits.
     Only a *result link* to the domain counts.
  2. Challenge pages. DuckDuckGo answers an agent with HTTP 202 and an anomaly
     interstitial; Mojeek answers HTTP 200 with a captcha document. Both are
     200-class statuses with no results in them.
  3. Soft success. Bing answers 200 with ten real result blocks - for an
     unrelated domain. Results were returned; the query was ignored. Counting
     result blocks would score that as "found".

So each engine is scored on: were result links extracted at all, how many, and
how many point at the target domain. A domain that appears zero times in the
result set is absent from that index, whatever the status code said.
"""
import datetime, html, json, re, urllib.parse, urllib.request, urllib.error

TARGET = "agentgates.surge.sh"
CONTROL = "archive.softwareheritage.org"   # plural content, surely indexed
OUT = "data/index_presence.json"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

ENGINES = [
    # id, endpoint template, result-block regex, result-link extractor
    ("bing_html", "https://www.bing.com/search?q={q}",
     r'<li class="b_algo".*?</li>', r'<cite[^>]*>(.*?)</cite>'),
    ("bing_rss", "https://www.bing.com/search?format=rss&q={q}",
     r'<item>.*?</item>', r'<link>(.*?)</link>'),
    ("duckduckgo_lite", "https://lite.duckduckgo.com/lite/?q={q}",
     r'<a[^>]+class="result-link"[^>]*>.*?</a>', r'href="([^"]+)"'),
    ("mojeek", "https://www.mojeek.com/search?q={q}",
     r'<li>\s*<h2>.*?</li>', r'<a[^>]+href="(https?://[^"]+)"'),
]

CHALLENGE = re.compile(
    r"(captcha|anomaly|unusual traffic|verify you are human|are you a robot|"
    r"automated (queries|requests)|access denied|blocked)", re.I)


def fetch(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "text/html,application/xhtml+xml,*/*",
        "Accept-Language": "en-US,en;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:8000]
    except Exception as e:
        return "EXC", str(e)[:300]


def domain_of(u):
    m = re.match(r"https?://([^/]+)", u.strip())
    return m.group(1).lower().lstrip("www.") if m else ""


def evaluate(body, block_re, link_re, domain):
    """Return (n_blocks, n_result_links, hits_for_domain, sample_domains, challenge)."""
    if not isinstance(body, str):
        return 0, 0, 0, [], False
    challenge = bool(CHALLENGE.search(body[:6000]))
    blocks = re.findall(block_re, body, re.S)
    links = []
    for b in blocks:
        links += re.findall(link_re, b)
    if not links:                      # no blocks matched: try whole document
        links = re.findall(r'href="(https?://[^"]+)"', body)
        links = [l for l in links if "bing.com/ck/a" not in l]
    doms = [domain_of(html.unescape(l)) for l in links]
    doms = [d for d in doms if d and "bing.com" not in d and "mojeek.com" not in d
            and "duckduckgo.com" not in d]
    hits = sum(1 for d in doms if domain.lower().lstrip("www.") in d)
    return len(blocks), len(doms), hits, sorted(set(doms))[:8], challenge


res = {
    "probe": "index presence after IndexNow submission (100% of URLs queued, 0 verified)",
    "question": "does an unattended agent have any way to confirm that a search engine "
                "received and stored the pages it asked it to index?",
    "target": TARGET,
    "positive_control": CONTROL,
    "ran_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "engines": {},
}

for name, tmpl, block_re, link_re in ENGINES:
    entry = {}
    for label, domain in (("target", TARGET), ("control", CONTROL)):
        url = tmpl.format(q=urllib.parse.quote(f"site:{domain}"))
        status, body = fetch(url)
        nb, nl, hits, sample, ch = evaluate(body, block_re, link_re, domain)
        entry[label] = {
            "query": f"site:{domain}", "url": url, "http_status": status,
            "result_blocks": nb, "result_links": nl, "links_to_query_domain": hits,
            "sample_result_domains": sample, "challenge_page": ch,
            "bytes": len(body) if isinstance(body, str) else 0,
        }
    t, c = entry["target"], entry["control"]
    if t["challenge_page"]:
        verdict = "refused_to_answer (challenge page despite 200-class status)"
    elif t["links_to_query_domain"] > 0:
        verdict = "indexed - target appears in this engine's result set"
    elif t["result_links"] == 0:
        verdict = "empty result set - absent from this index"
    else:
        verdict = (f"query ignored - {t['result_links']} result links returned, "
                   f"none for the target (junk results)")
    entry["verdict"] = verdict
    entry["control_reads"] = ("control appears in results - this engine's output is "
                              "readable in principle"
                              if c["links_to_query_domain"] > 0 else
                              "control absent too - this engine's output is NOT readable")
    res["engines"][name] = entry

with open(OUT, "w") as f:
    json.dump(res, f, indent=2)

for name, e in res["engines"].items():
    t, c = e["target"], e["control"]
    print(f"{name:18s} [{t['http_status']}] blocks={t['result_blocks']} links={t['result_links']} "
          f"hits={t['links_to_query_domain']} challenge={t['challenge_page']} | "
          f"control_hits={c['links_to_query_domain']}\n{'':18s} -> {e['verdict']}\n"
          f"{'':18s} -> {e['control_reads']}")
