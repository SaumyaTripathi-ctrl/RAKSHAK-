// Rakshak anchoring chaincode: stores Merkle roots of record batches and custody hand-overs.
// EXPERIMENTAL: the logic is unit-tested (./anchor); it has not been run against a live Fabric network in CI.
package main

import (
	"encoding/json"
	"log"

	"github.com/hyperledger/fabric-contract-api-go/contractapi"

	"rakshak/chaincode/anchor"
)

type stubState struct {
	ctx contractapi.TransactionContextInterface
}

func (s stubState) Get(k string) ([]byte, error) { return s.ctx.GetStub().GetState(k) }
func (s stubState) Put(k string, v []byte) error { return s.ctx.GetStub().PutState(k, v) }

// Contract is the chaincode entry point.
type Contract struct{ contractapi.Contract }

// Submit appends an entry and returns its transaction id.
func (c *Contract) Submit(ctx contractapi.TransactionContextInterface, kind string, payload string) (string, error) {
	ts, err := ctx.GetStub().GetTxTimestamp()
	if err != nil {
		return "", err
	}
	e, err := anchor.Ledger{S: stubState{ctx}}.Submit(ctx.GetStub().GetTxID(), ts.Seconds, kind, []byte(payload))
	if err != nil {
		return "", err
	}
	return e.TxID, nil
}

// GetEntry returns the entry for a transaction id as JSON ("" when unknown).
func (c *Contract) GetEntry(ctx contractapi.TransactionContextInterface, txID string) (string, error) {
	e, err := anchor.Ledger{S: stubState{ctx}}.GetByTx(txID)
	if err != nil || e == nil {
		return "", err
	}
	b, _ := json.Marshal(e)
	return string(b), nil
}

// ListEntries returns entries newest first as a JSON array.
func (c *Contract) ListEntries(ctx contractapi.TransactionContextInterface, limit int, offset int) (string, error) {
	es, err := anchor.Ledger{S: stubState{ctx}}.List(limit, offset)
	if err != nil {
		return "", err
	}
	b, _ := json.Marshal(es)
	return string(b), nil
}

// Health re-walks the hash chain: {"ok":bool,"entries":n,"problem":""}.
func (c *Contract) Health(ctx contractapi.TransactionContextInterface) (string, error) {
	ok, n, p := anchor.Ledger{S: stubState{ctx}}.Verify()
	b, _ := json.Marshal(map[string]any{"ok": ok, "entries": n, "problem": p})
	return string(b), nil
}

func main() {
	cc, err := contractapi.NewChaincode(&Contract{})
	if err != nil {
		log.Panicf("create chaincode: %v", err)
	}
	if err := cc.Start(); err != nil {
		log.Panicf("start chaincode: %v", err)
	}
}
