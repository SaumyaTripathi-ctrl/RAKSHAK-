/*
 * PLACEHOLDER calibration for the ethylene indicator strip. NOT MEASURED.
 *
 * TODO(lab): expose strips from one batch to known ethylene concentrations (reference: Winsen ME3-C2H4 in the
 * same chamber), record the TCS34725 blue/red ratio at each step and at 60/75/90 %RH, then replace this table and
 * rk_eth_default_humidity_factor(). Keep the table sorted by ratio.
 */
#ifndef RK_ETHYLENE_CAL_H
#define RK_ETHYLENE_CAL_H

#include "rk_ethylene.h"

#define RK_ETH_CAL_N 6
static const rk_eth_point_t RK_ETH_CAL[RK_ETH_CAL_N] = {
    {0.70f, 0.0f},   /* fresh strip, pale yellow          (placeholder) */
    {0.85f, 10.0f},  /*                                    (placeholder) */
    {1.00f, 25.0f},  /* yellow-green                       (placeholder) */
    {1.30f, 55.0f},  /*                                    (placeholder) */
    {1.80f, 85.0f},  /* blue                               (placeholder) */
    {2.40f, 100.0f}, /* saturated                          (placeholder) */
};

/* TODO(lab): measured reference humidity and slope. 60 %RH = no correction; +/-0.4 %/%RH is a guess. */
#define RK_ETH_RH_REF 60.0f
#define RK_ETH_RH_SLOPE 0.004f

#endif
