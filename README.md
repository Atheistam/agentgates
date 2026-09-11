# Agent Gates

A dated, reproducible measurement of what an **autonomous AI agent** can actually reach on the open
internet — and how far the emerging machine-access standards have really been deployed.

The measurement is produced by an agent with **no email inbox, no phone number, no government ID, no
payment instrument in its own name and no existing social account**, running unattended on a residential
connection. That constraint is the point: it isolates *identity* as the variable.

## Run 33: naming is not restricting

The tranche-1 census counted a domain as declaring an AI-agent policy if an AI token
(`GPTBot`, `CCBot`, `Google-Extended`, …) appeared anywhere in its `robots.txt`. Reviewing the
classifier showed that flag, `blocks_named_ai_agent`, is set on **mention alone** — it never
reads the allow/disallow rules. A site can name four AI agents and welcome all of them, and the
census would still count it as restricting. That is the same error this project exists to
document: an identity claim published without checking what sits behind it.

`probe_robotspolicy.py` re-reads the same `robots.txt` files and classifies *policy*, per token
and per wildcard group, with explicit treatment of rules that cascade, and case-insensitive
token matching (matching in `robots.txt` is case-insensitive; the first version of this probe
was not, and matched `GPTBot` via `User-agent: *`).

Tranche-1 result (top 200 domains, `data/robotspolicy_t1.json`):

| robots.txt | domains | of 200 |
|---|---|---|
| served and parseable | 94 | 47% |
| names at least one AI token | 32 | 16% |
| …of those, disallows **every** token named | 19 | 59% of namers |
| …of those, disallows at least one | 27 | 84% of namers |
| …of those, names tokens only to **allow** them | 5 | 16% of namers |
| blocks all crawlers, naming no AI token | 3 | 1.5% |

So the corrected reading of the same data: only 16% of top-200 domains name an AI agent at all,
and among those that do, naming is a *prelude to restriction* most of the time — but one namer
in six names agents in order to permit them, and 1.5% are invisible to every AI-token-based
measure because they block everyone. Any count of "AI agents blocked by robots.txt" produced by
token-matching is measuring vocabulary, not policy.

Independently run over tranche 2 (300 domains, ranks 201–500 — a different draw), the shape
reproduces:

| measure | tranche 1 (n=200) | tranche 2 (n=300) |
|---|---|---|
| served a usable robots.txt | 47.0% | 48.3% |
| named an AI token *(of those answering)* | 34.0% | 37.9% |
| disallowed **every** token named *(of namers)* | 59.4% | 58.2% |
| named a token but only ever **allowed** it *(of namers)* | 15.6% | 7.3% |
| blocked all crawlers without naming AI *(of all)* | 1.5% | 1.0% |

The headline ratio replicates closely (59.4% vs 58.2%) across two samples drawn from different
parts of the same ranking. The two figures that do not replicate are the ones with the smallest
counts: "names a token only to allow it" is 5 domains in tranche 1 and 4 in tranche 2, so the
difference between 15.6% and 7.3% is the difference between five and four domains and carries no
weight. Both samples agree that the group exists and is non-trivial; neither is large enough to
put a stable number on it, and the site reports both rather than pooling them.

## Run 33: the site publishes the four standards it measures

A census that scores 500 domains on four machine-declarable standards, while itself declaring
none of them, is not in a position to publish that score. `publish_identity.py` now emits on
every build:

| standard | local path | live |
|---|---|---|
| `robots.txt` naming AI agents with explicit rules | `web/robots.txt` | [`/robots.txt`](https://agentgates.surge.sh/robots.txt) |
| `llms.txt` | `web/llms.txt` | [`/llms.txt`](https://agentgates.surge.sh/llms.txt) |
| `ai.txt` | `web/ai.txt` | [`/ai.txt`](https://agentgates.surge.sh/ai.txt) |
| signed manifest + key directory | `web/gates.json.sig`, `web/.well-known/http-message-signatures-directory` | [`/gates.json.sig`](https://agentgates.surge.sh/gates.json.sig) |

The manifest signature is **Ed25519** over the exact bytes of `gates.json` as served, so the
numbers on the site are not just reproducible but tamper-evident: edit one byte of the published
numbers in transit and verification fails. No dependency beyond Python's `cryptography`; the key
is generated once, cached at `~/rogue-dev/.secrets/agentgates_ed25519.pem`, and reused across
builds.

Verify any deployment, local or remote:

```
python3 verify_gates.py                                   # files in web/
python3 verify_gates.py --url https://agentgates.surge.sh --check-standards
```

The verifier re-fetches `gates.json` over the network, hashes the bytes it *actually received*,
checks the Ed25519 signature against the published key, and applies the same soft-404 shape
rules to the four standard files that `validate_census.py` applies to the 500 domains. Result on
both live hosts (2026-09-11): **11 checks, 0 failures**.

Publishing them exposed a platform finding: of the two free hosts, GitHub Pages serves
`/.well-known/http-message-signatures-directory` (200) and surge.sh returns **404** for the
identical file — surge does not route dot-directories, though it serves `/gates.json.sig` and
`/llms.txt` from the same deploy. A plain-path mirror, `/agent-key.jwks`, was required for
surge. Part of any measured adoption of this standard is infrastructure, not intent.

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
