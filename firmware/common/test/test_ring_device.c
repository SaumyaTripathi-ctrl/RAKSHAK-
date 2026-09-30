/* Ring buffer + device identity: persistence, crash safety, refusal to encrypt without durable seq. */
#include <stdlib.h>

#include "rk_codec.h"
#include "rk_device.h"
#include "rk_ring.h"
#include "rk_test.h"
#include "vectors.h"

/* ---- RAM block device with fault injection ------------------------------------------------------------ */
typedef struct {
    uint8_t slots[16][RK_SLOT_SIZE];
    int fail_writes;
} ramdev_t;

static int ram_read(void *c, uint32_t s, uint8_t *b) { memcpy(b, ((ramdev_t *)c)->slots[s], RK_SLOT_SIZE); return 0; }
static int ram_write(void *c, uint32_t s, const uint8_t *b) {
    ramdev_t *d = c;
    if (d->fail_writes) return -1;
    memcpy(d->slots[s], b, RK_SLOT_SIZE);
    return 0;
}

static rk_blockdev_t mk(ramdev_t *d, uint32_t n) { rk_blockdev_t b = {d, n, ram_read, ram_write}; return b; }

/* a syntactically valid frame with a given seq (contents do not matter to the ring) */
static size_t fake_frame(uint8_t *f, uint32_t seq, uint8_t type) {
    memset(f, 0xAB, RK_MAX_FRAME_LEN);
    f[0] = RK_VERSION;
    f[1] = type;
    f[20] = (uint8_t)seq; f[21] = (uint8_t)(seq >> 8); f[22] = (uint8_t)(seq >> 16); f[23] = (uint8_t)(seq >> 24);
    return rk_frame_len(type);
}

static uint32_t peek_seq(rk_ring_t *r, uint32_t i) {
    uint8_t f[RK_MAX_FRAME_LEN];
    size_t n;
    if (rk_ring_peek(r, i, f, sizeof f, &n) != RK_OK) return 0xFFFFFFFFu;
    return (uint32_t)f[20] | ((uint32_t)f[21] << 8);
}

static void test_crc(void) {
    CHECK_EQ(rk_crc16((const uint8_t *)"123456789", 9), 0x29B1); /* CRC-16/CCITT-FALSE check value */
}

static void test_ring_push_peek_ack(void) {
    static ramdev_t d;
    memset(&d, 0, sizeof d);
    rk_ring_t r;
    rk_blockdev_t b = mk(&d, 8);
    CHECK_EQ(rk_ring_init(&r, &b), RK_OK);
    CHECK_EQ(r.count, 0);
    uint8_t f[RK_MAX_FRAME_LEN];
    for (uint32_t s = 0; s < 5; s++) CHECK_EQ(rk_ring_push(&r, f, fake_frame(f, s, RK_TYPE_TAG_SAMPLE)), RK_OK);
    CHECK_EQ(r.count, 5);
    CHECK_EQ(peek_seq(&r, 0), 0);
    CHECK_EQ(peek_seq(&r, 4), 4);
    CHECK_EQ(rk_ring_ack(&r, 0, 2), 3); /* delete-after-ACK */
    CHECK_EQ(r.count, 2);
    CHECK_EQ(peek_seq(&r, 0), 3);
    CHECK_EQ(rk_ring_ack(&r, 10, 20), 0); /* an ACK for something we do not hold removes nothing */
    CHECK_EQ(r.count, 2);
    CHECK_EQ(rk_ring_ack(&r, 4, 3), RK_ERR_ARG);
}

static void test_ack_only_deletes_a_contiguous_prefix(void) {
    static ramdev_t d;
    memset(&d, 0, sizeof d);
    rk_ring_t r;
    rk_blockdev_t b = mk(&d, 8);
    rk_ring_init(&r, &b);
    uint8_t f[RK_MAX_FRAME_LEN];
    for (uint32_t s = 0; s < 4; s++) rk_ring_push(&r, f, fake_frame(f, s, RK_TYPE_TAG_SAMPLE));
    CHECK_EQ(rk_ring_ack(&r, 2, 3), 0); /* ACK for 2..3 while 0..1 are still held: nothing is lost */
    CHECK_EQ(r.count, 4);
}

static void test_overwrite_oldest_and_count_drops(void) {
    static ramdev_t d;
    memset(&d, 0, sizeof d);
    rk_ring_t r;
    rk_blockdev_t b = mk(&d, 4);
    rk_ring_init(&r, &b);
    uint8_t f[RK_MAX_FRAME_LEN];
    for (uint32_t s = 0; s < 7; s++) CHECK_EQ(rk_ring_push(&r, f, fake_frame(f, s, RK_TYPE_TAG_SAMPLE)), RK_OK);
    CHECK_EQ(r.count, 4);
    CHECK_EQ(r.dropped, 3); /* the loss is counted, never silent */
    CHECK_EQ(peek_seq(&r, 0), 3);
    CHECK_EQ(peek_seq(&r, 3), 6);
}

static void test_recovery_after_reboot_and_wraparound(void) {
    static ramdev_t d;
    memset(&d, 0, sizeof d);
    rk_ring_t r;
    rk_blockdev_t b = mk(&d, 5);
    rk_ring_init(&r, &b);
    uint8_t f[RK_MAX_FRAME_LEN];
    for (uint32_t s = 0; s < 8; s++) rk_ring_push(&r, f, fake_frame(f, s, s % 2 ? RK_TYPE_HUB_SAMPLE : RK_TYPE_TAG_SAMPLE));
    rk_ring_ack(&r, 3, 4); /* 3,4 acknowledged; 5,6,7 remain */
    rk_ring_t r2; /* "reboot": state comes only from the device */
    CHECK_EQ(rk_ring_init(&r2, &b), RK_OK);
    CHECK_EQ(r2.count, 3);
    CHECK_EQ(peek_seq(&r2, 0), 5);
    CHECK_EQ(peek_seq(&r2, 2), 7);
    CHECK_EQ(r2.next_seq_hint, 8);
    CHECK_EQ(rk_ring_push(&r2, f, fake_frame(f, 8, RK_TYPE_TAG_SAMPLE)), RK_OK); /* and it keeps going */
    CHECK_EQ(peek_seq(&r2, 3), 8);
}

static void test_torn_write_is_ignored(void) {
    static ramdev_t d;
    memset(&d, 0, sizeof d);
    rk_ring_t r;
    rk_blockdev_t b = mk(&d, 8);
    rk_ring_init(&r, &b);
    uint8_t f[RK_MAX_FRAME_LEN];
    for (uint32_t s = 0; s < 3; s++) rk_ring_push(&r, f, fake_frame(f, s, RK_TYPE_TAG_SAMPLE));
    d.slots[2][40] ^= 0xFF; /* power failed while writing the last slot */
    rk_ring_t r2;
    CHECK_EQ(rk_ring_init(&r2, &b), RK_OK);
    CHECK_EQ(r2.count, 2);
    CHECK_EQ(peek_seq(&r2, 1), 1);
}

static void test_storage_errors_are_reported(void) {
    static ramdev_t d;
    memset(&d, 0, sizeof d);
    rk_ring_t r;
    rk_blockdev_t b = mk(&d, 4);
    rk_ring_init(&r, &b);
    uint8_t f[RK_MAX_FRAME_LEN];
    size_t n = fake_frame(f, 0, RK_TYPE_TAG_SAMPLE);
    d.fail_writes = 1;
    CHECK(rk_ring_push(&r, f, n) != RK_OK);
    CHECK_EQ(r.count, 0);
    d.fail_writes = 0;
    CHECK(rk_ring_push(&r, f, 5) != RK_OK); /* shorter than a header */
    CHECK(rk_ring_push(&r, f, RK_MAX_FRAME_LEN + 1) != RK_OK);
}

/* ---- key-value store with fault injection ---------------------------------------------------------------- */
typedef struct {
    char keys[8][8];
    uint8_t vals[8][64];
    size_t lens[8];
    int n;
    int fail_put_key; /* fail puts of this key (-1 = none) */
    int fail_all_gets;
} ramkv_t;

static int find(ramkv_t *k, const char *key) {
    for (int i = 0; i < k->n; i++) if (!strcmp(k->keys[i], key)) return i;
    return -1;
}
static int kv_get(void *c, const char *key, uint8_t *buf, size_t len) {
    ramkv_t *k = c;
    int i = find(k, key);
    if (k->fail_all_gets || i < 0 || k->lens[i] != len) return -1;
    memcpy(buf, k->vals[i], len);
    return 0;
}
static int kv_put(void *c, const char *key, const uint8_t *buf, size_t len) {
    ramkv_t *k = c;
    if (k->fail_put_key >= 0 && !strcmp(key, "seq") && k->fail_put_key == 1) return -1;
    int i = find(k, key);
    if (i < 0) { i = k->n++; strcpy(k->keys[i], key); }
    memcpy(k->vals[i], buf, len);
    k->lens[i] = len;
    return 0;
}
static rk_kv_t mkkv(ramkv_t *k) { rk_kv_t kv = {k, kv_get, kv_put}; return kv; }

static int hexbyte(const char *s) { unsigned v; sscanf(s, "%2x", &v); return (int)v; }
static void unhex(const char *s, uint8_t *out, size_t n) { for (size_t i = 0; i < n; i++) out[i] = (uint8_t)hexbyte(s + 2 * i); }

static void test_device_reproduces_the_python_vector(void) {
    static ramkv_t kv;
    static ramdev_t dev;
    memset(&kv, 0, sizeof kv); memset(&dev, 0, sizeof dev);
    kv.fail_put_key = -1;
    uint8_t master[32], key[32];
    unhex(VEC_MASTER_KEY, master, 32);
    CHECK_EQ(rk_derive_device_key(master, "TAG-0001", 0, key), RK_OK);
    rk_kv_t k = mkkv(&kv);
    CHECK_EQ(rk_device_provision(&k, "TAG-0001", 0, key), RK_OK);
    rk_blockdev_t b = mk(&dev, 8);
    rk_ring_t ring;
    rk_ring_init(&ring, &b);
    rk_device_t d;
    CHECK_EQ(rk_device_load(&d, &k, &ring), RK_OK);

    const vec_record_t *v = &VEC_RECORDS[0]; /* tag_0_first_genesis */
    rk_tag_sample_t t = {{{0}, {0}, v->seq, v->ts}, (int16_t)v->f[0], (uint16_t)v->f[1], (uint16_t)v->f[2], (uint8_t)v->f[3], (uint8_t)v->f[4]};
    strcpy(t.c.device_id, v->device_id);
    strcpy(t.c.shipment_id, v->shipment_id);
    uint8_t body[RK_TAG_BODY_LEN], frame[RK_MAX_FRAME_LEN], want[RK_MAX_FRAME_LEN];
    size_t flen;
    CHECK_EQ(rk_pack_tag(&t, body), RK_OK);
    CHECK_EQ(rk_device_emit(&d, RK_TYPE_TAG_SAMPLE, body, sizeof body, frame, &flen), RK_OK);
    unhex(v->frame, want, flen);
    CHECK_EQ(flen, strlen(v->frame) / 2);
    CHECK(memcmp(frame, want, flen) == 0); /* device firmware flow == Python reference, byte for byte */
    CHECK_EQ(d.seq, 1);
    CHECK_EQ(ring.count, 1);
}

static void test_seq_is_persisted_before_use_and_survives_reboot(void) {
    static ramkv_t kv;
    static ramdev_t dev;
    memset(&kv, 0, sizeof kv); memset(&dev, 0, sizeof dev);
    kv.fail_put_key = -1;
    uint8_t key[32] = {7};
    rk_kv_t k = mkkv(&kv);
    rk_device_provision(&k, "TAG-0002", 3, key);
    rk_blockdev_t b = mk(&dev, 8);
    rk_ring_t ring;
    rk_ring_init(&ring, &b);
    rk_device_t d;
    CHECK_EQ(rk_device_load(&d, &k, &ring), RK_OK);
    CHECK_EQ(d.key_epoch, 3);
    uint8_t body[RK_EVENT_BODY_LEN] = {RK_VERSION, RK_TYPE_EVENT}, frame[RK_MAX_FRAME_LEN];
    memcpy(body + 2, "TAG-0002\0\0\0\0\0\0\0\0", 16);
    memcpy(body + 18, "RKS-1\0\0\0\0\0\0\0\0\0\0\0", 16);
    size_t fl;
    for (int i = 0; i < 3; i++) {
        body[34] = (uint8_t)i; /* seq inside the body must match the frame header's */
        CHECK_EQ(rk_device_emit(&d, RK_TYPE_EVENT, body, sizeof body, frame, &fl), RK_OK);
    }
    uint8_t prev_before[32];
    memcpy(prev_before, d.prev_hash, 32);
    rk_device_t d2; /* reboot */
    CHECK_EQ(rk_device_load(&d2, &k, &ring), RK_OK);
    CHECK_EQ(d2.seq, 3);
    CHECK(memcmp(d2.prev_hash, prev_before, 32) == 0); /* the chain continues */
}

static void test_refuses_to_encrypt_when_seq_cannot_be_persisted(void) {
    static ramkv_t kv;
    static ramdev_t dev;
    memset(&kv, 0, sizeof kv); memset(&dev, 0, sizeof dev);
    kv.fail_put_key = -1;
    uint8_t key[32] = {9};
    rk_kv_t k = mkkv(&kv);
    rk_device_provision(&k, "TAG-0003", 0, key);
    rk_blockdev_t b = mk(&dev, 8);
    rk_ring_t ring;
    rk_ring_init(&ring, &b);
    rk_device_t d;
    rk_device_load(&d, &k, &ring);
    uint8_t body[RK_TAG_BODY_LEN] = {RK_VERSION, RK_TYPE_TAG_SAMPLE}, frame[RK_MAX_FRAME_LEN];
    size_t fl = 0;
    kv.fail_put_key = 1; /* NVS write of "seq" fails */
    CHECK_EQ(rk_device_emit(&d, RK_TYPE_TAG_SAMPLE, body, sizeof body, frame, &fl), RK_ERR_STORAGE);
    CHECK_EQ(fl, 0);
    CHECK_EQ(ring.count, 0); /* nothing was encrypted or stored */
    CHECK_EQ(d.seq, 0);      /* and the nonce was not consumed */
}

static void test_refuses_to_start_when_persisted_state_is_unreadable(void) {
    static ramkv_t kv;
    memset(&kv, 0, sizeof kv);
    kv.fail_put_key = -1;
    uint8_t key[32] = {1};
    rk_kv_t k = mkkv(&kv);
    rk_device_t d;
    CHECK_EQ(rk_device_load(&d, &k, NULL), RK_ERR_STORAGE); /* not provisioned */
    rk_device_provision(&k, "TAG-0004", 0, key);
    CHECK_EQ(rk_device_load(&d, &k, NULL), RK_OK);
    kv.fail_all_gets = 1; /* NVS corrupted */
    CHECK_EQ(rk_device_load(&d, &k, NULL), RK_ERR_STORAGE);
}

static void test_reprovisioning_bumps_epoch_but_keeps_seq(void) {
    static ramkv_t kv;
    static ramdev_t dev;
    memset(&kv, 0, sizeof kv); memset(&dev, 0, sizeof dev);
    kv.fail_put_key = -1;
    uint8_t key0[32] = {1}, key1[32] = {2};
    rk_kv_t k = mkkv(&kv);
    rk_device_provision(&k, "TAG-0005", 0, key0);
    rk_blockdev_t b = mk(&dev, 8);
    rk_ring_t ring;
    rk_ring_init(&ring, &b);
    rk_device_t d;
    rk_device_load(&d, &k, &ring);
    uint8_t body[RK_TAG_BODY_LEN] = {RK_VERSION, RK_TYPE_TAG_SAMPLE}, frame[RK_MAX_FRAME_LEN];
    memcpy(body + 2, "TAG-0005\0\0\0\0\0\0\0\0", 16);
    memcpy(body + 18, "S\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0", 16);
    size_t fl;
    for (int i = 0; i < 4; i++) { body[34] = (uint8_t)i; rk_device_emit(&d, RK_TYPE_TAG_SAMPLE, body, sizeof body, frame, &fl); }
    CHECK_EQ(rk_device_provision(&k, "TAG-0005", 1, key1), RK_OK); /* key rotated */
    rk_device_t d2;
    CHECK_EQ(rk_device_load(&d2, &k, &ring), RK_OK);
    CHECK_EQ(d2.key_epoch, 1);
    CHECK_EQ(d2.seq, 4); /* seq NOT reset: (key, nonce) pairs stay unique and the chain continues */
    CHECK(memcmp(d2.key, key1, 32) == 0);
    CHECK_EQ(rk_device_provision(&k, "", 0, key1), RK_ERR_ARG);
}

int main(void) {
    RUN(test_crc);
    RUN(test_ring_push_peek_ack);
    RUN(test_ack_only_deletes_a_contiguous_prefix);
    RUN(test_overwrite_oldest_and_count_drops);
    RUN(test_recovery_after_reboot_and_wraparound);
    RUN(test_torn_write_is_ignored);
    RUN(test_storage_errors_are_reported);
    RUN(test_device_reproduces_the_python_vector);
    RUN(test_seq_is_persisted_before_use_and_survives_reboot);
    RUN(test_refuses_to_encrypt_when_seq_cannot_be_persisted);
    RUN(test_refuses_to_start_when_persisted_state_is_unreadable);
    RUN(test_reprovisioning_bumps_epoch_but_keeps_seq);
    RK_TEST_MAIN_END("ring+device");
}
