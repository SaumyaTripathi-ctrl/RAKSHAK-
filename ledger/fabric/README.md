# Hyperledger Fabric backend (experimental)

**Status: EXPERIMENTAL.** `chaincode/anchor` (the ledger logic) has Go unit tests and `bridge/` has Node tests
with a mocked gateway; both run in CI. They have **not** been run against a live Fabric network in this
repository — Fabric needs ~2 GB of container images and a Linux/WSL2 shell, which is too heavy for a laptop demo.
The default backend is the local hash-linked ledger.

```
Rakshak API ──HTTP──► bridge (Node, fabric-gateway) ──gRPC──► Fabric peer ──► chaincode "rakshak" (Go)
   FabricLedger           POST /entries  GET /entries/:tx  GET /entries  GET /health
```

## Chaincode (`chaincode/`)

Append-only: no update/delete function. `Submit(kind, payload)` validates the payload, refuses to anchor the
same batch / hand-over twice, hash-links entries, and returns the transaction id. `GetEntry`, `ListEntries` and
`Health` (re-walks the chain) are read-only.

```bash
# unit tests without installing Go (uses the golang image)
docker run --rm -v "$PWD/ledger/fabric/chaincode:/src" -w /src golang:1.22 go test ./...
```

Dependency note: `fabric-contract-api-go` **v1.2.2** is pinned on purpose; v2 currently requires a Go toolchain
newer than Fabric's chaincode build images provide (see `docs/DECISIONS.md`).

## Running it with fabric-samples' test-network (from the Fabric docs — untested here)

```bash
# 1. inside WSL2/Linux, get fabric-samples + binaries/images (see hyperledger-fabric.readthedocs.io, "Install")
cd fabric-samples/test-network
./network.sh up createChannel -c mychannel -ca
./network.sh deployCC -ccn rakshak -ccp /path/to/rakshak-app/ledger/fabric/chaincode -ccl go

# 2. start the bridge (paths default to test-network Org1; override via FABRIC_* env vars)
cd /path/to/rakshak-app/ledger/fabric/bridge && npm install
FABRIC_CRYPTO_PATH=$HOME/fabric-samples/test-network/organizations/peerOrganizations/org1.example.com npm start

# 3. point the backend at it
RAKSHAK_LEDGER_BACKEND=fabric RAKSHAK_FABRIC_BRIDGE_URL=http://localhost:8090
```

Set `BRIDGE_TOKEN` to require `Authorization: Bearer <token>` on the bridge (the Python client does not send one
yet — keep the bridge on localhost / a private network).

## What multi-party adds

With peers operated by the FPO, the transporter, the exporter and the buyer, and an endorsement policy requiring
more than one of them, no single party can rewrite an anchored root. That is the property the local ledger
cannot provide.
