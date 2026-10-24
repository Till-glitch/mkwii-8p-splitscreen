// SPDX-License-Identifier: GPL-3.0-or-later
// Make the working reference's controller resource configuration reproducible
// without patching the shared PlatformIO framework archive.
#include <stddef.h>
#include <esp_bt.h>

static_assert(offsetof(esp_bt_controller_config_t, ble_max_conn) == 0x15,
              "Recheck controller configuration against the pinned ESP-IDF headers.");
static_assert(offsetof(esp_bt_controller_config_t, bt_max_acl_conn) == 0x16,
              "Recheck controller configuration against the pinned ESP-IDF headers.");

extern "C" esp_err_t __real_esp_bt_controller_init(esp_bt_controller_config_t* config);

extern "C" esp_err_t __wrap_esp_bt_controller_init(esp_bt_controller_config_t* config) {
    if (config == nullptr) return __real_esp_bt_controller_init(config);
    esp_bt_controller_config_t bridgeConfig = *config;
    // The unmodified framework reserves only two BR/EDR ACL connections. The
    // accepted old installation changed BLE 3->1 and BR/EDR 2->7 in libbtstack.a.
    // Reserve the same resources here; firmware still accepts exactly 4 devices.
    bridgeConfig.ble_max_conn = 1;
    bridgeConfig.bt_max_acl_conn = 7;
    return __real_esp_bt_controller_init(&bridgeConfig);
}
