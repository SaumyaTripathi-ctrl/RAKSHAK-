// Package anchor holds the ledger logic of the Rakshak chaincode, independent of Fabric's shim so it
// can be unit-tested with an in-memory state.
//
// The chaincode is append-only: there is no update or delete function. Each entry is also hash-linked
// to the previous one, so even a compromised peer admin cannot silently rewrite history.
package anchor

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
	"strconv"
)

const (
	KindBatch    = "BATCH"
	KindHandover = "HANDOVER"
	genesisPrev  = "0000000000000000000000000000000000000000000000000000000000000000"
)

var hex64 = regexp.MustCompile(`^[0-9a-f]{64}$`)

// State is the subset of the Fabric stub the logic needs.
type State interface {
	Get(key string) ([]byte, error)
	Put(key string, value []byte) error
}

// Entry is one anchored record.
type Entry struct {
	Index    int             `json:"index"`
	TxID     string          `json:"txId"`
	Kind     string          `json:"kind"`
	Payload  json.RawMessage `json:"payload"`
	TS       int64           `json:"ts"`
	PrevHash string          `json:"prevHash"`
	Hash     string          `json:"hash"`
}

// Ledger is the anchoring logic over a State.
type Ledger struct{ S State }

func entryKey(i int) string { return fmt.Sprintf("entry:%012d", i) }

func (l Ledger) count() (int, error) {
	b, err := l.S.Get("meta:count")
	if err != nil || b == nil {
		return 0, err
	}
	return strconv.Atoi(string(b))
}

func hashEntry(index int, ts int64, kind string, payload []byte, prev string) string {
	sum := sha256.Sum256([]byte(fmt.Sprintf("%d|%d|%s|%s|%s", index, ts, kind, payload, prev)))
	return hex.EncodeToString(sum[:])
}

func compact(raw []byte) ([]byte, error) {
	var out json.RawMessage
	if err := json.Unmarshal(raw, &out); err != nil {
		return nil, errors.New("payload is not valid JSON")
	}
	return json.Marshal(out) // Marshal of a RawMessage compacts it
}

func str(m map[string]any, k string) (string, bool) {
	v, ok := m[k].(string)
	return v, ok && v != ""
}

// validate enforces the payload shape per kind (mirrors backend/rakshak/ledger/client.py).
func validate(kind string, payload []byte) (string, error) {
	var m map[string]any
	if err := json.Unmarshal(payload, &m); err != nil {
		return "", errors.New("payload must be a JSON object")
	}
	switch kind {
	case KindBatch:
		ship, ok1 := str(m, "shipment_id")
		dev, ok2 := str(m, "device_id")
		root, ok3 := str(m, "merkle_root")
		id, ok4 := m["batch_id"].(float64)
		if !ok1 || !ok2 || !ok3 || !ok4 || !hex64.MatchString(root) {
			return "", errors.New("BATCH needs shipment_id, device_id, batch_id and a 64-hex merkle_root")
		}
		first, _ := m["first_seq"].(float64)
		last, _ := m["last_seq"].(float64)
		if first > last {
			return "", errors.New("first_seq must be <= last_seq")
		}
		return fmt.Sprintf("batch:%s:%s:%d", ship, dev, int(id)), nil
	case KindHandover:
		ship, ok1 := str(m, "shipment_id")
		hh, ok2 := str(m, "handover_hash")
		br, ok3 := str(m, "batches_root")
		if !ok1 || !ok2 || !ok3 || !hex64.MatchString(hh) || !hex64.MatchString(br) {
			return "", errors.New("HANDOVER needs shipment_id, handover_hash and batches_root (64-hex)")
		}
		return fmt.Sprintf("handover:%s:%s", ship, hh), nil
	}
	return "", fmt.Errorf("unknown entry kind %q", kind)
}

// Submit appends an entry. ts must come from the transaction (not time.Now) to stay deterministic.
func (l Ledger) Submit(txID string, ts int64, kind string, payload []byte) (*Entry, error) {
	compacted, err := compact(payload)
	if err != nil {
		return nil, err
	}
	dedup, err := validate(kind, compacted)
	if err != nil {
		return nil, err
	}
	if existing, _ := l.S.Get(dedup); existing != nil {
		return nil, fmt.Errorf("already anchored: %s", dedup)
	}
	n, err := l.count()
	if err != nil {
		return nil, err
	}
	prev := genesisPrev
	if n > 0 {
		last, err := l.getIndex(n - 1)
		if err != nil {
			return nil, err
		}
		prev = last.Hash
	}
	e := Entry{Index: n, TxID: txID, Kind: kind, Payload: compacted, TS: ts, PrevHash: prev,
		Hash: hashEntry(n, ts, kind, compacted, prev)}
	raw, _ := json.Marshal(e)
	writes := []struct {
		k string
		v []byte
	}{
		{entryKey(n), raw},
		{"tx:" + txID, []byte(strconv.Itoa(n))},
		{dedup, []byte(txID)},
		{"meta:count", []byte(strconv.Itoa(n + 1))},
	}
	for _, w := range writes {
		if err := l.S.Put(w.k, w.v); err != nil {
			return nil, err
		}
	}
	return &e, nil
}

func (l Ledger) getIndex(i int) (*Entry, error) {
	raw, err := l.S.Get(entryKey(i))
	if err != nil {
		return nil, err
	}
	if raw == nil {
		return nil, fmt.Errorf("entry %d missing", i)
	}
	var e Entry
	if err := json.Unmarshal(raw, &e); err != nil {
		return nil, err
	}
	return &e, nil
}

// GetByTx returns nil, nil when the transaction is unknown.
func (l Ledger) GetByTx(txID string) (*Entry, error) {
	b, err := l.S.Get("tx:" + txID)
	if err != nil || b == nil {
		return nil, err
	}
	i, err := strconv.Atoi(string(b))
	if err != nil {
		return nil, err
	}
	return l.getIndex(i)
}

// List returns entries newest first.
func (l Ledger) List(limit, offset int) ([]Entry, error) {
	n, err := l.count()
	if err != nil {
		return nil, err
	}
	out := []Entry{}
	for i := n - 1 - offset; i >= 0 && len(out) < limit; i-- {
		e, err := l.getIndex(i)
		if err != nil {
			return nil, err
		}
		out = append(out, *e)
	}
	return out, nil
}

// Verify re-walks the hash chain.
func (l Ledger) Verify() (ok bool, entries int, problem string) {
	n, err := l.count()
	if err != nil {
		return false, 0, err.Error()
	}
	prev := genesisPrev
	for i := 0; i < n; i++ {
		e, err := l.getIndex(i)
		if err != nil {
			return false, n, err.Error()
		}
		if e.PrevHash != prev || e.Hash != hashEntry(e.Index, e.TS, e.Kind, e.Payload, e.PrevHash) {
			return false, n, fmt.Sprintf("entry %d: chain broken", i)
		}
		prev = e.Hash
	}
	return true, n, ""
}
