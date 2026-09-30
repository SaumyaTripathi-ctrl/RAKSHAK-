#pragma once
#include <Arduino.h>

struct HubTH {
    float temp_c = NAN;
    float rh_pct = NAN;
    bool ok = false;
};

bool sensors_begin();
HubTH sensors_read_th();       // SHT31 (hub enclosure / cabin)
float sensors_shock_peak_g();  // peak |accel| over a ~60 ms burst (MPU6050, +-2 g range, own driver)
bool sensors_lid_open();       // reed switch
uint8_t sensors_battery_pct();
