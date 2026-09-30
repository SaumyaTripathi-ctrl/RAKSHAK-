// Rakshak Tag (ESP32-C3 SuperMini) - pin map and constants.  *** NOT HARDWARE-TESTED (compile-tested only) ***
#pragma once

// ---- pins (ESP32-C3 SuperMini defaults; change to match your PCB) -------------------------------------------
#define PIN_I2C_SDA 8        // SHT31 (0x44) + TCS34725 (0x29) share the bus
#define PIN_I2C_SCL 9
#define PIN_TCS_LED 3        // TCS34725 illumination LED: ON only while sampling the strip
#define PIN_REED 4           // lid reed switch to GND, internal pull-up; RTC-capable (GPIO0-5) so it can wake us
#define PIN_LED 10           // status LED (lid-open / low-battery blink)
#define PIN_BATT_ADC 1       // 18650 through a 1:2 divider (2 x 100 k)
#define BATT_DIVIDER 2.0f

// ---- timing ---------------------------------------------------------------------------------------------------
#define SAMPLE_PERIOD_S 60       // wake every minute: SHT31 + reed
#define STRIP_EVERY_WAKES 5      // read the ethylene strip every 5 minutes
#define BLE_EVERY_WAKES 5        // offer the batch to the hub every 5 minutes
#define BLE_WINDOW_MS 6000       // how long we advertise waiting for the hub
#define STRIP_SETTLE_MS 120      // LED on -> reading settled (TCS34725 integration time)
#define BATCH_MAX_FRAMES 32      // frames per BLE batch (<= RK_BLE_MAX_BATCH)
#define BLE_MTU 247

// ---- storage ----------------------------------------------------------------------------------------------------
#define RING_SECTOR 4096
#define RING_SLOTS 1012          // 44 sectors x 23 slots x 176 B: ~17 h at one record per minute (raw "spiffs" partition)
#define NVS_NS "rakshak"

// ---- power ------------------------------------------------------------------------------------------------------
#define LOW_BATT_PCT 15

// ---- BLE UUIDs (shared with the hub) -----------------------------------------------------------------------
#define RK_SERVICE_UUID "5a1d0000-7261-6b73-6861-6b2d74616721"
#define RK_CHAR_FRAMES "5a1d0001-7261-6b73-6861-6b2d74616721" // notify: frame fragments + END
#define RK_CHAR_ACK "5a1d0002-7261-6b73-6861-6b2d74616721"    // write:  ACK from the hub
#define RK_CHAR_PAIR "5a1d0003-7261-6b73-6861-6b2d74616721"   // write:  [0x20][shipment_id 16][epoch u32]
