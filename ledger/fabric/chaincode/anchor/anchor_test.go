package anchor

import (
	"fmt"
	"strings"
	"testing"
)

type mem map[string][]byte

func (m mem) Get(k string) ([]byte, error) { return m[k], nil }
func (m mem) Put(k string, v []byte) error { m[k] = v; return nil }

const root = "aabbccddeeff00112233445566778899aabbccddeeff00112233445566778899"

func batch(id int, rootHex string) []byte {
	return []byte(fmt.Sprintf(`{"shipment_id":"RKS-26-000001","device_id":"TAG-0001","batch_id":%d,`+
		`"first_seq":0,"last_seq":4,"leaf_count":5,"merkle_root":"%s"}`, id, rootHex))
}

func TestSubmitGetListVerify(t *testing.T) {
	l := Ledger{mem{}}
	e1, err := l.Submit("tx1", 100, KindBatch, batch(1, root))
	if err != nil || e1.Index != 0 || e1.PrevHash != genesisPrev {
		t.Fatalf("first entry: %+v %v", e1, err)
	}
	e2, err := l.Submit("tx2", 101, KindBatch, batch(2, root))
	if err != nil || e2.PrevHash != e1.Hash {
		t.Fatalf("second entry must link to first: %+v %v", e2, err)
	}
	got, _ := l.GetByTx("tx2")
	if got == nil || got.Index != 1 {
		t.Fatalf("GetByTx: %+v", got)
	}
	if nope, _ := l.GetByTx("missing"); nope != nil {
		t.Fatal("unknown tx must be nil")
	}
	list, _ := l.List(10, 0)
	if len(list) != 2 || list[0].TxID != "tx2" {
		t.Fatalf("list newest first: %+v", list)
	}
	if ok, n, p := l.Verify(); !ok || n != 2 {
		t.Fatalf("verify: %v %d %s", ok, n, p)
	}
}

func TestAppendOnlyAndDedup(t *testing.T) {
	l := Ledger{mem{}}
	if _, err := l.Submit("tx1", 1, KindBatch, batch(1, root)); err != nil {
		t.Fatal(err)
	}
	if _, err := l.Submit("tx2", 2, KindBatch, batch(1, root)); err == nil ||
		!strings.Contains(err.Error(), "already anchored") {
		t.Fatalf("re-anchoring the same batch must fail, got %v", err)
	}
}

func TestValidation(t *testing.T) {
	l := Ledger{mem{}}
	if _, err := l.Submit("t", 1, KindBatch, []byte(`nope`)); err == nil {
		t.Error("non-JSON accepted")
	}
	if _, err := l.Submit("t", 1, KindBatch, batch(1, "abc")); err == nil {
		t.Error("short merkle root accepted")
	}
	if _, err := l.Submit("t", 1, "WHATEVER", []byte(`{}`)); err == nil {
		t.Error("unknown kind accepted")
	}
	if _, err := l.Submit("t", 1, KindHandover, []byte(`{"shipment_id":"x"}`)); err == nil {
		t.Error("incomplete HANDOVER accepted")
	}
	ho := fmt.Sprintf(`{"shipment_id":"S","handover_hash":"%s","batches_root":"%s"}`, root, root)
	if _, err := l.Submit("t", 1, KindHandover, []byte(ho)); err != nil {
		t.Errorf("valid HANDOVER rejected: %v", err)
	}
}

func TestVerifyDetectsTampering(t *testing.T) {
	m := mem{}
	l := Ledger{m}
	for i, id := range []string{"tx1", "tx2", "tx3"} {
		if _, err := l.Submit(id, int64(i), KindBatch, batch(i+1, root)); err != nil {
			t.Fatal(err)
		}
	}
	key := entryKey(1)
	orig := m[key]
	m[key] = []byte(strings.Replace(string(orig), `"leaf_count":5`, `"leaf_count":1`, 1))
	if ok, _, p := l.Verify(); ok || !strings.Contains(p, "entry 1") {
		t.Fatalf("edit must be detected, got ok=%v %q", ok, p)
	}
	m[key] = orig
	if ok, _, _ := l.Verify(); !ok {
		t.Fatal("restored ledger must verify")
	}
}
