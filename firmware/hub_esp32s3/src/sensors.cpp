#include "sensors.h"

#include <Adafruit_SHT31.h>
#include <Wire.h>

#include "config.h"

static Adafruit_SHT31 sht;
static bool have_sht = false, have_mpu = false;

static constexpr uint8_t MPU_ADDR = 0x68;

static bool mpu_write(uint8_t reg, uint8_t val) {
    Wire.beginTransmission(MPU_ADDR);
    Wire.write(reg);
    Wire.write(val);
    return Wire.endTransmission() == 0;
}

// Raw accelerometer read (registers 0x3B..0x40, big-endian, 16384 LSB/g at +-2 g).
static bool mpu_accel(float *ax, float *ay, float *az) {
    Wire.beginTransmission(MPU_ADDR);
    Wire.write(0x3B);
    if (Wire.endTransmission(false) != 0) return false;
    if (Wire.requestFrom((int)MPU_ADDR, 6) != 6) return false;
    int16_t x = (int16_t)((Wire.read() << 8) | Wire.read());
    int16_t y = (int16_t)((Wire.read() << 8) | Wire.read());
    int16_t z = (int16_t)((Wire.read() << 8) | Wire.read());
    *ax = x / 16384.0f;
    *ay = y / 16384.0f;
    *az = z / 16384.0f;
    return true;
}

bool sensors_begin() {
    Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);
    pinMode(PIN_REED, INPUT_PULLUP);
    analogReadResolution(12);
    have_sht = sht.begin(0x44);
    have_mpu = mpu_write(0x6B, 0x00) && mpu_write(0x1C, 0x00); // wake, +-2 g full scale
    return have_sht;
}

HubTH sensors_read_th() {
    HubTH r;
    if (!have_sht) return r;
    float t = sht.readTemperature(), h = sht.readHumidity();
    if (isnan(t) || isnan(h)) return r;
    r.temp_c = t;
    r.rh_pct = constrain(h, 0.0f, 100.0f);
    r.ok = true;
    return r;
}

float sensors_shock_peak_g() {
    if (!have_mpu) return 0.0f;
    float peak = 0;
    for (int i = 0; i < 30; i++) { // 30 reads ~ 60 ms
        float x, y, z;
        if (mpu_accel(&x, &y, &z)) peak = max(peak, sqrtf(x * x + y * y + z * z));
        delay(2);
    }
    return peak; // ~1.0 at rest; the +-2 g range clips larger shocks (TODO: +-8 g range for real road shocks)
}

bool sensors_lid_open() { return digitalRead(PIN_REED) == HIGH; }

uint8_t sensors_battery_pct() {
    uint32_t mv = 0;
    for (int i = 0; i < 8; i++) mv += analogReadMilliVolts(PIN_BATT_ADC);
    float v = (mv / 8.0f) / 1000.0f * BATT_DIVIDER;
    return (uint8_t)constrain((int)((v - 3.30f) / (4.15f - 3.30f) * 100.0f), 0, 100);
}
