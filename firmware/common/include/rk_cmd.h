/*
 * Hub command parsing (MQTT rakshak/{hub}/cmd, JSON) and modem response parsing (A7670C AT).
 * Tiny, allocation-free, bounds-checked: these parse untrusted input from the network / the modem.
 */
#ifndef RK_CMD_H
#define RK_CMD_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    RK_CMD_NONE = 0,
    RK_CMD_FLAP_SET,
    RK_CMD_FAN_ON,
    RK_CMD_FAN_OFF,
    RK_CMD_ALERT_WARNING,
    RK_CMD_ALERT_CRITICAL,
    RK_CMD_ALERT_CLEAR,
    RK_CMD_ACK_ALERT,
    RK_CMD_UNKNOWN,
} rk_cmd_kind_t;

typedef struct {
    rk_cmd_kind_t kind;
    int has_arg;
    int arg;
    char id[40];
} rk_cmd_t;

/* Parse {"id":"...","cmd":"FLAP_SET","arg":50,...}. Returns 0 if it is a well-formed command object (kind may be
 * RK_CMD_UNKNOWN for an unrecognised name - still acknowledged with ok:false), -1 if it is not usable. A FLAP_SET
 * whose arg is not one of 0/25/50/100 becomes RK_CMD_UNKNOWN. */
int rk_cmd_parse(const char *json, size_t len, rk_cmd_t *out);

/* Build the ack: {"type":"cmd_ack","id":"...","ok":true}. Returns length, or 0 if `cap` is too small. */
size_t rk_cmd_ack_json(char *out, size_t cap, const char *id, int ok);

/* ---- A7670C AT response parsers ---------------------------------------------------------------------------- */

typedef struct {
    int fix;            /* 1 if the modem reports a fix */
    double lat, lon;    /* decimal degrees, signed */
    uint32_t epoch;     /* UTC seconds since 1970 from the GNSS date/time (0 if unavailable) */
} rk_gnss_t;

/* Parse one "+CGNSSINFO: ..." line. Returns 0 on success (fix may be 0 when the fields are empty). */
int rk_parse_cgnssinfo(const char *line, rk_gnss_t *out);

/* "+CSQ: 18,99" -> RSSI index (0..31), or -1 if unknown/invalid. */
int rk_parse_csq(const char *line);

/* "+CMQTTPUB: 0,0" -> 1 when the publish was acknowledged (error code 0), 0 otherwise, -1 if not that URC. */
int rk_parse_cmqttpub(const char *line);

/* days-from-civil based UTC conversion (no libc time zone dependency). */
uint32_t rk_epoch_from_utc(int year, int mon, int day, int hh, int mm, int ss);

#ifdef __cplusplus
}
#endif
#endif
