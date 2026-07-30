# Cowrie

**A cross-border payment network for Africa.**

### Try it now

| | |
|---|---|
| **Live app** | **https://cowrie-web-production.up.railway.app** |
| **API** | https://cowrie-api-production.up.railway.app |
| **Interactive API docs** | https://cowrie-api-production.up.railway.app/docs |
| **Public transparency page** | https://cowrie-web-production.up.railway.app/transparency |

Open **`/pay`**, create an account with any phone number and email — the
verification code is shown on screen — then send a transfer and watch it settle
in about thirty seconds. Nothing is seeded, so what you see is what you did.

On Android, Chrome will offer to install CowriePay to your home screen. On
iPhone, Safari installs it through **Share → Add to Home Screen**. Either way it
opens full-screen with no browser chrome.

The admin console at `/admin` signs in with `amara@cowrie.demo` / `cowrie-demo`.

Cowrie settles payments between African currencies in seconds at under 1% in
fees, using **cUSDC** — a USD-pegged stablecoin — as the neutral bridge between
local on-ramps and off-ramps. The launch corridor is **Nigeria → Kenya**: naira
leaves a Nigerian bank account, moves through cNGN and cUSDC on the Base
network, and lands as Kenyan shillings in an M-Pesa wallet about thirty seconds
later.

If anything stalls, the sender is refunded within ten minutes. Every transfer
either completes or comes back.

---

## Why this exists

The most expensive currency for Africans to use is their own.

The World Bank puts the cost of sending $200 within Sub-Saharan Africa at
**7.4%**, against a global average of 6.2% and a UN SDG target of 3%
(*Remittance Prices Worldwide*, Issue 53, Q1 2025). Settlement takes two to five
days. 57% of African adults are unbanked. And the AfCFTA is projected to triple
intra-African trade by 2035 — onto rails that cannot carry it.

The reason is structural, and it is three things:

1. **There is no direct NGN/KES market.** Naira converts to dollars, dollars
   convert to shillings, and a spread is taken twice.
2. **Correspondent banking sits in the middle**, adding days and fees to a
   transfer between two countries that share a continent.
3. **The rails skip mobile money** — the account most Africans actually use.
   PAPSS connects thirteen central banks and still cannot pay an M-Pesa wallet.

Cowrie removes all three. One atomic on-chain transaction replaces the
correspondent chain, cUSDC replaces the double dollar detour, and the payout
lands directly in the wallet the recipient already has.

**Cowrie's take on a $200 transfer is 0.90% against the region's 7.4% average.**

---

## What is real, and what is not

This is a prototype built to demonstrate a system design. Being precise about
this matters more than making it sound finished.

**Real, and running:**

- The complete settlement state machine, including every refund path
- The hash-chained, tamper-evident audit log, and its verification
- The fee model and the sub-1% corridor arithmetic
- The Solidity contracts — they compile, pass 22 tests, and settle real
  transactions on a local chain
- Sanctions screening logic and the enforcement path behind it
- API key authentication, idempotency, signed webhooks, and rate limiting

**Simulated, deliberately:**

- **Mono** (naira on-ramp), **Safaricom Daraja** (M-Pesa payout), **Smile ID**
  (identity), and the **reserve banking partner**. No live credentials for any
  of them exist in this repository.
- **Base mainnet.** The contracts run on a local Anvil node, never on Base.
- **The USD reserves.** The figures are seeded.

This is the position SRS §2.5 constraint 2 sets out: *"No banking partner is
integrated for cUSDC reserves and the smart contracts aren't yet deployed on
Base, so cUSDC's behaviour is simulated with seeded demo data."*

**No real money moves through this system.** Every screen that shows a number
that would be real in production says so, and `GET /transparency` returns the
full disclosure as structured data.

---

## Getting it running

### What you need

| | Version | Required? |
|---|---|---|
| **Python** | 3.12+ | Yes |
| **uv** | latest | Yes — `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| **Node.js** | 20+ | For the web surfaces |
| **Docker** | any recent | Optional — only for PostgreSQL/Redis |
| **Foundry** | latest | Optional — only for the contracts |

You do **not** need Docker or Foundry to run the application. It defaults to a
local SQLite file and an in-process model of Base, so it starts on a clean
machine with nothing else installed.

### The three-command version

```bash
git clone https://github.com/owizdom/cowrie.git
cd cowrie
make setup && make dev
```

Open **http://localhost:8000/docs**.

### Step by step

**1. Clone and enter the repository**

```bash
git clone https://github.com/owizdom/cowrie.git
cd cowrie
```

**2. Install uv, if you do not have it**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

On Windows: `powershell -c "irm https://astral.sh/uv/install.ps1 | iex"`

**3. Install dependencies**

```bash
make setup
```

This creates a Python 3.12 virtual environment in `orchestration/.venv`,
installs the API, and installs the Foundry libraries if `forge` is present. uv
downloads Python 3.12 itself if your system does not have it.

**4. Start the API**

```bash
make dev
```

On first start it creates the database and provisions two things, and only two:
the five console operators of SRS §2.3, and the OFAC/UN/EU lists that FR 1.3
screens against. There is no sample dataset — no users, no transfers, no KYC
submissions, no partner keys, no reserve history. Everything else arrives
through the product, which is the only way to know the product works. You will
see:

```
[provision] 5 console operators, 6 sanctions entries
[provision] console: amara@cowrie.demo / cowrie-demo
[cowrie] chain: simulated - Base (simulated in-process)
[cowrie] corridor: NGN -> KES
```

**5. Check it works**

```bash
curl http://localhost:8000/health
```

Then open the interactive API documentation at
**http://localhost:8000/docs**.

### Getting into each surface

Only the admin console has an account waiting for you. The other three are
self-serve, because they are the sign-up flows the requirements describe and a
seeded shortcut past them would leave FR 1.1 and FR 4.1 untested.

| Surface | How you get in |
|---|---|
| **Admin console** | `amara@cowrie.demo` / `cowrie-demo` — provisioned at first boot |
| **CowriePay** | `POST /auth/register/start` → `POST /auth/register/verify` (FR 1.1). With no email provider configured the one-time code is returned in the response and shown on screen |
| **Cowrie API** | `POST /v1/partners` returns a key pair. The secret is shown once |
| **Regulator portal** | `POST /auth/regulator/register` with an email and password. Read-only by construction |

Other admin roles, to see the RBAC refuse things: `kwame@cowrie.demo` (Officer),
`zainab@cowrie.demo` (Reviewer), `david@cowrie.demo` (Engineer),
`blessing@cowrie.demo` (Support). All use the password `cowrie-demo`.

`GET /demo/config` returns the same map from the running service, so it cannot
drift from this table without the test suite noticing.

### Send a transfer from the command line

```bash
# 1. Create an account. The code is returned here because no email provider is
#    configured; with one set up it is emailed and omitted from the response.
START=$(curl -s -X POST localhost:8000/auth/register/start \
  -H 'Content-Type: application/json' \
  -d '{"fullName":"Ada Okoro","phone":"+2348012345678","email":"ada@example.com","country":"NG","pin":"123456"}')
CHALLENGE=$(echo "$START" | python3 -c 'import sys,json;print(json.load(sys.stdin)["challengeId"])')
CODE=$(echo "$START" | python3 -c 'import sys,json;print(json.load(sys.stdin)["code"])')

# 2. Verify it. Only now does a User row exist (FR 1.1).
TOKEN=$(curl -s -X POST localhost:8000/auth/register/verify \
  -H 'Content-Type: application/json' \
  -d "{\"challengeId\":\"$CHALLENGE\",\"code\":\"$CODE\"}" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')

# 3. Link a bank account and fund the wallet, so there is something to send.
curl -s -X POST localhost:8000/kyc/link-account -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"kind":"BANK","institution":"Guaranty Trust Bank","accountNumber":"0123454417"}'
curl -s -X POST localhost:8000/kyc/top-up -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"amount":"500000"}'

# 4. Get an itemised quote, locked for 60 seconds
curl -s -X POST localhost:8000/quotes -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"amount":"100000"}' | python3 -m json.tool
```

You will get back every fee on its own line, and the exact amount the recipient
receives:

```json
{
  "source":      { "amount": "100000.00", "currency": "NGN" },
  "destination": { "amount": "8387.36",   "currency": "KES" },
  "fees": {
    "fxSpread":        "350.00",
    "networkGas":      "6.12",
    "liquiditySpread": "150.00",
    "cowrieFee":       "400.00",
    "total":           "906.12"
  },
  "costPercent": "0.91",
  "secondsRemaining": 59
}
```

Take the `id` from that response and confirm the transfer:

```bash
# 5. Create it
curl -s -X POST localhost:8000/transfers -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"quoteId":"<paste the quote id>","recipientName":"Mary Wanjiru","recipientMsisdn":"+254712345678","scenario":"HAPPY"}'

# 6. Confirm with the PIN, then watch it settle
curl -s -X POST localhost:8000/transfers/<id>/confirm -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"pin":"123456"}'
```

It settles in about 30 seconds: 12 confirmations at 2 second blocks is 24 of
them, which is exactly what FR 3.3 specifies.

---

## Running the parts you can skip

### PostgreSQL and Redis

The SRS specifies PostgreSQL 15 and Redis 7. SQLite is the default so the
project starts with no infrastructure, but to run against the real thing:

```bash
make infra
export COWRIE_DATABASE_URL=postgresql+psycopg://cowrie:cowrie@localhost:5432/cowrie
export COWRIE_REDIS_URL=redis://localhost:6379/0
make dev
```

### The contracts, on a real chain

The Solidity contracts do not have to be simulated. With Foundry installed you
can run them on a local node and settle genuine on-chain transactions:

```bash
make anvil     # terminal 1 - a local chain with 2 second blocks
make chain     # terminal 2 - deploy the contracts
make dev-chain # terminal 3 - point the API at them
```

Transfers now produce real transaction hashes you can inspect:

```bash
cast receipt <txHash> --rpc-url http://127.0.0.1:8545
```

This is still entirely local. **There is no code path in this repository that
reaches Base mainnet or Base Sepolia**, and no funded key exists.

---

## Testing

```bash
make test
```

**99 Python tests** covering the requirements — the fee arithmetic, the state
machine's refusal to make illegal moves, the settlement guarantee, the mint
gate, the audit chain, and API idempotency.

**22 Foundry tests** covering the contracts, including two fuzz properties: that
cUSDC supply can never exceed attested reserves, and that a bridge call
conserves value.

Each test is named after the requirement it holds the system to, so a failure
tells you which part of the SRS broke.

```bash
make test-api        # Python only
make test-contracts  # Solidity only
make lint            # ruff + forge fmt
```

---

## How it is put together

```
cowrie/
├── orchestration/   Python 3.12 + FastAPI — the SRS "orchestration tier"
│   └── cowrie/
│       ├── models.py       the class diagram, 1:1
│       ├── enums.py        the state machine's transition table
│       ├── adapters/       one per external actor, all simulated
│       ├── services/       named after the sequence diagram's participants
│       ├── routers/        one per surface
│       └── middleware/     rate limiting (§3.4) and NFR 1 timing
├── surfaces/        Next.js — all six user interfaces
├── cusdc/           Foundry — cUSDC, cNGN, the bridge, the 3-of-5 treasury
└── docs/
    └── uml/                the five analysis models
```

### The design decision that shapes everything

The state machine diagram is not documentation of the code — it is a table the
code is checked against. `enums.ALLOWED_TRANSITIONS` is a transcription of
`docs/uml/cowrie_state.puml`, and every state change goes through
`transfer_service.transition()`, which **raises** on any move that is not an
arrow on the diagram.

That has a consequence worth stating: the diagram and the implementation cannot
drift. A test asserts that every non-terminal state can reach a terminal one,
which is NFR 3 — *"no transfer is left in the system"* — proved as a property of
the graph rather than demonstrated on a handful of happy paths.

`GET /demo/state-machine` serves the table straight from that constant, so the
published diagram is always the enforced one.

---

## Seeing the requirements work

Some of these are more convincing than a screenshot.

**The settlement guarantee (NFR 3).** Every branch of the state machine is
reachable through the scenario switch:

```bash
curl localhost:8000/demo/scenarios | python3 -m json.tool
```

Pass `"scenario": "CHAIN_ROLLBACK"` when creating a transfer and watch it accrue
confirmations, hit a reorganisation, and refund. `PAYOUT_FAILED`,
`ONRAMP_TIMEOUT`, `MONO_ERROR` and `SANCTIONS_HOLD` each drive a different
labelled arrow. All six end in a terminal state; none strands the money.

**The tamper-evident log (NFR 5).** Verify the chain, then break it:

```bash
ATOKEN=$(curl -s -X POST localhost:8000/auth/admin/login -H 'Content-Type: application/json' \
  -d '{"email":"amara@cowrie.demo","password":"cowrie-demo"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')

curl -s localhost:8000/admin/audit/verify -H "Authorization: Bearer $ATOKEN"
# {"valid": true, "entriesChecked": 12, ...}   <- however many actions you have taken

sqlite3 cowrie-demo.db "UPDATE audit_log SET action='tampered' WHERE seq=2;"

curl -s localhost:8000/admin/audit/verify -H "Authorization: Bearer $ATOKEN"
# {"valid": false, "brokenAtSeq": 2, "reason": "entry contents do not match its recorded hash"}
```

It names the row. Deleting a row is caught the same way.

**The unbacked-mint refusal (FR 3.2).** Try to create cUSDC without a confirmed
dollar deposit:

```bash
curl -s -X POST localhost:8000/admin/reserve/mint \
  -H "Authorization: Bearer $ATOKEN" -H 'Content-Type: application/json' \
  -d '{"amount":"1000000","usdDepositReference":""}'
# 400 - "No USD deposit reference supplied; mint refused (FR 3.2)"
```

The same rule is enforced in the contract itself, where there is no plain
`mint()` at all — only `mintWithAttestation`, and each attestation can be spent
once.

**The signed regulator report (FR 5.3).** The signature covers the CSV bytes, so
you can check it the way a regulator would — recompute the hash from the file
itself:

```bash
EXPORT=$(curl -s -X POST "localhost:8000/regulator/exports?regulator=SEC_NIGERIA&days=30" \
  -H "Authorization: Bearer $ATOKEN")
ID=$(echo "$EXPORT" | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')

curl -s "localhost:8000/regulator/exports/$ID/download" -H "Authorization: Bearer $ATOKEN" \
  | python3 -c '
import hashlib, sys
doc = sys.stdin.read()
body = "".join(l for l in doc.splitlines(keepends=True) if not l.startswith("#"))
stated = [l for l in doc.splitlines() if l.startswith("# Content SHA-256:")][0].split(": ")[1]
print("recomputed:", hashlib.sha256(body.encode()).hexdigest())
print("stated    :", stated)
print("match     :", hashlib.sha256(body.encode()).hexdigest() == stated)'
# match     : True
```

The report is stored at the moment it is signed and served unchanged
afterwards, so a transfer that settles later cannot quietly rewrite a document
that has already been attested to. `GET /regulator/exports/{id}/verify` runs the
same check server-side. Without a session, both endpoints return 401 — this is
the pseudonymised transaction register, not a public file.

---

## Diagram reconciliation

One inconsistency between the two analysis models, resolved in favour of the
state machine and recorded rather than quietly patched:

The class diagram's `TransactionState` enum lists **ten** values. The state
machine diagram defines a transition `Quoted --> Cancelled : quote expires
(> 60s)`, which needs an eleventh. `CANCELLED` is included, and the reasoning is
in the docstring of `orchestration/cowrie/enums.py`.

---

## Requirements coverage

`GET /requirements` maps every functional and non-functional requirement to the
module that implements it, served by the running system so it cannot go stale
against a file nobody re-reads.

Two of those mappings are executable rather than asserted:
`GET /demo/state-machine` returns the transition table the code actually
enforces, and `GET /health/performance` returns the NFR 1 latency budgets as
measured over recent requests.

---

## What is missing, honestly

1. **No HSM.** NFR 2 wants signing keys in tamper-resistant hardware. Every
   signature in this build goes through one function,
   `security.sign_with_platform_key`, which is an HMAC and says so. Regulator
   exports produced by it are labelled `demo-signed`.
2. **No VASP licences.** NFR 4 asserts active SEC and CMA registration. That is
   a legal status, not a feature. The transparency page states the real
   position.
3. **No OpenTelemetry collector is configured by default.** The exporter is
   wired — set `COWRIE_OTEL_ENDPOINT` and spans ship over OTLP/HTTP, with
   FastAPI and SQLAlchemy both instrumented. What a local demo lacks is
   somewhere to send them, not the pipeline to do it.
4. **One corridor.** NGN → KES only, which is the v1.0 scope in SRS §1.1.

---

## Documentation

| | Deployed | Local |
|---|---|---|
| **App** | https://cowrie-web-production.up.railway.app | http://localhost:3000 |
| **Interactive API** | https://cowrie-api-production.up.railway.app/docs | http://localhost:8000/docs |
| **OpenAPI 3.0** | https://cowrie-api-production.up.railway.app/openapi.json | http://localhost:8000/openapi.json |
| **Requirements map** | `GET /requirements` | `GET /requirements` |
| **Public disclosure** | `GET /transparency` | `GET /transparency` |
| **UML analysis models** | [`docs/uml/`](docs/uml/) | |

---

## Licence

MIT. Built by **Wisdom Okechukwu** at African Leadership University.
