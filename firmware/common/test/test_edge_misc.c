/* Edge rules vs the Python reference, ethylene calibration, BLE batching, command/AT parsing, tag clock. */
#include <stdlib.h>

#include "edge_vectors.h"
#include "rk_ble.h"
#include "rk_clock.h"
#include "rk_cmd.h"
#include "rk_edge.h"
#include "rk_ethylene.h"
#include "rk_test.h"

/* ---- edge rules ------------------------------------------------------------------------------------------ */
static void test_flap_matches_python(void) {
    for (size_t i = 0; i < EV_FLAP_N; i++)
        CHECK_EQ(rk_flap_for_deviation(EV_FLAP[i].temp, EV_FLAP[i].upper, 0.0, 1.5, 3.0), EV_FLAP[i].flap);
}

static void test_fan_matches_python_step_for_step(void) {
    for (size_t c = 0; c < EV_FAN_CASES_N; c++) {
        rk_fan_t f;
        rk_fan_init(&f);
        int mismatches = 0;
        for (int i = 0; i < EV_FAN_CASES[c].n; i++)
            if (rk_fan_update(&f, i * EV_STEP_MIN, EV_FAN_CASES[c].series[i]) != EV_FAN_CASES[c].expected[i]) mismatches++;
        if (mismatches) printf("  case %s: %d mismatching steps\n", EV_FAN_CASES[c].name, mismatches);
        CHECK_EQ(mismatches, 0);
    }
}

static void test_fan_ignores_out_of_order_and_alert_levels(void) {
    rk_fan_t f;
    rk_fan_init(&f);
    rk_fan_update(&f, 10, 5);
    CHECK_EQ(rk_fan_update(&f, 10, 99), 0);
    CHECK_EQ(rk_fan_update(&f, 5, 99), 0);
    CHECK_EQ(rk_edge_alert_level(13.0, 13.0), 0);
    CHECK_EQ(rk_edge_alert_level(16.0, 13.0), 1);
    CHECK_EQ(rk_edge_alert_level(19.5, 13.0), 2);
}

/* ---- ethylene ---------------------------------------------------------------------------------------------- */
static void test_ethylene_index_is_monotone_clamped_and_humidity_corrected(void) {
    float prev = -1;
    for (int b = 60; b <= 260; b += 10) {
        float idx = rk_ethylene_index(100, 90, (uint16_t)b, 300, 60.0f, NULL);
        CHECK(idx >= prev);
        CHECK(idx >= 0.0f && idx <= 100.0f);
        prev = idx;
    }
    CHECK_NEAR(rk_ethylene_index(100, 90, 50, 300, 60, NULL), 0.0, 1e-4);   /* below the first point: clamped */
    CHECK_NEAR(rk_ethylene_index(100, 90, 300, 300, 60, NULL), 100.0, 1e-4); /* above the last: clamped */
    CHECK_NEAR(rk_ethylene_index(100, 90, 100, 300, 60, NULL), 25.0, 1e-3);  /* a calibration point */
    CHECK_NEAR(rk_ethylene_index(100, 90, 115, 300, 60, NULL), 25.0 + (0.15 / 0.30) * 30.0, 1e-2);
    CHECK_EQ(rk_ethylene_index(0, 0, 50, 0, 60, NULL), 0); /* dark/saturated sensor: no reading, no crash */
    float humid = rk_ethylene_index(100, 90, 130, 300, 95.0f, NULL);
    float dry = rk_ethylene_index(100, 90, 130, 300, 30.0f, NULL);
    CHECK(humid < dry); /* the (placeholder) humidity hook is applied */
    CHECK_NEAR(rk_eth_default_humidity_factor(60.0f), 1.0, 1e-6);
}

/* ---- BLE batching ---------------------------------------------------------------------------------------- */
static size_t mkframe(uint8_t *f, uint32_t seq) {
    memset(f, 0x5A, RK_TAG_FRAME_LEN);
    f[0] = RK_VERSION; f[1] = RK_TYPE_TAG_SAMPLE;
    f[20] = (uint8_t)seq; f[21] = (uint8_t)(seq >> 8); f[22] = f[23] = 0;
    f[100] = (uint8_t)(seq * 7); /* payload marker so reassembly errors are visible */
    return RK_TAG_FRAME_LEN;
}

static void send_batch(rk_ble_rx_t *rx, uint32_t first, int count, size_t mtu_payload, int *rc_end) {
    uint8_t frames[8][RK_MAX_FRAME_LEN];
    static uint8_t frag[16][RK_BLE_MAX_NOTIFY];
    size_t fl[16];
    for (int i = 0; i < count; i++) {
        size_t n = mkframe(frames[i], first + (uint32_t)i);
        int nf = rk_ble_fragment(frames[i], n, (uint8_t)i, mtu_payload, frag, fl, 16);
        CHECK(nf > 0);
        for (int k = 0; k < nf; k++) CHECK_EQ(rk_ble_rx_feed(rx, frag[k], fl[k]), RK_OK);
    }
    uint8_t end[16];
    size_t en = rk_ble_pack_end(end, (uint16_t)count, first, first + (uint32_t)count - 1);
    *rc_end = rk_ble_rx_feed(rx, end, en);
}

static void test_ble_batch_roundtrip_at_full_and_small_mtu(void) {
    size_t mtus[] = {244, 100, 23 - 3 + 20 /* 40 */, 16};
    for (size_t m = 0; m < 4; m++) {
        rk_ble_rx_t rx;
        rk_ble_rx_init(&rx);
        int rc;
        send_batch(&rx, 40, 5, mtus[m], &rc);
        CHECK_EQ(rc, RK_OK);
        CHECK(rx.complete);
        CHECK_EQ(rx.n, 5);
        CHECK_EQ(rx.first_seq, 40);
        CHECK_EQ(rx.last_seq, 44);
        CHECK_EQ(rx.lens[2], RK_TAG_FRAME_LEN);
        CHECK_EQ(rx.frames[3][100], (uint8_t)(43 * 7)); /* reassembled intact */
    }
}

static void test_ble_rejects_inconsistent_batches(void) {
    uint8_t f[RK_MAX_FRAME_LEN], end[16];
    static uint8_t frag[8][RK_BLE_MAX_NOTIFY];
    size_t fl[8];
    rk_ble_rx_t rx;

    rk_ble_rx_init(&rx); /* count lies */
    size_t n = mkframe(f, 7);
    int nf = rk_ble_fragment(f, n, 0, 244, frag, fl, 8);
    for (int k = 0; k < nf; k++) rk_ble_rx_feed(&rx, frag[k], fl[k]);
    size_t en = rk_ble_pack_end(end, 2, 7, 7);
    CHECK(rk_ble_rx_feed(&rx, end, en) != RK_OK);
    CHECK(!rx.complete); /* => the hub does not ACK, the tag keeps its records */

    rk_ble_rx_init(&rx); /* first/last do not match the frames */
    for (int k = 0; k < nf; k++) rk_ble_rx_feed(&rx, frag[k], fl[k]);
    en = rk_ble_pack_end(end, 1, 7, 9);
    CHECK(rk_ble_rx_feed(&rx, end, en) != RK_OK);

    rk_ble_rx_init(&rx); /* a fragment lost in the middle */
    nf = rk_ble_fragment(f, n, 0, 64, frag, fl, 8);
    CHECK(nf >= 3);
    CHECK_EQ(rk_ble_rx_feed(&rx, frag[0], fl[0]), RK_OK);
    CHECK(rk_ble_rx_feed(&rx, frag[nf - 1], fl[nf - 1]) != RK_OK); /* fragment 1 never arrived */
    en = rk_ble_pack_end(end, 1, 7, 7);
    CHECK(rk_ble_rx_feed(&rx, end, en) != RK_OK); /* END while a frame is unfinished */

    rk_ble_rx_init(&rx); /* non-increasing seq */
    uint8_t g[RK_MAX_FRAME_LEN];
    for (uint32_t s = 0; s < 2; s++) {
        n = mkframe(g, s == 0 ? 9 : 4);
        nf = rk_ble_fragment(g, n, (uint8_t)s, 244, frag, fl, 8);
        for (int k = 0; k < nf; k++) rk_ble_rx_feed(&rx, frag[k], fl[k]);
    }
    en = rk_ble_pack_end(end, 2, 9, 4);
    CHECK(rk_ble_rx_feed(&rx, end, en) != RK_OK);

    CHECK(rk_ble_rx_feed(&rx, (const uint8_t *)"\x77", 1) != RK_OK); /* garbage */
    CHECK(rk_ble_rx_feed(&rx, (const uint8_t *)"", 0) != RK_OK);
}

static void test_ble_ack_roundtrip_and_validation(void) {
    uint8_t ack[16];
    size_t n = rk_ble_pack_ack(ack, 10, 19, 1791000000u);
    uint32_t a, b, e;
    CHECK_EQ(rk_ble_parse_ack(ack, n, &a, &b, &e), RK_OK);
    CHECK(a == 10 && b == 19 && e == 1791000000u);
    CHECK(rk_ble_parse_ack(ack, n - 1, &a, &b, &e) != RK_OK);
    n = rk_ble_pack_ack(ack, 20, 10, 5); /* reversed range */
    CHECK(rk_ble_parse_ack(ack, n, &a, &b, &e) != RK_OK);
    ack[0] = 0x99;
    CHECK(rk_ble_parse_ack(ack, 13, &a, &b, &e) != RK_OK);
}

/* ---- commands --------------------------------------------------------------------------------------------- */
static void test_command_parsing(void) {
    rk_cmd_t c;
    const char *ok = "{\"id\":\"7d1c-42\",\"cmd\":\"FLAP_SET\",\"arg\":50,\"source\":\"ai\",\"ts\":1791003601}";
    CHECK_EQ(rk_cmd_parse(ok, strlen(ok), &c), 0);
    CHECK(c.kind == RK_CMD_FLAP_SET && c.has_arg && c.arg == 50);
    CHECK(strcmp(c.id, "7d1c-42") == 0);

    const char *sp = "  { \"cmd\" : \"FAN_ON\" , \"arg\" : null , \"id\" : \"x\" }  ";
    CHECK_EQ(rk_cmd_parse(sp, strlen(sp), &c), 0);
    CHECK(c.kind == RK_CMD_FAN_ON && !c.has_arg);

    struct { const char *name; rk_cmd_kind_t kind; } names[] = {
        {"FAN_OFF", RK_CMD_FAN_OFF}, {"ALERT_WARNING", RK_CMD_ALERT_WARNING}, {"ALERT_CRITICAL", RK_CMD_ALERT_CRITICAL},
        {"ALERT_CLEAR", RK_CMD_ALERT_CLEAR}, {"ACK_ALERT", RK_CMD_ACK_ALERT}, {"SELF_DESTRUCT", RK_CMD_UNKNOWN}};
    for (int i = 0; i < 6; i++) {
        char buf[96];
        snprintf(buf, sizeof buf, "{\"id\":\"a\",\"cmd\":\"%s\",\"arg\":null}", names[i].name);
        CHECK_EQ(rk_cmd_parse(buf, strlen(buf), &c), 0);
        CHECK(c.kind == names[i].kind);
    }
    const char *bad_flap[] = {"{\"cmd\":\"FLAP_SET\",\"arg\":33}", "{\"cmd\":\"FLAP_SET\"}", "{\"cmd\":\"FLAP_SET\",\"arg\":-5}", "{\"cmd\":\"FLAP_SET\",\"arg\":101}"};
    for (int i = 0; i < 4; i++) {
        CHECK_EQ(rk_cmd_parse(bad_flap[i], strlen(bad_flap[i]), &c), 0);
        CHECK(c.kind == RK_CMD_UNKNOWN); /* never actuate on an out-of-range value */
    }
    const char *malformed[] = {"", "{", "not json", "{\"cmd\":}", "{\"cmd\":\"FAN_ON\"", "[1,2]", "{\"id\":\"a\"}", "{\"cmd\":{\"x\":1}}", "{\"cmd\":\"A\\u0041\"}"};
    for (size_t i = 0; i < sizeof malformed / sizeof *malformed; i++) CHECK_EQ(rk_cmd_parse(malformed[i], strlen(malformed[i]), &c), -1);
    char big[600];
    memset(big, ' ', sizeof big);
    memcpy(big, "{\"cmd\":\"FAN_ON\"}", 16);
    CHECK_EQ(rk_cmd_parse(big, sizeof big, &c), -1); /* oversized input is refused */
    const char *longid = "{\"cmd\":\"FAN_ON\",\"id\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\"}";
    CHECK_EQ(rk_cmd_parse(longid, strlen(longid), &c), 0);
    CHECK(strlen(c.id) < sizeof c.id); /* truncated, never overflowed */
}

static void test_command_ack_json_is_safe(void) {
    char out[128];
    CHECK(rk_cmd_ack_json(out, sizeof out, "abc-1", 1) > 0);
    CHECK(strcmp(out, "{\"type\":\"cmd_ack\",\"id\":\"abc-1\",\"ok\":true}") == 0);
    rk_cmd_ack_json(out, sizeof out, "x\"}, \"ok\":true, \"y\":\"", 0);
    CHECK(strstr(out, "\\") == NULL && strstr(out, "\"ok\":false}") != NULL); /* quotes from the network cannot break the JSON */
    CHECK_EQ(rk_cmd_ack_json(out, 10, "abc", 1), 0); /* too small: refuses, never truncates silently */
}

/* ---- modem parsers ------------------------------------------------------------------------------------------ */
static void test_gnss_and_modem_parsers(void) {
    rk_gnss_t g;
    /* 16 59.4 N, 73 18 E style values in ddmm.mmmm: lat 1659.4124 = 16 deg 59.4124 min */
    const char *fix = "+CGNSSINFO: 2,09,03,00,00,1659.412400,N,07318.001200,E,011026,061700.0,12.5,0.0,0.0,1.1,0.9,1.0";
    CHECK_EQ(rk_parse_cgnssinfo(fix, &g), 0);
    CHECK(g.fix);
    CHECK_NEAR(g.lat, 16.0 + 59.4124 / 60.0, 1e-6);
    CHECK_NEAR(g.lon, 73.0 + 18.0012 / 60.0, 1e-6);
    CHECK_EQ(g.epoch, rk_epoch_from_utc(2026, 10, 1, 6, 17, 0));
    CHECK_EQ(g.epoch, 1790835420u);
    const char *south = "+CGNSSINFO: 2,09,03,00,00,3352.128000,S,15112.558000,W,010126,000000.0,1,0,0";
    CHECK_EQ(rk_parse_cgnssinfo(south, &g), 0);
    CHECK(g.lat < 0 && g.lon < 0);
    const char *nofix = "+CGNSSINFO: ,,,,,,,,,,,,,,,";
    CHECK_EQ(rk_parse_cgnssinfo(nofix, &g), 0);
    CHECK(!g.fix);
    CHECK_EQ(rk_parse_cgnssinfo("OK", &g), -1);
    CHECK_EQ(rk_parse_cgnssinfo("+CGNSSINFO: 1,2,3", &g), -1);
    CHECK_EQ(rk_parse_cgnssinfo("+CGNSSINFO: 2,0,0,0,0,9999.0,N,99999.0,E,010126,000000.0,1,0,0", &g), -1); /* out of range */
    CHECK_EQ(rk_epoch_from_utc(1970, 1, 1, 0, 0, 0), 0);
    CHECK_EQ(rk_epoch_from_utc(2000, 3, 1, 0, 0, 0), 951868800u); /* leap-year handling */
    CHECK_EQ(rk_parse_csq("+CSQ: 18,99"), 18);
    CHECK_EQ(rk_parse_csq("+CSQ: 99,99"), -1);
    CHECK_EQ(rk_parse_csq("garbage"), -1);
    CHECK_EQ(rk_parse_cmqttpub("+CMQTTPUB: 0,0"), 1);
    CHECK_EQ(rk_parse_cmqttpub("+CMQTTPUB: 0,14"), 0);
    CHECK_EQ(rk_parse_cmqttpub("OK"), -1);
}

/* ---- clock ------------------------------------------------------------------------------------------------ */
static void test_tag_clock(void) {
    rk_clock_t c;
    rk_clock_init(&c, 1000);
    int valid;
    CHECK_EQ(rk_clock_ts(&c, 1300, &valid), 300);
    CHECK(!valid); /* unsynced: seconds since boot, flagged */
    uint32_t since_boot = rk_clock_sync(&c, 1791000300u, 1600);
    CHECK_EQ(since_boot, 600); /* goes into the TIME_SYNC event so the backend can re-base */
    CHECK_EQ(rk_clock_ts(&c, 1660, &valid), 1791000360u);
    CHECK(valid);
}

int main(void) {
    RUN(test_flap_matches_python);
    RUN(test_fan_matches_python_step_for_step);
    RUN(test_fan_ignores_out_of_order_and_alert_levels);
    RUN(test_ethylene_index_is_monotone_clamped_and_humidity_corrected);
    RUN(test_ble_batch_roundtrip_at_full_and_small_mtu);
    RUN(test_ble_rejects_inconsistent_batches);
    RUN(test_ble_ack_roundtrip_and_validation);
    RUN(test_command_parsing);
    RUN(test_command_ack_json_is_safe);
    RUN(test_gnss_and_modem_parsers);
    RUN(test_tag_clock);
    RK_TEST_MAIN_END("edge+misc");
}
