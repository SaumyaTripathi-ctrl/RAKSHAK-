#include "rk_edge.h"

#include <string.h>

int rk_flap_for_deviation(double temp_c, double upper_limit_c, double t0, double t1, double t2) {
    double d = temp_c - upper_limit_c;
    if (d <= t0) return 0;
    if (d < t1) return 25;
    if (d < t2) return 50;
    return 100;
}

void rk_fan_init(rk_fan_t *f) {
    memset(f, 0, sizeof *f);
    f->rise_per_min = 0.12;
    f->stable_eps_per_min = 0.06;
    f->stable_min = 30.0;
    f->window_min = 30.0;
    f->min_points = 5;
    f->confirm = 2;
}

/* Least-squares slope over the window; returns 0 and sets *ok=0 when there are too few points. */
static double slope(const rk_fan_t *f, int *ok) {
    if (f->n < f->min_points || f->n < 2) {
        *ok = 0;
        return 0.0;
    }
    double mt = 0, mv = 0;
    for (int i = 0; i < f->n; i++) {
        mt += f->t[i];
        mv += f->v[i];
    }
    mt /= f->n;
    mv /= f->n;
    double num = 0, den = 0;
    for (int i = 0; i < f->n; i++) {
        num += (f->t[i] - mt) * (f->v[i] - mv);
        den += (f->t[i] - mt) * (f->t[i] - mt);
    }
    if (den == 0.0) {
        *ok = 0;
        return 0.0;
    }
    *ok = 1;
    return num / den;
}

int rk_fan_update(rk_fan_t *f, double t_min, double idx) {
    if (f->n > 0 && t_min <= f->t[f->n - 1]) return f->fan_on; /* out-of-order / duplicate: ignore */
    /* append, then drop points older than the window (and keep the buffer bounded) */
    if (f->n == RK_FAN_MAX_POINTS) {
        memmove(f->t, f->t + 1, sizeof(double) * (RK_FAN_MAX_POINTS - 1));
        memmove(f->v, f->v + 1, sizeof(double) * (RK_FAN_MAX_POINTS - 1));
        f->n--;
    }
    f->t[f->n] = t_min;
    f->v[f->n] = idx;
    f->n++;
    int keep_from = 0;
    while (keep_from < f->n && t_min - f->t[keep_from] > f->window_min + 1e-9) keep_from++;
    if (keep_from > 0) {
        memmove(f->t, f->t + keep_from, sizeof(double) * (f->n - keep_from));
        memmove(f->v, f->v + keep_from, sizeof(double) * (f->n - keep_from));
        f->n -= keep_from;
    }

    int ok;
    double rate = slope(f, &ok);
    if (!ok) return f->fan_on;
    f->above = rate > f->rise_per_min ? f->above + 1 : 0;
    if (f->above >= f->confirm) {
        f->fan_on = 1;
        f->stable_active = 0;
    } else if (f->fan_on && f->above == 0) {
        if (rate <= f->stable_eps_per_min) {
            if (!f->stable_active) {
                f->stable_active = 1;
                f->stable_since = t_min;
            }
            if (t_min - f->stable_since >= f->stable_min) {
                f->fan_on = 0;
                f->stable_active = 0;
            }
        } else {
            f->stable_active = 0;
        }
    }
    return f->fan_on;
}

int rk_edge_alert_level(double temp_c, double upper_limit_c) {
    double d = temp_c - upper_limit_c;
    return d >= 6.0 ? 2 : d >= 3.0 ? 1 : 0;
}
