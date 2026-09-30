#include "rk_codec.h"

#include <stdio.h>
#include <string.h>

#include "mbedtls/gcm.h"
#include "mbedtls/hkdf.h"
#include "mbedtls/md.h"
#include "mbedtls/platform_util.h"
#include "mbedtls/sha256.h"

/* ---- little-endian helpers ------------------------------------------------------------- */
static void put16(uint8_t *p, uint16_t v) {
    p[0] = (uint8_t)v;
    p[1] = (uint8_t)(v >> 8);
}
static void put32(uint8_t *p, uint32_t v) {
    for (int i = 0; i < 4; i++) p[i] = (uint8_t)(v >> (8 * i));
}
static uint16_t get16(const uint8_t *p) { return (uint16_t)(p[0] | (p[1] << 8)); }
static uint32_t get32(const uint8_t *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

/* Identifiers: 1..16 chars of [A-Za-z0-9_-], NUL padded. */
static int put_id(uint8_t *out, const char *id) {
    if (id == NULL) return RK_ERR_ARG;
    size_t n = strlen(id);
    if (n == 0 || n > RK_ID_LEN) return RK_ERR_ARG;
    for (size_t i = 0; i < n; i++) {
        char c = id[i];
        int ok = (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') ||
                 c == '_' || c == '-';
        if (!ok) return RK_ERR_ARG;
    }
    memset(out, 0, RK_ID_LEN);
    memcpy(out, id, n);
    return RK_OK;
}

static void get_id(char *dst, const uint8_t *src) {
    memcpy(dst, src, RK_ID_LEN);
    dst[RK_ID_LEN] = '\0';
}

size_t rk_body_len(uint8_t type) {
    switch (type) {
        case RK_TYPE_TAG_SAMPLE: return RK_TAG_BODY_LEN;
        case RK_TYPE_HUB_SAMPLE: return RK_HUB_BODY_LEN;
        case RK_TYPE_EVENT: return RK_EVENT_BODY_LEN;
        default: return 0;
    }
}

size_t rk_frame_len(uint8_t type) {
    size_t b = rk_body_len(type);
    return b ? RK_FRAME_LEN(b) : 0;
}

static int pack_common(uint8_t *out, uint8_t type, const rk_common_t *c) {
    out[0] = RK_VERSION;
    out[1] = type;
    if (put_id(out + 2, c->device_id) != RK_OK) return RK_ERR_ARG;
    if (put_id(out + 18, c->shipment_id) != RK_OK) return RK_ERR_ARG;
    put32(out + 34, c->seq);
    put32(out + 38, c->ts);
    return RK_OK;
}

int rk_pack_tag(const rk_tag_sample_t *r, uint8_t out[RK_TAG_BODY_LEN]) {
    if (pack_common(out, RK_TYPE_TAG_SAMPLE, &r->c) != RK_OK) return RK_ERR_ARG;
    put16(out + 42, (uint16_t)r->temp_x100);
    put16(out + 44, r->rh_x100);
    put16(out + 46, r->ethylene_idx_x10);
    out[48] = r->flags;
    out[49] = r->batt_pct;
    return RK_OK;
}

int rk_pack_hub(const rk_hub_sample_t *r, uint8_t out[RK_HUB_BODY_LEN]) {
    if (pack_common(out, RK_TYPE_HUB_SAMPLE, &r->c) != RK_OK) return RK_ERR_ARG;
    put16(out + 42, (uint16_t)r->temp_x100);
    put16(out + 44, r->rh_x100);
    put16(out + 46, r->shock_g_x100);
    put32(out + 48, (uint32_t)r->lat_e6);
    put32(out + 52, (uint32_t)r->lon_e6);
    out[56] = r->flags;
    out[57] = r->flap_pct;
    out[58] = r->batt_pct;
    out[59] = r->alert_level;
    return RK_OK;
}

int rk_pack_event(const rk_event_t *r, uint8_t out[RK_EVENT_BODY_LEN]) {
    if (pack_common(out, RK_TYPE_EVENT, &r->c) != RK_OK) return RK_ERR_ARG;
    put16(out + 42, r->event_code);
    put16(out + 44, r->arg0);
    put16(out + 46, r->arg1);
    out[48] = r->flags;
    out[49] = r->batt_pct;
    return RK_OK;
}

int rk_unpack_tag(const uint8_t *body, size_t len, rk_tag_sample_t *r) {
    if (len != RK_TAG_BODY_LEN || body[0] != RK_VERSION || body[1] != RK_TYPE_TAG_SAMPLE)
        return RK_ERR_FORMAT;
    get_id(r->c.device_id, body + 2);
    get_id(r->c.shipment_id, body + 18);
    r->c.seq = get32(body + 34);
    r->c.ts = get32(body + 38);
    r->temp_x100 = (int16_t)get16(body + 42);
    r->rh_x100 = get16(body + 44);
    r->ethylene_idx_x10 = get16(body + 46);
    r->flags = body[48];
    r->batt_pct = body[49];
    return RK_OK;
}

/* ---- hashing / KDF -------------------------------------------------------------------- */
int rk_chain_hash(const uint8_t prev_hash[RK_HASH_LEN], const uint8_t *body, size_t body_len,
                  uint8_t out[RK_HASH_LEN]) {
    mbedtls_sha256_context ctx;
    mbedtls_sha256_init(&ctx);
    int rc = mbedtls_sha256_starts(&ctx, 0);
    if (rc == 0) rc = mbedtls_sha256_update(&ctx, prev_hash, RK_HASH_LEN);
    if (rc == 0) rc = mbedtls_sha256_update(&ctx, body, body_len);
    if (rc == 0) rc = mbedtls_sha256_finish(&ctx, out);
    mbedtls_sha256_free(&ctx);
    return rc == 0 ? RK_OK : RK_ERR_CRYPTO;
}

int rk_hkdf_sha256(const uint8_t *salt, size_t salt_len, const uint8_t *ikm, size_t ikm_len,
                   const uint8_t *info, size_t info_len, uint8_t *okm, size_t okm_len) {
    const mbedtls_md_info_t *md = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
    if (md == NULL) return RK_ERR_CRYPTO;
    int rc = mbedtls_hkdf(md, salt, salt_len, ikm, ikm_len, info, info_len, okm, okm_len);
    return rc == 0 ? RK_OK : RK_ERR_CRYPTO;
}

int rk_derive_device_key(const uint8_t master[RK_KEY_LEN], const char *device_id,
                         uint16_t key_epoch, uint8_t key[RK_KEY_LEN]) {
    uint8_t probe[RK_ID_LEN];
    if (put_id(probe, device_id) != RK_OK) return RK_ERR_ARG;
    char info[64];
    int n = snprintf(info, sizeof info, "rakshak-v1|%s|%u", device_id, (unsigned)key_epoch);
    if (n <= 0 || (size_t)n >= sizeof info) return RK_ERR_ARG;
    return rk_hkdf_sha256(NULL, 0, master, RK_KEY_LEN, (const uint8_t *)info, (size_t)n, key,
                          RK_KEY_LEN);
}

/* ---- frames ---------------------------------------------------------------------------- */
static void make_nonce(uint8_t nonce[RK_NONCE_LEN], uint32_t seq) {
    memset(nonce, 0, 8);
    put32(nonce + 8, seq);
}

int rk_frame_encode(uint8_t type, const char *device_id, uint16_t key_epoch, uint32_t seq,
                    const uint8_t key[RK_KEY_LEN], const uint8_t *body, size_t body_len,
                    const uint8_t prev_hash[RK_HASH_LEN], uint8_t *frame, size_t frame_cap,
                    size_t *frame_len, uint8_t hash_out[RK_HASH_LEN]) {
    size_t blen = rk_body_len(type);
    if (blen == 0 || body_len != blen) return RK_ERR_ARG;
    size_t flen = RK_FRAME_LEN(blen);
    if (frame_cap < flen) return RK_ERR_SIZE;

    uint8_t *header = frame;
    header[0] = RK_VERSION;
    header[1] = type;
    if (put_id(header + 2, device_id) != RK_OK) return RK_ERR_ARG;
    put16(header + 18, key_epoch);
    put32(header + 20, seq);

    uint8_t plain[RK_PLAINTEXT_LEN(RK_MAX_BODY_LEN)];
    memcpy(plain, body, blen);
    memcpy(plain + blen, prev_hash, RK_HASH_LEN);
    int rc = rk_chain_hash(prev_hash, body, blen, plain + blen + RK_HASH_LEN);
    if (rc != RK_OK) return rc;

    uint8_t nonce[RK_NONCE_LEN];
    make_nonce(nonce, seq);

    mbedtls_gcm_context gcm;
    mbedtls_gcm_init(&gcm);
    int mrc = mbedtls_gcm_setkey(&gcm, MBEDTLS_CIPHER_ID_AES, key, 256);
    if (mrc == 0) {
        size_t plen = RK_PLAINTEXT_LEN(blen);
        mrc = mbedtls_gcm_crypt_and_tag(&gcm, MBEDTLS_GCM_ENCRYPT, plen, nonce, RK_NONCE_LEN,
                                        header, RK_HEADER_LEN, plain, frame + RK_HEADER_LEN,
                                        RK_GCM_TAG_LEN, frame + RK_HEADER_LEN + plen);
    }
    mbedtls_gcm_free(&gcm);
    if (mrc == 0 && hash_out != NULL) memcpy(hash_out, plain + blen + RK_HASH_LEN, RK_HASH_LEN);
    mbedtls_platform_zeroize(plain, sizeof plain);
    if (mrc != 0) return RK_ERR_CRYPTO;

    *frame_len = flen;
    return RK_OK;
}

int rk_frame_peek(const uint8_t *frame, size_t len, rk_frame_header_t *hdr) {
    if (len < RK_HEADER_LEN) return RK_ERR_FORMAT;
    if (frame[0] != RK_VERSION) return RK_ERR_FORMAT;
    size_t expect = rk_frame_len(frame[1]);
    if (expect == 0 || len != expect) return RK_ERR_FORMAT;
    hdr->version = frame[0];
    hdr->type = frame[1];
    get_id(hdr->device_id, frame + 2);
    hdr->key_epoch = get16(frame + 18);
    hdr->seq = get32(frame + 20);
    return RK_OK;
}

int rk_frame_decode(const uint8_t key[RK_KEY_LEN], const uint8_t *frame, size_t len,
                    rk_decoded_t *out) {
    int rc = rk_frame_peek(frame, len, &out->header);
    if (rc != RK_OK) return rc;
    size_t blen = rk_body_len(out->header.type);
    size_t plen = RK_PLAINTEXT_LEN(blen);

    uint8_t nonce[RK_NONCE_LEN];
    make_nonce(nonce, out->header.seq);
    uint8_t plain[RK_PLAINTEXT_LEN(RK_MAX_BODY_LEN)];

    mbedtls_gcm_context gcm;
    mbedtls_gcm_init(&gcm);
    int mrc = mbedtls_gcm_setkey(&gcm, MBEDTLS_CIPHER_ID_AES, key, 256);
    if (mrc == 0) {
        mrc = mbedtls_gcm_auth_decrypt(&gcm, plen, nonce, RK_NONCE_LEN, frame, RK_HEADER_LEN,
                                       frame + RK_HEADER_LEN + plen, RK_GCM_TAG_LEN,
                                       frame + RK_HEADER_LEN, plain);
    }
    mbedtls_gcm_free(&gcm);
    if (mrc == MBEDTLS_ERR_GCM_AUTH_FAILED) {
        mbedtls_platform_zeroize(plain, sizeof plain);
        return RK_ERR_AUTH;
    }
    if (mrc != 0) return RK_ERR_CRYPTO;

    memcpy(out->body, plain, blen);
    out->body_len = blen;
    memcpy(out->prev_hash, plain + blen, RK_HASH_LEN);
    memcpy(out->hash, plain + blen + RK_HASH_LEN, RK_HASH_LEN);
    mbedtls_platform_zeroize(plain, sizeof plain);

    uint8_t calc[RK_HASH_LEN];
    rc = rk_chain_hash(out->prev_hash, out->body, blen, calc);
    if (rc != RK_OK) return rc;
    out->hash_ok = memcmp(calc, out->hash, RK_HASH_LEN) == 0;
    return RK_OK;
}
