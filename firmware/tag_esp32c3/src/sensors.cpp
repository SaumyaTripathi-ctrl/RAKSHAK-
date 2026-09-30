#include "sensors.h"

#include <Adafruit_SHT31.h>
#include <Adafruit_TCS34725.h>
#include <Wire.h>

#include "config.h"

extern "C" {
#include "rk_ethylene.h"
}

static Adafruit_SHT31 sht;
static Adafruit_TCS34725 tcs(TCS34725_INTEGRATIONTIME_50MS, TCS34725_GAIN_4X);
static bool have_sht = false, have_tcs = false;

bool sensors_begin() {
    Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);
    pinMode(PIN_TCS_LED, OUTPUT);
    digitalWrite(PIN_TCS_LED, LOW);
    pinMode(PIN_REED, INPUT_PULLUP);
    analogReadResolution(12);
    have_sht = sht.begin(0x44);
    have_tcs = tcs.begin();
    return have_sht; // the strip is optional (milk has none); temperature/humidity are not
}

TH sensors_read_th() {
    TH r;
    if (!have_sht) return r;
    float t = sht.readTemperature(), h = sht.readHumidity();
    if (isnan(t) || isnan(h)) return r;
    r.temp_c = t;
    r.rh_pct = constrain(h, 0.0f, 100.0f);
    r.ok = true;
    return r;
}

float sensors_read_ethylene_index(float rh_pct) {
    if (!have_tcs) return NAN;
    digitalWrite(PIN_TCS_LED, HIGH); // illuminate the strip only while sampling (saves power, stabilises colour)
    delay(STRIP_SETTLE_MS);
    uint16_t r, g, b, c;
    tcs.getRawData(&r, &g, &b, &c);
    digitalWrite(PIN_TCS_LED, LOW);
    return rk_ethylene_index(r, g, b, c, isnan(rh_pct) ? 60.0f : rh_pct, nullptr);
}

uint8_t sensors_battery_pct() {
    uint32_t mv = 0;
    for (int i = 0; i < 8; i++) mv += analogReadMilliVolts(PIN_BATT_ADC);
    float v = (mv / 8.0f) / 1000.0f * BATT_DIVIDER;
    float pct = (v - 3.30f) / (4.15f - 3.30f) * 100.0f; // crude Li-ion curve (TODO: measure on the prototype)
    return (uint8_t)constrain((int)pct, 0, 100);
}

bool sensors_lid_open() { return digitalRead(PIN_REED) == HIGH; }
