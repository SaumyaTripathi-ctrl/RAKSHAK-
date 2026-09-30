#include "actuators.h"

#include "config.h"

static constexpr uint32_t SERVO_HZ = 50, SERVO_BITS = 14;

void actuators_begin() {
    pinMode(PIN_FAN, OUTPUT);
    digitalWrite(PIN_FAN, LOW);
    pinMode(PIN_BUZZER, OUTPUT);
    digitalWrite(PIN_BUZZER, LOW);
    pinMode(PIN_LED_GREEN, OUTPUT);
    pinMode(PIN_LED_BLUE, OUTPUT);
    pinMode(PIN_LED_RED, OUTPUT);
    ledcAttach(PIN_SERVO, SERVO_HZ, SERVO_BITS);
    flap_set(0);
}

void flap_set(int pct) {
    pct = constrain(pct, 0, 100);
    uint32_t us = 500 + (uint32_t)pct * 10; // 100 % = 90 degrees = 1.5 ms
    ledcWrite(PIN_SERVO, (us * (1u << SERVO_BITS)) / 20000u);
}

void fan_set(bool on) { digitalWrite(PIN_FAN, on ? HIGH : LOW); }

void indicate(int tier, bool buzzer_latched) {
    digitalWrite(PIN_LED_GREEN, tier == 0);
    digitalWrite(PIN_LED_BLUE, tier == 1);
    digitalWrite(PIN_LED_RED, tier >= 2);
    digitalWrite(PIN_BUZZER, buzzer_latched ? HIGH : LOW);
}
