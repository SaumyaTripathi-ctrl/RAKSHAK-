#include "rk_cmd.h"

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* ---- JSON (flat object, string / integer / null values only) -------------------------------------------------- */

static const char *skip_ws(const char *p, const char *end) {
    while (p < end && (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n')) p++;
    return p;
}

/* Parses "string" into out (NUL-terminated, truncated to cap-1). Returns pointer past the closing quote or NULL. */
static const char *parse_string(const char *p, const char *end, char *out, size_t cap) {
    if (p >= end || *p != '"') return NULL;
    p++;
    size_t n = 0;
    while (p < end && *p != '"') {
        if (*p == '\\') { /* only plain escapes are accepted; \uXXXX is rejected (commands are ASCII) */
            p++;
            if (p >= end) return NULL;
            if (*p != '"' && *p != '\\' && *p != '/' && *p != 'n' && *p != 't') return NULL;
        }
        if (out && n + 1 < cap) out[n++] = *p;
        p++;
    }
    if (p >= end) return NULL;
    if (out && cap) out[n < cap ? n : cap - 1] = '\0';
    return p + 1;
}

/* Skips any JSON value (string, number, true/false/null); nested objects/arrays are rejected. */
static const char *skip_value(const char *p, const char *end) {
    if (p >= end) return NULL;
    if (*p == '"') return parse_string(p, end, NULL, 0);
    if (*p == '{' || *p == '[') return NULL;
    while (p < end && *p != ',' && *p != '}' && !isspace((unsigned char)*p)) p++;
    return p;
}

int rk_cmd_parse(const char *json, size_t len, rk_cmd_t *out) {
    if (!json || !out || len < 2 || len > 512) return -1;
    memset(out, 0, sizeof *out);
    const char *p = json, *end = json + len;
    p = skip_ws(p, end);
    if (p >= end || *p != '{') return -1;
    p++;
    char cmd[24] = "";
    int have_cmd = 0;
    for (;;) {
        p = skip_ws(p, end);
        if (p >= end) return -1;
        if (*p == '}') break;
        char key[16];
        p = parse_string(p, end, key, sizeof key);
        if (!p) return -1;
        p = skip_ws(p, end);
        if (p >= end || *p != ':') return -1;
        p = skip_ws(p + 1, end);
        if (strcmp(key, "cmd") == 0) {
            p = parse_string(p, end, cmd, sizeof cmd);
            if (!p) return -1;
            have_cmd = 1;
        } else if (strcmp(key, "id") == 0) {
            p = parse_string(p, end, out->id, sizeof out->id);
            if (!p) return -1;
        } else if (strcmp(key, "arg") == 0) {
            if (end - p >= 4 && strncmp(p, "null", 4) == 0) {
                p += 4;
            } else {
                char *num_end;
                char tmp[16];
                size_t n = 0;
                const char *q = p;
                while (q < end && n < sizeof tmp - 1 && (isdigit((unsigned char)*q) || *q == '-')) tmp[n++] = *q++;
                tmp[n] = '\0';
                if (n == 0) return -1;
                long v = strtol(tmp, &num_end, 10);
                if (*num_end != '\0') return -1;
                out->has_arg = 1;
                out->arg = (int)v;
                p = q;
            }
        } else {
            p = skip_value(p, end);
            if (!p) return -1;
        }
        p = skip_ws(p, end);
        if (p < end && *p == ',') p++;
    }
    if (!have_cmd) return -1;

    if (!strcmp(cmd, "FLAP_SET")) out->kind = RK_CMD_FLAP_SET;
    else if (!strcmp(cmd, "FAN_ON")) out->kind = RK_CMD_FAN_ON;
    else if (!strcmp(cmd, "FAN_OFF")) out->kind = RK_CMD_FAN_OFF;
    else if (!strcmp(cmd, "ALERT_WARNING")) out->kind = RK_CMD_ALERT_WARNING;
    else if (!strcmp(cmd, "ALERT_CRITICAL")) out->kind = RK_CMD_ALERT_CRITICAL;
    else if (!strcmp(cmd, "ALERT_CLEAR")) out->kind = RK_CMD_ALERT_CLEAR;
    else if (!strcmp(cmd, "ACK_ALERT")) out->kind = RK_CMD_ACK_ALERT;
    else out->kind = RK_CMD_UNKNOWN;

    if (out->kind == RK_CMD_FLAP_SET) {
        if (!out->has_arg || (out->arg != 0 && out->arg != 25 && out->arg != 50 && out->arg != 100)) out->kind = RK_CMD_UNKNOWN;
    }
    return 0;
}

size_t rk_cmd_ack_json(char *out, size_t cap, const char *id, int ok) {
    /* id is copied only if it is printable and free of quotes/backslashes (it came from the network) */
    char safe[40];
    size_t n = 0;
    for (const char *s = id ? id : ""; *s && n < sizeof safe - 1; s++)
        if ((unsigned char)*s >= 0x20 && (unsigned char)*s < 0x7f && *s != '"' && *s != '\\') safe[n++] = *s;
    safe[n] = '\0';
    int w = snprintf(out, cap, "{\"type\":\"cmd_ack\",\"id\":\"%s\",\"ok\":%s}", safe, ok ? "true" : "false");
    return (w < 0 || (size_t)w >= cap) ? 0 : (size_t)w;
}

/* ---- AT parsers ------------------------------------------------------------------------------------------------ */

uint32_t rk_epoch_from_utc(int y, int m, int d, int hh, int mm, int ss) {
    /* Howard Hinnant's days_from_civil */
    y -= m <= 2;
    int era = (y >= 0 ? y : y - 399) / 400;
    unsigned yoe = (unsigned)(y - era * 400);
    unsigned doy = (unsigned)((153 * (m + (m > 2 ? -3 : 9)) + 2) / 5 + d - 1);
    unsigned doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    long days = (long)era * 146097 + (long)doe - 719468;
    return (uint32_t)(days * 86400L + hh * 3600L + mm * 60L + ss);
}

/* Splits `s` at commas in place into up to `max` fields. */
static int split_csv(char *s, char **f, int max) {
    int n = 0;
    f[n++] = s;
    for (char *p = s; *p && n < max; p++)
        if (*p == ',') {
            *p = '\0';
            f[n++] = p + 1;
        }
    return n;
}

/* +CGNSSINFO: <mode>,<gps>,<glonass>,<bd>,<gal>,<lat>,<N/S>,<lon>,<E/W>,<date ddmmyy>,<utc hhmmss.s>,<alt>,<speed>,<course>...
 * (field order per the SIMCom A76xx GNSS AT manual; verify against your module firmware.) */
int rk_parse_cgnssinfo(const char *line, rk_gnss_t *out) {
    memset(out, 0, sizeof *out);
    const char *tag = "+CGNSSINFO:";
    while (*line == ' ') line++;
    if (strncmp(line, tag, strlen(tag)) != 0) return -1;
    char buf[200];
    size_t n = strlen(line + strlen(tag));
    if (n >= sizeof buf) return -1;
    memcpy(buf, line + strlen(tag), n + 1);
    char *f[16];
    int cnt = split_csv(buf, f, 16);
    if (cnt < 11) return -1;
    char *lat_s = f[5], *lon_s = f[7];
    if (!*lat_s || !*lon_s) return 0; /* no fix yet: fields are empty */
    double lat_raw = atof(lat_s), lon_raw = atof(lon_s); /* ddmm.mmmmmm / dddmm.mmmmmm */
    int lat_deg = (int)(lat_raw / 100), lon_deg = (int)(lon_raw / 100);
    double lat = lat_deg + (lat_raw - lat_deg * 100) / 60.0;
    double lon = lon_deg + (lon_raw - lon_deg * 100) / 60.0;
    if (f[6][0] == 'S') lat = -lat;
    if (f[8][0] == 'W') lon = -lon;
    if (lat < -90 || lat > 90 || lon < -180 || lon > 180) return -1;
    out->fix = 1;
    out->lat = lat;
    out->lon = lon;
    const char *date = f[9], *utc = f[10]; /* ddmmyy, hhmmss.s */
    if (strlen(date) >= 6 && strlen(utc) >= 6) {
        int dd = (date[0] - '0') * 10 + (date[1] - '0'), mo = (date[2] - '0') * 10 + (date[3] - '0');
        int yy = 2000 + (date[4] - '0') * 10 + (date[5] - '0');
        int hh = (utc[0] - '0') * 10 + (utc[1] - '0'), mi = (utc[2] - '0') * 10 + (utc[3] - '0');
        int ss = (utc[4] - '0') * 10 + (utc[5] - '0');
        if (dd >= 1 && dd <= 31 && mo >= 1 && mo <= 12 && hh < 24 && mi < 60 && ss < 61) out->epoch = rk_epoch_from_utc(yy, mo, dd, hh, mi, ss);
    }
    return 0;
}

int rk_parse_csq(const char *line) {
    while (*line == ' ') line++;
    if (strncmp(line, "+CSQ:", 5) != 0) return -1;
    int rssi = atoi(line + 5);
    return (rssi >= 0 && rssi <= 31) ? rssi : -1; /* 99 = unknown */
}

int rk_parse_cmqttpub(const char *line) {
    while (*line == ' ') line++;
    if (strncmp(line, "+CMQTTPUB:", 10) != 0) return -1;
    const char *comma = strchr(line, ',');
    if (!comma) return -1;
    return atoi(comma + 1) == 0 ? 1 : 0;
}
