/*
 * Rakshak record format v1 - constants. Mirrors backend/rakshak/codec/spec.py (keep in sync).
 * Normative description: firmware/common/spec/RECORD_SPEC.md
 */
#ifndef RK_SPEC_H
#define RK_SPEC_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#define RK_STATIC_ASSERT(cond, msg) static_assert(cond, msg)
#else
#define RK_STATIC_ASSERT(cond, msg) _Static_assert(cond, msg)
#endif

#define RK_VERSION 1

#define RK_HASH_LEN 32
#define RK_KEY_LEN 32
#define RK_NONCE_LEN 12
#define RK_GCM_TAG_LEN 16
#define RK_ID_LEN 16 /* device_id / shipment_id, ASCII, NUL padded */

typedef enum {
    RK_TYPE_TAG_SAMPLE = 1,
    RK_TYPE_HUB_SAMPLE = 2,
    RK_TYPE_EVENT = 3,
} rk_type_t;

typedef enum {
    RK_EVENT_TIME_SYNC = 1, /* ts = epoch at sync; arg0|arg1<<16 = device monotonic seconds */
    RK_EVENT_BOOT = 2,
    RK_EVENT_LID_OPEN = 3,
    RK_EVENT_SHOCK = 4, /* arg0 = shock_g_x100 */
    RK_EVENT_LOW_BATTERY = 5,
    RK_EVENT_PAIRED = 6,
    RK_EVENT_KEY_ROTATED = 7, /* arg0 = new key_epoch */
} rk_event_code_t;

/* flags for tag samples and events */
#define RK_TAG_FLAG_LID_OPEN (1u << 0)
#define RK_TAG_FLAG_TS_VALID (1u << 1)
/* flags for hub samples */
#define RK_HUB_FLAG_LID_OPEN (1u << 0)
#define RK_HUB_FLAG_TS_VALID (1u << 1)
#define RK_HUB_FLAG_GPS_VALID (1u << 2)
#define RK_HUB_FLAG_FAN_ON (1u << 3)

#define RK_COMMON_LEN 42 /* version,type,device_id[16],shipment_id[16],seq,ts */
#define RK_TAG_BODY_LEN 50
#define RK_EVENT_BODY_LEN 50
#define RK_HUB_BODY_LEN 60
#define RK_HEADER_LEN 24 /* version,type,device_id[16],key_epoch,seq - also the GCM AAD */

#define RK_PLAINTEXT_LEN(body) ((body) + 2 * RK_HASH_LEN)
#define RK_FRAME_LEN(body) (RK_HEADER_LEN + RK_PLAINTEXT_LEN(body) + RK_GCM_TAG_LEN)

#define RK_TAG_FRAME_LEN RK_FRAME_LEN(RK_TAG_BODY_LEN)     /* 154 */
#define RK_EVENT_FRAME_LEN RK_FRAME_LEN(RK_EVENT_BODY_LEN) /* 154 */
#define RK_HUB_FRAME_LEN RK_FRAME_LEN(RK_HUB_BODY_LEN)     /* 164 */
#define RK_MAX_FRAME_LEN RK_HUB_FRAME_LEN
#define RK_MAX_BODY_LEN RK_HUB_BODY_LEN

RK_STATIC_ASSERT(RK_TAG_BODY_LEN == 50, "tag body must be 50 bytes");
RK_STATIC_ASSERT(RK_EVENT_BODY_LEN == 50, "event body must be 50 bytes");
RK_STATIC_ASSERT(RK_HUB_BODY_LEN == 60, "hub body must be 60 bytes");
RK_STATIC_ASSERT(RK_TAG_FRAME_LEN == 154, "tag frame must be 154 bytes");
RK_STATIC_ASSERT(RK_EVENT_FRAME_LEN == 154, "event frame must be 154 bytes");
RK_STATIC_ASSERT(RK_HUB_FRAME_LEN == 164, "hub frame must be 164 bytes");
RK_STATIC_ASSERT(RK_HEADER_LEN == 24, "header must be 24 bytes");

typedef enum {
    RK_OK = 0,
    RK_ERR_ARG = -1,
    RK_ERR_CRYPTO = -2,
    RK_ERR_AUTH = -3, /* GCM tag mismatch: wrong key/epoch or modified frame */
    RK_ERR_FORMAT = -4,
    RK_ERR_SIZE = -5,
} rk_err_t;

#ifdef __cplusplus
}
#endif
#endif /* RK_SPEC_H */
