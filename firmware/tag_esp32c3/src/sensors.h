#pragma once
#include <Arduino.h>

struct TH {
    float temp_c = NAN;
    float rh_pct = NAN;
    bool ok = false;
};

bool sensors_begin();
TH sensors_read_th();                            // SHT31
float sensors_read_ethylene_index(float rh_pct); // TCS34725 + strip; LED on only while sampling. NAN on failure
uint8_t sensors_battery_pct();
bool sensors_lid_open();                         // reed switch (open circuit = lid opened)
