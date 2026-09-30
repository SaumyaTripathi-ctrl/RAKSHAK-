/*
 * Tag -> hub transfer format (transport-agnostic; the GATT glue lives in the tag/hub projects).
 *
 * The tag notifies each frame (fragmented if the negotiated MTU is small), then an END marker. The hub
 * verifies the batch (count + contiguous seq range) and writes back an ACK carrying the seq range and the current
 * epoch time (GNSS). The tag deletes its copies ONLY after a valid ACK.
 *
 *   FRAG : [0x01][frame_no u8][idx u8][total u8][payload...]     one fragment of one frame
 *   END  : [0x02][count u16][first_seq u32][last_seq u32]        little-endian
 *   ACK  : [0x10][first_seq u32][last_seq u32][epoch u32]        hub -> tag (write)
 */
#ifndef RK_BLE_H
#define RK_BLE_H

#include "rk_spec.h"

#ifdef __cplusplus
extern "C" {
#endif

#define RK_BLE_FRAG 0x01
#define RK_BLE_END 0x02
#define RK_BLE_ACK 0x10
#define RK_BLE_MAX_NOTIFY 244 /* MTU 247 - 3 */
#define RK_BLE_MAX_BATCH 64

/* Split one frame into notification payloads of at most `mtu_payload` bytes. Returns the number of fragments
 * written to `out` (each out[i] is `out_len[i]` bytes, buffers of RK_BLE_MAX_NOTIFY), or a negative error. */
int rk_ble_fragment(const uint8_t *frame, size_t len, uint8_t frame_no, size_t mtu_payload,
                    uint8_t out[][RK_BLE_MAX_NOTIFY], size_t *out_len, int max_out);

size_t rk_ble_pack_end(uint8_t *out, uint16_t count, uint32_t first_seq, uint32_t last_seq);
size_t rk_ble_pack_ack(uint8_t *out, uint32_t first_seq, uint32_t last_seq, uint32_t epoch);
/* Returns RK_OK and fills the fields when `msg` is a valid ACK. */
int rk_ble_parse_ack(const uint8_t *msg, size_t len, uint32_t *first_seq, uint32_t *last_seq, uint32_t *epoch);

/* Receiver (hub side): feed notifications in order; when an END marker validates the batch, `complete` is set. */
typedef struct {
    uint8_t frames[RK_BLE_MAX_BATCH][RK_MAX_FRAME_LEN];
    size_t lens[RK_BLE_MAX_BATCH];
    int n;
    /* reassembly of the frame in progress */
    uint8_t cur[RK_MAX_FRAME_LEN];
    size_t cur_len;
    int cur_no, cur_next_idx, cur_total;
    /* result */
    int complete;
    uint32_t first_seq, last_seq;
} rk_ble_rx_t;

void rk_ble_rx_init(rk_ble_rx_t *rx);
/* RK_OK, or RK_ERR_FORMAT on a malformed/out-of-order notification, RK_ERR_SIZE if the batch overflows.
 * On END, RK_OK means the batch is consistent (count and contiguous/monotonic seq) and rx->complete is 1;
 * RK_ERR_FORMAT means the batch must NOT be acknowledged (the tag keeps its copies). */
int rk_ble_rx_feed(rk_ble_rx_t *rx, const uint8_t *msg, size_t len);

#ifdef __cplusplus
}
#endif
#endif
