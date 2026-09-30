/* Host-side cross-language test: the C codec must reproduce every byte the Python codec produced. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "rk_codec.h"
#include "vectors.h"

static int failures = 0;
#define CHECK(cond, ...)                                      \
    do {                                                      \
        if (!(cond)) {                                        \
            failures++;                                       \
            printf("  FAIL %s:%d: ", __FILE__, __LINE__);     \
            printf(__VA_ARGS__);                              \
            printf("\n");                                     \
        }                                                     \
    } while (0)

static size_t unhex(const char *s, uint8_t *out, size_t cap) {
    size_t n = strlen(s) / 2;
    if (n > cap) return 0;
    for (size_t i = 0; i < n; i++) {
        unsigned v;
        sscanf(s + 2 * i, "%2x", &v);
        out[i] = (uint8_t)v;
    }
    return n;
}

static int hexeq(const char *name, const char *want_hex, const uint8_t *got, size_t len) {
    uint8_t want[512];
    size_t n = unhex(want_hex, want, sizeof want);
    if (n != len || memcmp(want, got, len) != 0) {
        printf("  FAIL %s: bytes differ (want %zu bytes, got %zu)\n", name, n, len);
        failures++;
        return 0;
    }
    return 1;
}

static const uint8_t *find_key(const char *dev, unsigned epoch, uint8_t out[32]) {
    for (size_t i = 0; i < VEC_KEYS_N; i++)
        if (!strcmp(VEC_KEYS[i].device_id, dev) && VEC_KEYS[i].key_epoch == epoch) {
            unhex(VEC_KEYS[i].key, out, 32);
            return out;
        }
    return NULL;
}

static int pack_vec(const vec_record_t *v, uint8_t *body) {
    rk_common_t c;
    memset(&c, 0, sizeof c);
    strcpy(c.device_id, v->device_id);
    strcpy(c.shipment_id, v->shipment_id);
    c.seq = v->seq;
    c.ts = v->ts;
    const int64_t *f = v->f;
    if (v->type == RK_TYPE_TAG_SAMPLE) {
        rk_tag_sample_t r = {c, (int16_t)f[0], (uint16_t)f[1], (uint16_t)f[2], (uint8_t)f[3], (uint8_t)f[4]};
        return rk_pack_tag(&r, body);
    }
    if (v->type == RK_TYPE_HUB_SAMPLE) {
        rk_hub_sample_t r = {c, (int16_t)f[0], (uint16_t)f[1], (uint16_t)f[2], (int32_t)f[3],
                             (int32_t)f[4], (uint8_t)f[5], (uint8_t)f[6], (uint8_t)f[7], (uint8_t)f[8]};
        return rk_pack_hub(&r, body);
    }
    rk_event_t r = {c, (uint16_t)f[0], (uint16_t)f[1], (uint16_t)f[2], (uint8_t)f[3], (uint8_t)f[4]};
    return rk_pack_event(&r, body);
}

int main(void) {
    printf("Rakshak C codec vs Python vectors\n");

    CHECK(rk_body_len(RK_TYPE_TAG_SAMPLE) == 50 && rk_body_len(RK_TYPE_HUB_SAMPLE) == 60 &&
              rk_body_len(RK_TYPE_EVENT) == 50,
          "body sizes");
    CHECK(rk_frame_len(RK_TYPE_TAG_SAMPLE) == 154 && rk_frame_len(RK_TYPE_HUB_SAMPLE) == 164 &&
              rk_frame_len(RK_TYPE_EVENT) == 154,
          "frame sizes");

    /* RFC 5869 A.1 (independent of our own Python code) */
    {
        uint8_t ikm[64], salt[64], info[64], want[64], got[42];
        size_t a = unhex(VEC_HKDF.ikm, ikm, 64), b = unhex(VEC_HKDF.salt, salt, 64),
               c = unhex(VEC_HKDF.info, info, 64), d = unhex(VEC_HKDF.okm, want, 64);
        CHECK(rk_hkdf_sha256(salt, b, ikm, a, info, c, got, d) == RK_OK, "hkdf call");
        CHECK(d == 42 && memcmp(got, want, 42) == 0, "hkdf RFC 5869 A.1 mismatch");
    }

    uint8_t master[32];
    unhex(VEC_MASTER_KEY, master, 32);
    for (size_t i = 0; i < VEC_KEYS_N; i++) {
        uint8_t got[32], want[32];
        unhex(VEC_KEYS[i].key, want, 32);
        CHECK(rk_derive_device_key(master, VEC_KEYS[i].device_id, (uint16_t)VEC_KEYS[i].key_epoch, got) == RK_OK &&
                  memcmp(got, want, 32) == 0,
              "device key %s epoch %u", VEC_KEYS[i].device_id, VEC_KEYS[i].key_epoch);
    }

    /* Records: pack -> body, chain hash, encrypt -> frame; then decrypt back. */
    for (size_t i = 0; i < VEC_RECORDS_N; i++) {
        const vec_record_t *v = &VEC_RECORDS[i];
        printf("  %s\n", v->name);
        uint8_t key[32], body[RK_MAX_BODY_LEN], prev[32], frame[RK_MAX_FRAME_LEN], hash[32];
        size_t frame_len = 0;
        if (!find_key(v->device_id, v->key_epoch, key)) {
            CHECK(0, "no key for %s", v->name);
            continue;
        }
        CHECK(pack_vec(v, body) == RK_OK, "pack %s", v->name);
        size_t blen = rk_body_len((uint8_t)v->type);
        hexeq("body", v->body, body, blen);
        unhex(v->prev_hash, prev, 32);
        int rc = rk_frame_encode((uint8_t)v->type, v->device_id, (uint16_t)v->key_epoch, v->seq, key,
                                 body, blen, prev, frame, sizeof frame, &frame_len, hash);
        CHECK(rc == RK_OK, "encode rc=%d", rc);
        hexeq("hash", v->hash, hash, 32);
        hexeq("frame", v->frame, frame, frame_len);

        uint8_t wire[RK_MAX_FRAME_LEN];
        size_t wlen = unhex(v->frame, wire, sizeof wire);
        rk_decoded_t dec;
        rc = rk_frame_decode(key, wire, wlen, &dec);
        CHECK(rc == RK_OK, "decode rc=%d", rc);
        if (rc == RK_OK) {
            CHECK(dec.hash_ok, "stored hash verifies");
            CHECK(dec.body_len == blen && memcmp(dec.body, body, blen) == 0, "decoded body");
            CHECK(memcmp(dec.prev_hash, prev, 32) == 0, "decoded prev_hash");
            CHECK(dec.header.seq == v->seq && !strcmp(dec.header.device_id, v->device_id), "header");
        }
        if (v->type == RK_TYPE_TAG_SAMPLE) {
            rk_tag_sample_t t;
            CHECK(rk_unpack_tag(body, blen, &t) == RK_OK && t.c.seq == v->seq &&
                      t.temp_x100 == (int16_t)v->f[0],
                  "unpack tag");
        }
    }

    /* Negative cases must all fail authentication. */
    for (size_t i = 0; i < VEC_NEG_N; i++) {
        uint8_t key[32], wire[RK_MAX_FRAME_LEN];
        find_key(VEC_NEG[i].device_id, VEC_NEG[i].key_epoch, key);
        size_t wlen = unhex(VEC_NEG[i].frame, wire, sizeof wire);
        rk_decoded_t dec;
        int rc = rk_frame_decode(key, wire, wlen, &dec);
        printf("  negative %s -> rc=%d\n", VEC_NEG[i].name, rc);
        CHECK(rc == RK_ERR_AUTH || rc == RK_ERR_FORMAT, "%s must be rejected", VEC_NEG[i].name);
    }

    /* Invalid identifiers are refused. */
    {
        rk_tag_sample_t t;
        memset(&t, 0, sizeof t);
        strcpy(t.c.device_id, "bad id!");
        strcpy(t.c.shipment_id, "X");
        uint8_t body[RK_TAG_BODY_LEN];
        CHECK(rk_pack_tag(&t, body) == RK_ERR_ARG, "invalid id rejected");
    }

    if (failures) {
        printf("FAILED: %d check(s)\n", failures);
        return 1;
    }
    printf("OK: all vectors match\n");
    return 0;
}
