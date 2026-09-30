// SIMCom A7670C driver: network attach, GNSS fix + time, MQTT over TLS (QoS 1, persistent session, last-will).
//
//   *** NOT HARDWARE-TESTED. The AT sequences follow SIMCom's A76XX "AT Command Manual" / MQTT application note from
//   *** memory and have NOT been run against a real module: expect to adjust timeouts, the +CMQTT* syntax and the TLS
//   *** certificate upload on the first bring-up (see docs/LIMITATIONS.md and firmware/hub_esp32s3/README.md).
#pragma once
#include <Arduino.h>

extern "C" {
#include "rk_cmd.h"
}

typedef void (*modem_cmd_cb)(const char *payload, size_t len);

struct MqttConfig {
    const char *host;
    uint16_t port;
    const char *client_id;
    const char *user;
    const char *pass;
    const char *will_topic;
    const char *will_msg;
    const char *sub_topic;
    bool tls;
};

void modem_begin_uart();
bool modem_power_on();                 // PWRKEY pulse + AT handshake
bool modem_attach(const char *apn);    // SIM ready, PS attach, PDP context
int modem_csq();                       // 0..31 or -1
bool modem_gnss(rk_gnss_t *out, uint32_t timeout_s);
bool modem_upload_ca(const char *pem); // writes ca.pem to the module's filesystem (needed once, for TLS)
bool modem_mqtt_connect(const MqttConfig &cfg, modem_cmd_cb on_cmd);
void modem_mqtt_disconnect();
bool modem_mqtt_connected();
// Publish and wait for the PUBACK URC. The caller removes the record from its ring only on true.
bool modem_publish(const char *topic, const uint8_t *payload, size_t len, uint8_t qos = 1);
void modem_poll(uint32_t ms);          // pump URCs (incoming commands, connection loss)
