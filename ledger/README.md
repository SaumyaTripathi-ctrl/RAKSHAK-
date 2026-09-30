# Ledger

Rakshak keeps the full data in the database and writes only **one Merkle root per batch** (and one entry per
custody hand-over) to a ledger. Any later change to any record — even one the attacker re-hashes — no longer
matches the anchored root.

```
records ──► batch (50, contiguous seq) ──► Merkle root ──► LedgerClient.submit("BATCH", …)
hand-over (signed) + root of all batch roots ───────────► LedgerClient.submit("HANDOVER", …)
GET /api/verify/{shipment_id}  recomputes everything from the DB and compares with the ledger
```

| Backend | Where | Default | Properties |
|---|---|---|---|
| **local** | `backend/rakshak/ledger/client.py` (`LocalLedger`) | yes | append-only hash-linked JSONL file; tamper-evident; works offline. **Single party** — whoever controls the file can rewrite it wholesale. Labelled as such in `/verify`, the QR page and the UI. |
| **fabric** | `ledger/fabric/` | no (`RAKSHAK_LEDGER_BACKEND=fabric`) | Hyperledger Fabric chaincode (Go) + HTTP bridge (Node, `@hyperledger/fabric-gateway`). Multi-party (farmer/FPO, transporter, exporter, buyer peers). **Experimental**: chaincode logic and the bridge are unit-tested; neither has been run against a live network here. |

Code lives in `backend/rakshak/ledger/` (Python: `merkle.py`, `client.py`, `anchor.py`, `verify.py`) so the
backend imports it directly; this folder holds the Fabric artefacts and docs.

## What `/verify` catches (all covered by `backend/tests/test_anchor_verify.py`)

| Attack on the database | Detected as |
|---|---|
| record body edited | stored hash ≠ SHA-256(prev ‖ body) |
| only a displayed value edited (`temp_c` …) | displayed value ≠ value decoded from the signed body |
| record deleted | missing seq + Merkle root mismatch |
| body **and** hash rewritten | next record's chain link broken + Merkle root mismatch |
| whole chain re-hashed **and** batch row rewritten | DB root ≠ root on the ledger |
| hand-over edited / removed | hash, link or Ed25519 signature failure |
| ledger file edited (local backend) | ledger hash-chain integrity failure |

## Honest limits

* The local ledger does not stop a party who controls *both* the database and the ledger file. Use Fabric with
  independently operated peers for that (and see `docs/LIMITATIONS.md`).
* Anchoring proves the data was not changed *after* anchoring; it cannot prove the sensor told the truth.
* Records still unanchored (fewer than a batch) are checked locally but are not yet covered by the ledger; the API
  reports this as `PARTIAL` with a coverage ratio.

See `fabric/README.md` to run the Fabric variant.
