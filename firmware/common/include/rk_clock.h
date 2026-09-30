/*
 * Tag clock: epoch time if synced by the hub, otherwise monotonic seconds since (re)boot with ts_valid = 0.
 * The hub's ACK carries GNSS time; `rk_clock_sync` then yields the TIME_SYNC event arguments (epoch + monotonic
 * seconds at that instant) that let the backend re-base every unsynced timestamp (RECORD_SPEC.md section 6).
 */
#ifndef RK_CLOCK_H
#define RK_CLOCK_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    int synced;
    int64_t offset; /* epoch - mono, valid when synced */
    uint32_t boot_mono; /* monotonic seconds at (re)boot: origin of unsynced timestamps */
} rk_clock_t;

void rk_clock_init(rk_clock_t *c, uint32_t boot_mono_s);
/* Timestamp for a record taken at monotonic time `mono_s`. */
uint32_t rk_clock_ts(const rk_clock_t *c, uint32_t mono_s, int *ts_valid);
/* Apply a hub time; returns the monotonic seconds (since boot) to put into the TIME_SYNC event's arg0|arg1<<16. */
uint32_t rk_clock_sync(rk_clock_t *c, uint32_t epoch_s, uint32_t mono_s);

#ifdef __cplusplus
}
#endif
#endif
