// MicroPython C-Modul (USER_C_MODULES) — startet Core 1 via MicroPython-Thread
#include "py/runtime.h"
#include "py/mpthread.h"
#include "pwmfb_core1_shared.h"
#include "pwmfb_core1_task.h"

// get_raw() → (high_us, low_us, age_us)
static mp_obj_t mp_c1_get_raw(void) {
    uint32_t now = (*(volatile uint32_t*)0x4005400Cu);
    mp_obj_t items[3] = {
        mp_obj_new_int(g_pwmfb.high_us),
        mp_obj_new_int(g_pwmfb.low_us),
        mp_obj_new_int(now - g_pwmfb.last_upd),
    };
    return mp_obj_new_tuple(3, items);
}
static MP_DEFINE_CONST_FUN_OBJ_0(mp_c1_get_raw_obj, mp_c1_get_raw);

// get_health() → (poll_count, edge_count, debounce_drop, ready)
static mp_obj_t mp_c1_get_health(void) {
    mp_obj_t items[4] = {
        mp_obj_new_int(g_pwmfb.poll_count),
        mp_obj_new_int(g_pwmfb.edge_count),
        mp_obj_new_int(g_pwmfb.debounce_drop),
        mp_obj_new_int(g_pwmfb.ready),
    };
    return mp_obj_new_tuple(4, items);
}
static MP_DEFINE_CONST_FUN_OBJ_0(mp_c1_get_health_obj, mp_c1_get_health);

// start() — Core 1 via MicroPython-Thread starten (nutzt mp_thread, nicht multicore direkt)
static mp_obj_t mp_c1_start(void) {
    static bool started = false;
    if (!started) {
        size_t stack_size = 1024;
        mp_thread_create(pwmfb_core1_task, NULL, &stack_size);
        started = true;
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(mp_c1_start_obj, mp_c1_start);

static const mp_rom_map_elem_t mp_module_c1_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_pwmfb_core1) },
    { MP_ROM_QSTR(MP_QSTR_start),      MP_ROM_PTR(&mp_c1_start_obj) },
    { MP_ROM_QSTR(MP_QSTR_get_raw),    MP_ROM_PTR(&mp_c1_get_raw_obj) },
    { MP_ROM_QSTR(MP_QSTR_get_health), MP_ROM_PTR(&mp_c1_get_health_obj) },
};
static MP_DEFINE_CONST_DICT(mp_module_c1_globals, mp_module_c1_globals_table);

const mp_obj_module_t mp_module_pwmfb_core1 = {
    .base    = { &mp_type_module },
    .globals = (mp_obj_dict_t*)&mp_module_c1_globals,
};
MP_REGISTER_MODULE(MP_QSTR_pwmfb_core1, mp_module_pwmfb_core1);
