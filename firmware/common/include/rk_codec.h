/*
 * Rakshak codec v1: record bodies, SHA-256 hash chain, AES-256-GCM frames (mbedTLS 3.x).
 * Pure C, no Arduino/ESP-IDF dependency: builds on the host for the cross-language vector test.
 */
#ifndef RK_CODEC_H
#define RK_CODEC_H

#include "rk_spec.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    char device_id[RK_ID_LEN + 1];
    char shipment_id[RK_ID_LEN + 1];
    uint32_t seq;
    uint32_t ts; /* epoch seconds if ts_valid, else device-monotonic seconds */
} rk_common_t;

typedef struct {
    rk_common_t c;
    int16_t temp_x100;
    uint16_t rh_x100;
    uint16_t ethylene_idx_x10;
    uint8_t flags;
    uint8_t batt_pct;
} rk_tag_sample_t;

typedef struct {
    rk_common_t c;
    int16_t temp_x100;
    uint16_t rh_x100;
    uint16_t shock_g_x100;
    int32_t lat_e6;
    int32_t lon_e6;
    uint8_t flags;
    uint8_t flap_pct;
    uint8_t batt_pct;
    uint8_t alert_level; /* 0 SAFE, 1 WARNING, 2 CRITICAL */
} rk_hub_sample_t;

typedef struct {
    rk_common_t c;
    uint16_t event_code;
    uint16_t arg0;
    uint16_t arg1;
    uint8_t flags;
    uint8_t batt_pct;
} rk_event_t;

typedef struct {
    uint8_t version;
    uint8_t type;
    char device_id[RK_ID_LEN + 1];
    uint16_t key_epoch;
    uint32_t seq;
} rk_frame_header_t;

typedef struct {
    rk_frame_header_t header;
    uint8_t body[RK_MAX_BODY_LEN];
    size_t body_len;
    uint8_t prev_hash[RK_HASH_LEN];
    uint8_t hash[RK_HASH_LEN];
    int hash_ok; /* stored hash == SHA-256(prev_hash || body) */
} rk_decoded_t;

/* Body length for a record type, or 0 if the type is unknown. */
size_t rk_body_len(uint8_t type);
/* Frame length for a record type, or 0 if the type is unknown. */
size_t rk_frame_len(uint8_t type);

/* Pack bodies (little-endian, fixed layout). Return RK_OK or RK_ERR_ARG (bad identifier). */
int rk_pack_tag(const rk_tag_sample_t *r, uint8_t out[RK_TAG_BODY_LEN]);
int rk_pack_hub(const rk_hub_sample_t *r, uint8_t out[RK_HUB_BODY_LEN]);
int rk_pack_event(const rk_event_t *r, uint8_t out[RK_EVENT_BODY_LEN]);
int rk_unpack_tag(const uint8_t *body, size_t len, rk_tag_sample_t *r);

/* hash = SHA-256(prev_hash || body) */
int rk_chain_hash(const uint8_t prev_hash[RK_HASH_LEN], const uint8_t *body, size_t body_len,
                  uint8_t out[RK_HASH_LEN]);

/* RFC 5869 HKDF-SHA256. salt may be NULL (=> 32 zero bytes). */
int rk_hkdf_sha256(const uint8_t *salt, size_t salt_len, const uint8_t *ikm, size_t ikm_len,
                   const uint8_t *info, size_t info_len, uint8_t *okm, size_t okm_len);
/* key = HKDF(master, info="rakshak-v1|<device_id>|<key_epoch>"). Used by tests/provisioning. */
int rk_derive_device_key(const uint8_t master[RK_KEY_LEN], const char *device_id,
                         uint16_t key_epoch, uint8_t key[RK_KEY_LEN]);

/* Encrypt one record into a frame. frame_cap must be >= rk_frame_len(type). */
int rk_frame_encode(uint8_t type, const char *device_id, uint16_t key_epoch, uint32_t seq,
                    const uint8_t key[RK_KEY_LEN], const uint8_t *body, size_t body_len,
                    const uint8_t prev_hash[RK_HASH_LEN], uint8_t *frame, size_t frame_cap,
                    size_t *frame_len, uint8_t hash_out[RK_HASH_LEN]);

/* Parse the unencrypted header only (hub ACKs by seq without any key). */
int rk_frame_peek(const uint8_t *frame, size_t len, rk_frame_header_t *hdr);

/* Authenticate + decrypt. RK_ERR_AUTH on wrong key/epoch or any modified byte. */
int rk_frame_decode(const uint8_t key[RK_KEY_LEN], const uint8_t *frame, size_t len,
                    rk_decoded_t *out);

#ifdef __cplusplus
}
#endif
#endif /* RK_CODEC_H */
