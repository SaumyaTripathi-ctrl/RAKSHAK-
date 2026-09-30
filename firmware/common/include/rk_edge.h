/*
 * Hub edge rules: run with NO network. Mirrors rakshak_ml/edge.py and the simulator; `tools/gen_edge_vectors.py`
 * generates vectors from the Python version and firmware/common/test/test_edge.c checks this implementation
 * against them. Thresholds are illustrative starting values (tuned per crop in the pilot) and live in
 * firmware/hub_esp32s3/src/config.h.
 */
#ifndef RK_EDGE_H
#define RK_EDGE_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* dT = crate_temp - upper_limit: <=0 -> 0 %, <1.5 -> 25 %, <3 -> 50 %, else 100 %. */
int rk_flap_for_deviation(double temp_c, double upper_limit_c, double t0, double t1, double t2);

#define RK_FAN_MAX_POINTS 16

typedef struct {
    double rise_per_min;        /* fan ON when the index rises faster than this (default 0.12) */
    double stable_eps_per_min;  /* "not rising" threshold (default 0.06) */
    double stable_min;          /* minutes not rising before OFF (default 30) */
    double window_min;          /* slope window (default 30) */
    int min_points;             /* no decision on fewer points (default 5) */
    int confirm;                /* consecutive rising evaluations to switch on (default 2) */
    /* state */
    int fan_on;
    int above;
    int n;
    double t[RK_FAN_MAX_POINTS];
    double v[RK_FAN_MAX_POINTS];
    double stable_since;
    int stable_active;
} rk_fan_t;

void rk_fan_init(rk_fan_t *f);
/* Feed one strip reading; returns the fan state. `t_min` in minutes (monotonic). */
int rk_fan_update(rk_fan_t *f, double t_min, double ethylene_idx);

/* Alert tier from crate deviation above the upper limit: 0 SAFE, 1 WARNING (>=3 C), 2 CRITICAL (>=6 C). */
int rk_edge_alert_level(double temp_c, double upper_limit_c);

#ifdef __cplusplus
}
#endif
#endif
