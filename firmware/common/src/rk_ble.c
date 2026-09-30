#include "rk_ble.h"

#include <string.h>

static void put16(uint8_t *p, uint16_t v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); }
static void put32(uint8_t *p, uint32_t v) { for (int i = 0; i < 4; i++) p[i] = (uint8_t)(v >> (8 * i)); }
static uint16_t get16(const uint8_t *p) { return (uint16_t)(p[0] | (p[1] << 8)); }
static uint32_t get32(const uint8_t *p) { return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24); }
static uint32_t frame_seq(const uint8_t *f) { return get32(f + 20); }

int rk_ble_fragment(const uint8_t *frame, size_t len, uint8_t frame_no, size_t mtu_payload,
                    uint8_t out[][RK_BLE_MAX_NOTIFY], size_t *out_len, int max_out) {
    if (!frame || len == 0 || len > RK_MAX_FRAME_LEN || mtu_payload < 8 || mtu_payload > RK_BLE_MAX_NOTIFY) return RK_ERR_ARG;
    const size_t room = mtu_payload - 4;
    int total = (int)((len + room - 1) / room);
    if (total > max_out || total > 255) return RK_ERR_SIZE;
    size_t off = 0;
    for (int i = 0; i < total; i++) {
        size_t n = len - off < room ? len - off : room;
        out[i][0] = RK_BLE_FRAG;
        out[i][1] = frame_no;
        out[i][2] = (uint8_t)i;
        out[i][3] = (uint8_t)total;
        memcpy(out[i] + 4, frame + off, n);
        out_len[i] = n + 4;
        off += n;
    }
    return total;
}

size_t rk_ble_pack_end(uint8_t *out, uint16_t count, uint32_t first_seq, uint32_t last_seq) {
    out[0] = RK_BLE_END;
    put16(out + 1, count);
    put32(out + 3, first_seq);
    put32(out + 7, last_seq);
    return 11;
}

size_t rk_ble_pack_ack(uint8_t *out, uint32_t first_seq, uint32_t last_seq, uint32_t epoch) {
    out[0] = RK_BLE_ACK;
    put32(out + 1, first_seq);
    put32(out + 5, last_seq);
    put32(out + 9, epoch);
    return 13;
}

int rk_ble_parse_ack(const uint8_t *msg, size_t len, uint32_t *first_seq, uint32_t *last_seq, uint32_t *epoch) {
    if (len != 13 || msg[0] != RK_BLE_ACK) return RK_ERR_FORMAT;
    uint32_t a = get32(msg + 1), b = get32(msg + 5);
    if (a > b) return RK_ERR_FORMAT;
    *first_seq = a;
    *last_seq = b;
    *epoch = get32(msg + 9);
    return RK_OK;
}

void rk_ble_rx_init(rk_ble_rx_t *rx) {
    memset(rx, 0, sizeof *rx);
    rx->cur_no = -1;
}

int rk_ble_rx_feed(rk_ble_rx_t *rx, const uint8_t *msg, size_t len) {
    if (len < 1) return RK_ERR_FORMAT;
    if (msg[0] == RK_BLE_FRAG) {
        if (len < 5) return RK_ERR_FORMAT;
        int frame_no = msg[1], idx = msg[2], total = msg[3];
        if (total == 0 || idx >= total) return RK_ERR_FORMAT;
        if (idx == 0) { /* a new frame starts; anything unfinished before it is discarded */
            rx->cur_len = 0;
            rx->cur_no = frame_no;
            rx->cur_next_idx = 0;
            rx->cur_total = total;
        }
        if (frame_no != rx->cur_no || idx != rx->cur_next_idx || total != rx->cur_total) return RK_ERR_FORMAT;
        size_t n = len - 4;
        if (rx->cur_len + n > RK_MAX_FRAME_LEN) return RK_ERR_SIZE;
        memcpy(rx->cur + rx->cur_len, msg + 4, n);
        rx->cur_len += n;
        rx->cur_next_idx++;
        if (rx->cur_next_idx == rx->cur_total) { /* frame complete */
            if (rx->n >= RK_BLE_MAX_BATCH) return RK_ERR_SIZE;
            memcpy(rx->frames[rx->n], rx->cur, rx->cur_len);
            rx->lens[rx->n] = rx->cur_len;
            rx->n++;
            rx->cur_len = 0;
            rx->cur_no = -1;
        }
        return RK_OK;
    }
    if (msg[0] == RK_BLE_END) {
        if (len != 11 || rx->cur_no != -1) return RK_ERR_FORMAT; /* END while a frame is unfinished */
        uint16_t count = get16(msg + 1);
        uint32_t first = get32(msg + 3), last = get32(msg + 7);
        if (count != rx->n || count == 0) return RK_ERR_FORMAT;
        if (frame_seq(rx->frames[0]) != first || frame_seq(rx->frames[rx->n - 1]) != last) return RK_ERR_FORMAT;
        for (int i = 1; i < rx->n; i++)
            if (frame_seq(rx->frames[i]) <= frame_seq(rx->frames[i - 1])) return RK_ERR_FORMAT; /* must be increasing */
        rx->complete = 1;
        rx->first_seq = first;
        rx->last_seq = last;
        return RK_OK;
    }
    return RK_ERR_FORMAT;
}
