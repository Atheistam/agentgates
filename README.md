# Agent Gates

A dated, reproducible measurement of what an **autonomous AI agent** can actually reach on the open
internet — and how far the emerging machine-access standards have really been deployed.

The measurement is produced by an agent with **no email inbox, no phone number, no government ID, no
payment instrument in its own name and no existing social account**, running unattended on a residential
connection. That constraint is the point: it isolates *identity* as the variable.

## Headline results

| Metric | Value |
|---|---|
| Account surfaces closed to a lone agent | **24 of 32 (75%)** |
| Top domains naming AI agents in `robots.txt` | see `data/standards_census.json` |
| Domains publishing a signed-agent key directory | ~0–1% |
| Domains publishing `llms.txt` | a small minority |
| Does declaring yourself an agent change what you get? | `data/declaration_test.json` — the whole response is fetched **four times per URL**, twice with each User-Agent, so ordinary page churn cannot be mistaken for a user-agent effect |
| Census, second independent sample | `data/standards_census_t2.json` (Tranco ranks 201–500) — a stability band, not an extension: Tranco's ranking regenerates daily, so tranche 1 is frozen and tranche 2 is a separate draw |

Run `python3 build_site.py` after the probes to regenerate the exact figures for the current date.

## The four gates

Every control that stopped the agent resolved to one of four missing things:

1. **An inbox** — email verification (Mastodon, most SaaS, GitHub at creation time)
2. **A SIM** — SMS/phone verification (Bluesky, Product Hunt, Stripe)
3. **A human willing to approve it** — manual registration approval (Lemmy instances, many Mastodon
   instances, Discourse forums)
4. **Accumulated reputation** — the account exists but cannot be heard (Hacker News)

CAPTCHA and WAF bot-challenges sit across all four as a delivery mechanism.

## What an agent can enter alone

Nostr (identity is a locally generated keypair, not an account), static hosting deploys, search-engine
submission endpoints, and file hosting. All of these are **publish-only** — they grant reach to nobody.

## The unstable-equilibrium finding

Ungated access to reach does not appear to be a stable state. `keyid.ai` marketed "free email for AI
agents, no signup, no human needed", then **withdrew its open pool because it "attracted bulk
account-farming rather than real deployments"**. The gate was correct; the demand was abusive. This
dataset recorded that cycle closing in real time.

## Method

- `probe_signup.py` — 32 named services. Reads `robots.txt` first, then makes **one** GET request to the
  account surface. Where `robots.txt` forbids a declared bot, nothing is fetched and the refusal is
  recorded as the result. Nothing is submitted; no form is posted.
- `probe_standards.py` — census over the Tranco traffic-ranked top domains: `robots.txt` AI-agent
  naming, `/.well-known/http-message-signatures-directory`, `llms.txt`, `ai.txt`. Every signal is
  content-validated at collection time: an HTTP 200 with an HTML body is a soft-404, not a file.
- `validate_census.py` — independent counter-check that re-fetches every flagged URL and rejects
  HTML, XML, empty and tiny WAF-challenge bodies. `run.sh` runs it after the census.
- `probe_keydirs.py` — fetches the flagged signature-directory URLs, records redirects, parses the
  JSON and classifies its shape (spec-shaped `{"keys": [...]}` set vs a single bare JWK).
- `probe_declaration.py` — the declaration experiment, on 32 account surfaces. Each URL is fetched
  **four times in one interleaved pass** (generic, declared, generic, declared) with only the
  `User-Agent` line differing. The repeat of each UA is a control: if the two generic passes disagree
  with each other, the page churns under a constant UA and the declared-vs-generic difference is
  **not** attributable to the header — that target is scored `dynamic_unresolved` rather than forced
  into a finding. Bodies are compared on whitespace-normalised, entity-decoded visible text and
  token-set overlap, so nonces, timestamps and formatting jitter do not read as an effect.
- `census_tranche.py` — the same content-validated census over the second sample (`data/tranche2_domains.txt`).
- `build_site.py` — static site generator, no JS, no external assets.
- `fieldnotes.json` — first-hand evidence from 30 unattended runs, with confidence levels.

All probes identify themselves honestly:

```
AgentGatesBot/0.1 (+https://agentgates.surge.sh; autonomous-agent reachability measurement; GET-only, non-destructive)
```

## What this is not

Not a bypass guide. Nothing here is a technique for defeating a control — the study's value depends on
the controls working as intended. No CAPTCHA was solved, no verification was spoofed, no policy evaded.
The measurements exist so that platform operators, agent developers and policymakers can see the
landscape as it actually is.

## Reproduce

```bash
python3 probe_signup.py        # ~2 min
python3 probe_standards.py     # ~7 min  (tranche 1: data/top_domains.txt, frozen)
python3 census_tranche.py      # ~40 min (tranche 2: Tranco ranks 201-500)
python3 validate_census.py     # ~5 min counter-check
python3 validate_census.py --file standards_census_t2.json
python3 probe_keydirs.py       # ~5 s
python3 probe_declaration.py   # ~10 min, 4 passes x 32 URLs
python3 build_site.py          # instant -> web/
```

Python 3.9+, standard library only. No API keys.

## Limits

One host, one geography, one point in time. If two probes of the same service disagree on different days,
that is bot mitigation being adaptive, not a bug. Surface signals (`<input type="email">`) are weaker
evidence than the first-hand attempts in `fieldnotes.json`; where the two disagree, believe the attempt.

## Data

- `data/signup_gates.json` / `.csv`
- `data/standards_census.json` / `.csv` — tranche 1 (Tranco top 200, frozen)
- `data/standards_census_t2.json` / `.csv` — tranche 2 (Tranco ranks 201–500, independent draw)
- `data/tranche2_domains.txt` — the tranche-2 domain list, kept so the sample is auditable
- `data/declaration_test.json` / `.csv` — the four-pass declaration experiment
- `data/fieldnotes.json`

## License

Data and text: CC BY 4.0. Code: MIT.
