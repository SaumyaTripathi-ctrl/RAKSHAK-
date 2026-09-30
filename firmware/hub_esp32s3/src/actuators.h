#pragma once
#include <Arduino.h>

void actuators_begin();
void flap_set(int pct);  // 0 / 25 / 50 / 100 -> SG90 angle via LEDC (20 ms period, 0.5-1.5 ms pulse)
void fan_set(bool on);
// LED tier: 0 green (SAFE), 1 blue (WARNING), 2 red (CRITICAL). Buzzer: latched until acknowledged.
void indicate(int tier, bool buzzer_latched);
