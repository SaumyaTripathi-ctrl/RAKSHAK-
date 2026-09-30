#include "rk_clock.h"

void rk_clock_init(rk_clock_t *c, uint32_t boot_mono_s) {
    c->synced = 0;
    c->offset = 0;
    c->boot_mono = boot_mono_s;
}

uint32_t rk_clock_ts(const rk_clock_t *c, uint32_t mono_s, int *ts_valid) {
    if (c->synced) {
        *ts_valid = 1;
        return (uint32_t)((int64_t)mono_s + c->offset);
    }
    *ts_valid = 0;
    return mono_s - c->boot_mono;
}

uint32_t rk_clock_sync(rk_clock_t *c, uint32_t epoch_s, uint32_t mono_s) {
    uint32_t since_boot = mono_s - c->boot_mono;
    c->offset = (int64_t)epoch_s - (int64_t)mono_s;
    c->synced = 1;
    return since_boot;
}
