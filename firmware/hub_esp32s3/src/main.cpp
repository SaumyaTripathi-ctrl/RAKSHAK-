// Rakshak Hub skeleton (Phase 1): proves firmware/common builds for the target. Real firmware: Phase 7.
#include <Arduino.h>

#include "rk_codec.h"

void setup() {
    Serial.begin(115200);
    Serial.printf("Rakshak Hub skeleton, hub frame = %u bytes\n", (unsigned)rk_frame_len(RK_TYPE_HUB_SAMPLE));
}

void loop() { delay(1000); }
