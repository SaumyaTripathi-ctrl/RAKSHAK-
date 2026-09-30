/*
 * Ethylene indicator strip -> index 0..100 %.
 *
 * The TCS34725 reads the strip (pale yellow -> blue as it absorbs ethylene). The blue/red ratio is mapped to an
 * index through a calibration table (rk_ethylene_cal.h), then corrected for humidity.
 *
 * *** CALIBRATION IS PLACEHOLDER. *** The table and the humidity factor are NOT measured: each strip batch must
 * be calibrated once in the lab against a reference sensor (Winsen ME3-C2H4) - see docs/LIMITATIONS.md.
 */
#ifndef RK_ETHYLENE_H
#define RK_ETHYLENE_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    float ratio; /* blue / red of the strip */
    float index; /* ethylene exposure index, 0..100 */
} rk_eth_point_t;

/* Linear interpolation over a table sorted by ratio; clamped to the first/last index. */
float rk_eth_interp(const rk_eth_point_t *table, int n, float ratio);

/* Hook: multiplicative humidity correction (1.0 = none). Default: rk_eth_default_humidity_factor. */
typedef float (*rk_eth_humidity_fn)(float rh_pct);
float rk_eth_default_humidity_factor(float rh_pct);

/* Raw clear/red/green/blue counts -> corrected index (0..100). `humidity` may be NULL (uses the default). */
float rk_ethylene_index(uint16_t r, uint16_t g, uint16_t b, uint16_t c, float rh_pct, rk_eth_humidity_fn humidity);

#ifdef __cplusplus
}
#endif
#endif
