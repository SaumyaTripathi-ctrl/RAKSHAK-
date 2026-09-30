# Device key provisioning (spec v1)

1. Generate / hold the **master key** on the backend only (`RAKSHAK_MASTER_KEY_HEX`).
2. For each device derive `device_key = HKDF-SHA256(master, "rakshak-v1|<device_id>|<key_epoch>")`
   (`rakshak.codec.derive_device_key`, `rk_derive_device_key`).
3. Write `device_id`, `key_epoch` and `device_key` into the device's NVS partition **before** enabling ESP32
   flash encryption + secure boot (otherwise the key is readable from flash). Set `seq = 0`.
4. Re-provisioning (key suspected exposed, device re-flashed): increment `key_epoch`, derive a new key, keep `seq`
   monotonic. The backend picks the key from the frame header, so old frames still decrypt with the old epoch.

Flash encryption + secure boot raise the cost of key extraction; the ESP32 has no secure element (see LIMITATIONS).
Hardware-specific steps are filled in during Phase 7.
