#include "rk_ethylene.h"

#include "rk_ethylene_cal.h"

float rk_eth_interp(const rk_eth_point_t *t, int n, float ratio) {
    if (n <= 0) return 0.0f;
    if (ratio <= t[0].ratio) return t[0].index;
    if (ratio >= t[n - 1].ratio) return t[n - 1].index;
    for (int i = 1; i < n; i++) {
        if (ratio <= t[i].ratio) {
            float span = t[i].ratio - t[i - 1].ratio;
            float f = span > 0 ? (ratio - t[i - 1].ratio) / span : 0.0f;
            return t[i - 1].index + f * (t[i].index - t[i - 1].index);
        }
    }
    return t[n - 1].index;
}

float rk_eth_default_humidity_factor(float rh_pct) {
    /* Placeholder: a humid strip reads slightly "bluer", so scale down when above the reference humidity. */
    float f = 1.0f - RK_ETH_RH_SLOPE * (rh_pct - RK_ETH_RH_REF);
    return f < 0.5f ? 0.5f : (f > 1.5f ? 1.5f : f);
}

float rk_ethylene_index(uint16_t r, uint16_t g, uint16_t b, uint16_t c, float rh_pct, rk_eth_humidity_fn humidity) {
    (void)g;
    (void)c;
    if (r == 0) return 0.0f; /* sensor saturated/dark: no reading */
    float ratio = (float)b / (float)r;
    float idx = rk_eth_interp(RK_ETH_CAL, RK_ETH_CAL_N, ratio);
    float corr = humidity ? humidity(rh_pct) : rk_eth_default_humidity_factor(rh_pct);
    idx *= corr;
    return idx < 0.0f ? 0.0f : (idx > 100.0f ? 100.0f : idx);
}
