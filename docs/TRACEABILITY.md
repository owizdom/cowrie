# Cowrie — Requirements Traceability Matrix

Every requirement in the SRS and every element of the five UML diagrams, mapped
to the code that implements it. This file is the checklist the build is held to.

Legend for **Status**: ✅ implemented · 🟡 implemented with a stated limitation ·
❌ not implemented (with the reason)

---

## 1. Functional Requirements (SRS §4)

| Req | Requirement | Where it lives | Status |
|---|---|---|---|
| **FR 1** | **User Onboarding & KYC** | | |
| FR 1.1 | Sign up with phone + email, **verified by a one-time code before the account is created** | `routers/auth.py` → `request_otp` / `verify_otp` / `register`; OTP in `services/otp.py` | ✅ |
| FR 1.2 | Government ID (NIN, BVN, Kenyan ID, NIDA, Ghana Card) + selfie via Smile ID; **limits scale with level** | `services/kyc_service.py`, `adapters/smileid.py`, `User.raiseLimit`, `config.tier_limits_usd` | ✅ |
| FR 1.3 | Screen against OFAC, UN, EU **at signup and refresh daily** | `services/sanctions.py` → `screen_user` (signup + transfer), `daily_refresh` (worker) | ✅ |
| **FR 2** | **Send Money (CowriePay)** | | |
| FR 2.1 | Live rate, all fees, exact recipient amount on one screen; **quote locked 60s** | `services/quote_engine.py`, `Quote.expiresAt`, `/pay/send` confirm screen | ✅ |
| FR 2.2 | Debit sender's NGN bank account via Mono; **6-digit PIN**, **second factor for large transfers** | `adapters/mono.py`, `transfer_service.authorize`, `services/otp.py` step-up | ✅ |
| FR 2.3 | Deposit KES to recipient M-Pesa via Daraja; **match M-Pesa ID to on-chain record** | `adapters/daraja.py`; `Transaction.mpesaReceipt` + `OnchainRecord.txHash` on one row | ✅ |
| FR 2.4 | "Cancel and refund" after 5 min pending; **auto-refund after 10 min** | `Transaction.isStuck()`, `transfer_service.cancel_and_refund`, `sweep_stuck` | ✅ |
| **FR 3** | **Settlement Layer & cUSDC** | | |
| FR 3.1 | Single on-chain tx converting cNGN → cUSDC, **emits a confirmation event** | `cusdc/src/CowrieBridge.sol` → `executeBridge` emits `BridgeSettled`; `adapters/chain.py` | ✅ |
| FR 3.2 | Mint only after banking partner confirms matching USD; burn on redemption; **reject unbacked mint** | `services/reserve_service.mint` (refusal path + audit), `adapters/banking_partner.py`, `cusdc/src/CUSDC.sol` `mintWithAttestation` | ✅ |
| FR 3.3 | Wait ≥ 12 confirmations (~24s); refund within 10 min on rollback | `config.required_confirmations`, `OnchainRecord.isFinal()`, `transfer_service` confirmation loop | ✅ |
| **FR 4** | **Cowrie API (Institutional)** | | |
| FR 4.1 | API key pairs, authenticated over TLS, **unique ID per write to prevent duplicates** | `security.generate_api_key`, `routers/partner.py` `Idempotency-Key`, `PaymentIntent.idempotencyKey` unique | ✅ |
| FR 4.2 | Create payment: source ccy, destination ccy, amount, recipient, partner reference | `routers/partner.py` → `POST /v1/payment_intents` | ✅ |
| FR 4.3 | Signed webhooks — **payment settled, payment failed, payout completed, KYC completed** — retry up to 24h | `services/webhooks.py` (HMAC-SHA256, exponential retry to 24h), all four events emitted | ✅ |
| **FR 5** | **Admin & Compliance Console** | | |
| FR 5.1 | Live transaction feed; flag suspicious via **rule-based and velocity-based** checks | `services/monitoring.py` (both families), `/admin` live feed over WebSocket | ✅ |
| FR 5.2 | KYC + dispute review queues; **approve, reject, freeze, escalate**; every action permanently logged | `services/kyc_service.decide`, `routers/admin.py` disputes, `services/audit.py` | ✅ |
| FR 5.3 | **Signed** transaction reports for Nigeria SEC and Kenya CMA; live supply, reserve, coverage | `routers/regulator.py` export (signed + hashed), `reserve_service.dashboard` | 🟡 signed with an HMAC, not an HSM — see NFR 2 |

## 2. Non-Functional Requirements (SRS §5)

| Req | Requirement | Where it lives | Status |
|---|---|---|---|
| NFR 1 | Transfer < 30s typical, < 60s worst case; API reads < 500ms, writes < 2s | Real timings (2s blocks × 12 = 24s); measured in `monitoring.feed_summary` and `middleware/timing.py`, surfaced on `/admin` | ✅ measured, not asserted |
| NFR 2 | Signing keys in tamper-resistant hardware; TLS in transit; encryption at rest; **≥ 3-of-5 multisig** for treasury | `security.sign_with_platform_key` (single HSM swap point), `cusdc/src/CowrieTreasury.sol` 3-of-5, `reserve_service` approval gate | 🟡 multisig real; **no HSM** — the one function that would move is isolated and labelled |
| NFR 3 | No transfer left in the system; completes or auto-refunds within 10 min | `enums.ALLOWED_TRANSITIONS` (every non-terminal state has a refund arrow), `sweep_stuck` timer independent of the driver | ✅ |
| NFR 4 | Licences held; real-time quote; OFAC/UN/EU screening on all transactions | Screening ✅, real-time quote ✅. **Licences are a legal fact, not code** — the transparency page states the true regulatory position rather than claiming licences | 🟡 stated honestly |
| NFR 5 | Every balance-changing action in a permanent tamper-evident log, **anchored on-chain** | `services/audit.py` hash chain + `verify_chain()` + `anchor_pending()`; `/admin/audit` verify button | ✅ |
| NFR 6 | 3 taps / 4 steps to send; **every fee on its own line, never bundled** | `/pay` send flow is 4 steps; `FeeBreakdown` carries 4 components end-to-end, no endpoint returns a single "fee" | ✅ |
| NFR 7 | WCAG 2.1 AA; Android 8+/iOS 14+; current Chrome and Safari | Semantic HTML, labelled controls, visible focus, AA contrast, keyboard-operable PIN pad; PWA targets Android 8+/iOS 14+ | ✅ |

## 3. Product Functions (SRS §2.2) — the nine major functions

| # | Function | Where it lives | Status |
|---|---|---|---|
| 1a | CowriePay: register, KYC, **link bank/mobile-money account**, quote, send/receive, check status, cancel stuck, **history**, **export statement**, **support ticket** | `routers/users.py`, `routers/transfers.py`, `routers/support.py`; `/pay` screens | ✅ all ten |
| 1b | Cowrie API: authenticate by key, create payment intents, **analyse transaction statistics** | `routers/partner.py` → `/v1/stats` | ✅ |
| 1c | cUSDC: mint on attested reserves, burn on redemption, **reconcile on-chain supply vs off-chain reserves**, transparency endpoint | `reserve_service.mint/burn/reconcile`, `routers/transparency.py` | ✅ |
| 2a | Quote engine — real-time corridor rates | `services/quote_engine.py` | ✅ |
| 2b | Neutral bridge — local currency → cUSDC → target within a single Base block | `cusdc/src/CowrieBridge.sol` (one atomic call), `adapters/chain.py` | ✅ |
| 2c | On-/off-ramp integration — bank and mobile-money wallets | `adapters/mono.py`, `adapters/daraja.py` | 🟡 simulated per SRS §2.5 |
| 2d | KYC screening via Smile ID | `adapters/smileid.py` | 🟡 simulated per SRS §2.5 |
| 2e | Notifications | `services/notifications.py` (WebSocket push) | ✅ |
| 3a | Admin console: KYC queue, real-time tracking, reserve dashboard, regulatory reporting | `/admin` + `routers/admin.py` | ✅ |

## 4. External Interfaces (SRS §3)

| Item | Requirement | Where it lives | Status |
|---|---|---|---|
| §3.1 | **Six** user interfaces on one design system | `/`, `/pay`, `/admin`, `/developers`, `/transparency`, `/regulator` | ✅ |
| §3.1 | CowriePay Login — 6-digit PIN with a **randomised keypad** | `surfaces/app/pay/login` — digits reshuffled per render | ✅ |
| §3.1 | CowriePay Home — balance, recent transactions, **Send / Receive / Top-up** | `surfaces/app/pay/(home)` — all three actions | ✅ |
| §3.1 | CowriePay Send/Quote — beneficiary, amount, **itemised FX / Gas / Liquidity / Cowrie fee**, PIN | `surfaces/app/pay/send` | ✅ |
| §3.1 | Admin live transactions with **filter chips: status, corridor, size, risk score** | `/admin` — all four chip groups | ✅ |
| §3.1 | Admin KYC queue — **side-by-side documents + liveness, provider confidence score** | `/admin/kyc` | ✅ |
| §3.1 | Admin cUSDC reserve — live supply, attestation history, mint/burn | `/admin/reserve` | ✅ |
| §3.1 | Dev portal — OpenAPI 3.0, **"Try It" console**, **Python + TypeScript samples**, key management, **webhook signing + payload test**, **sandbox/production switch** | `/developers` (all six) | ✅ |
| §3.1 | Transparency — live supply, reserve breakdown, attestation report, **anchor proof**, contract address | `/transparency` | ✅ |
| §3.2 | **Rear camera** (ID document) and **front camera** (liveness selfie) | `/pay/verify` — `getUserMedia` with `facingMode` environment/user | ✅ |
| §3.3 | Ten external software components | `adapters/*` (5 simulated), OpenZeppelin v5 + Foundry (real), Postgres + Redis (real) | 🟡 partners simulated |
| §3.4 | REST + OpenAPI 3.0, JSON both ways, **WebSocket for transaction status**, JSON-RPC 2.0 to chain | FastAPI auto-OpenAPI, `routers/ws.py`, `adapters/chain.py` | ✅ |
| §3.4 | Rate limits — **API 100/s burst 200/s per key; CowriePay 1,000/min per session; unauthenticated 10/s** | `middleware/ratelimit.py` — all three tiers, sliding window | ✅ |

## 5. Other SRS commitments

| Item | Requirement | Where it lives | Status |
|---|---|---|---|
| §2.3 | Admin RBAC — Support (read), Reviewer (KYC), Officer (export + freeze), Engineer (deploy), Admin (grants) | `enums.AdminRole`, `routers/admin.py` `require_role` on every route | ✅ |
| §2.4 | Python 3.12+, PostgreSQL 15+, Redis 7+, Base | `pyproject.toml`, `docker-compose.yml` | ✅ |
| §2.4 | Observability — OpenTelemetry | Structured span logging via `middleware/timing.py`; **OTel exporter not wired** (no collector to send to in a local demo) | 🟡 |
| §2.4 | Foundry toolkit for local testing | `cusdc/` — `forge build`, `forge test` | ✅ |
| §2.6 | CowriePay **in-app help centre** | `/pay/help` | ✅ |
| §2.6 | API developer portal with the complete specification | `/developers` | ✅ |
| §2.6 | **Regulator integration guide** | `/regulator/guide` | ✅ |
| §1.4 | Audit log — append-only Postgres with on-chain hash anchors | `services/audit.py` | ✅ |

## 6. UML — Use Case Diagram (22 use cases, 9 actors)

| Use case | Actor(s) | Endpoint / screen | Status |
|---|---|---|---|
| Register account | Individual | `POST /auth/register` · `/pay/register` | ✅ |
| Verify identity (KYC) ← *include* | Individual, Smile ID | `POST /kyc/submit` · `/pay/verify` | ✅ |
| Screen against sanctions ← *include* | — | `services/sanctions.py` | ✅ |
| Request transparent quote ← *include* | Individual | `POST /quotes` · `/pay/send` | ✅ |
| Initiate & confirm transfer (6-digit PIN) | Individual, Mono | `POST /transfers` + `/confirm` | ✅ |
| Receive to M-Pesa ← *include* | Daraja | `adapters/daraja.py` · `/pay/receive` | ✅ |
| Cancel & refund stuck transfer ← *extend* | Individual | `POST /transfers/{id}/cancel` | ✅ |
| View history / export statement | Individual | `GET /transfers` · `GET /transfers/statement.csv` | ✅ |
| Create support ticket | Individual | `POST /support/tickets` · `/pay/support` | ✅ |
| Execute atomic bridge settlement ← *include* | Base Network | `CowrieBridge.executeBridge` | ✅ |
| Mint cUSDC (reserve-attested) | Admin, Banking Partner | `POST /admin/reserve/mint` | ✅ |
| Burn cUSDC (redemption) | Admin, Banking Partner | `POST /admin/reserve/burn` | ✅ |
| Publish reserve attestation ← *include of Mint* | Regulator, Admin | `POST /admin/reserve/attest` | ✅ |
| Authenticate via API key ← *include* | Institution | `X-API-Key` on `/v1/*` | ✅ |
| Create payment intent | Institution | `POST /v1/payment_intents` | ✅ |
| Receive signed webhooks | Institution | `services/webhooks.py` | ✅ |
| Analyze transaction stats | Institution | `GET /v1/stats` | ✅ |
| Monitor transactions | Admin | `GET /admin/transactions` · `/admin` | ✅ |
| Review KYC & resolve disputes | Admin | `POST /admin/kyc/{id}/decide`, `/admin/disputes/{id}` | ✅ |
| Export regulator report | Admin, Regulator | `POST /regulator/exports` | ✅ |
| View cUSDC reserve dashboard | Admin, Regulator | `GET /admin/reserve` · `/regulator` | ✅ |

All nine actors are represented: Individual, Institution/API Consumer, Cowrie Admin,
Regulator, Mono, Safaricom Daraja, Smile ID, cUSDC Banking Partner, Base Network.

## 7. UML — Class Diagram

All 12 classes exist in `orchestration/cowrie/models.py` with identical field
names, types and visibility: `AuditableEntity` (abstract), `User`,
`KycSubmission`, `Transaction`, `OnchainRecord`, `ApiKey`, `PaymentIntent`,
`CusdcReserve`, `Webhook`, `Money` «value object», `FeeBreakdown» «value object»,
`AuditLogEntry` «log». All 7 enumerations in `enums.py`. All 9 relationships
(3 composition, 2 aggregation, 1 association, 7 generalization, 1 dependency)
are expressed as SQLAlchemy relationships with matching cascade semantics.

All 21 diagram operations are implemented, not stubbed — including
`FeeBreakdown.total()`, `Transaction.isStuck()`, `OnchainRecord.isFinal()`,
`CusdcReserve.coverageRatio()`/`isFullyBacked()`, and `AuditLogEntry.verifyChain()`.

## 8. UML — Sequence Diagram

All 24 numbered messages are executed in order by
`services/transfer_service.py`, with the step numbers in the code comments. The
`alt` frame is the branch at the end of `_drive_inner`: finality within SLA →
Daraja payout → SETTLED → receipt; otherwise → refund → REFUNDED → notice.

## 9. UML — State Machine Diagram

All 11 states and all 15 transitions are encoded in
`enums.ALLOWED_TRANSITIONS`, and `transfer_service.transition()` raises on any
move not on the diagram. Every arrow is reachable in the demo through the
scenario switch (`enums.DemoScenario`).

## 10. UML — Deployment Diagram

| Node | Realised as |
|---|---|
| Sender device (CowriePay PWA) | `surfaces/` installable PWA |
| Admin / Regulator workstation | `/admin`, `/regulator` |
| Railway — Python 3.12 containers | `orchestration/`, `render.yaml` |
| PostgreSQL 15 (state + audit log) | `docker-compose.yml` |
| Redis 7 (cache / rate limit / queue) | `docker-compose.yml`, `middleware/ratelimit.py` |
| HSM | **Not present** — `security.sign_with_platform_key` is the seam |
| Base L2 — cUSDC, cNGN, Bridge, 3-of-5 Safe | `cusdc/` contracts, local Anvil |
| Alchemy / Infura | Not used — local chain only, by design |
| Mono, Daraja, Smile ID, Banking Partner | `adapters/` (simulated) |

---

## Deliberate gaps

These are not oversights. Each is a thing the SRS asks for that a local,
demo-data build cannot honestly claim.

1. **No HSM.** NFR 2 wants signing keys in tamper-resistant hardware. Every
   signature goes through one function, `security.sign_with_platform_key`, which
   says so. Exports produced by it are labelled demo-signed.
2. **Partners are simulated.** Mono, Daraja, Smile ID and the banking partner
   have no live credentials. SRS §2.5 constraint 2 authorises exactly this. Each
   adapter keeps the real request/response shape and names what it drops.
3. **Contracts are not on Base.** They compile, they pass their Foundry tests,
   and they run on a local Anvil node. They are not deployed to Base mainnet or
   Sepolia, and the addresses in SRS §2.4 are carried as labels.
4. **No VASP licences.** NFR 4 asserts active SEC/CMA licences. That is a legal
   status, not a feature; the transparency page states the real position.
5. **OpenTelemetry is not exported.** Timing spans are produced and logged, but
   there is no collector in a local demo to receive them.
