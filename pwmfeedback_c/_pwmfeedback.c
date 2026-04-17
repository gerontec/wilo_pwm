// _pwmfeedback.c — MicroPython natmod für RP2040
// Kompiliert zu _pwmfeedback.mpy → läuft auf Standard-MicroPython-Firmware.
//
// State liegt in einem Python-bytearray (übergeben vom Wrapper) → keine C-Statics.
//
// State-Layout im bytearray (je uint32_t = 4 Bytes):
//   Byte  0:   pin_num    (uint8_t, vom Wrapper gesetzt)
//   Byte  1:   last_state (uint8_t)
//   Byte  2-3: padding
//   Byte  4:   high_us    (uint32_t)
//   Byte  8:   low_us     (uint32_t)
//   Byte 12:   last_upd   (uint32_t)
//   Byte 16:   last_change(uint32_t)
//   Gesamt: 20 Bytes

#include "py/dynruntime.h"

// RP2040 Register — kein pico-sdk nötig
#define SIO_GPIO_IN  (*(volatile uint32_t*)0xD0000004u)
#define TIMER_TIMELR (*(volatile uint32_t*)0x4005400Cu)

#define DEBOUNCE_US  100u
#define TIMEOUT_US  50000u

// State-Struct im bytearray (heap-allokiert → 4-Byte-aligned → direkt castbar)
typedef struct {
    uint8_t  pin_num;
    uint8_t  last_state;
    uint8_t  _pad[2];
    uint32_t high_us;
    uint32_t low_us;
    uint32_t last_upd;
    uint32_t last_chg;
} pwmfb_state_t;

#define STATE_SIZE  sizeof(pwmfb_state_t)  // 20 Bytes

// ==================== irq_cb(state_buf) ====================
// Vom Python-Wrapper per pin.irq() aufgerufen (soft IRQ).
// Liest GPIO + Timer direkt per Register — kein Python-Overhead im heißen Pfad.
static mp_obj_t mp_irq_cb(mp_obj_t buf_obj) {
    mp_buffer_info_t buf;
    mp_get_buffer_raise(buf_obj, &buf, MP_BUFFER_RW);
    pwmfb_state_t *s = (pwmfb_state_t*)buf.buf;

    uint32_t now     = TIMER_TIMELR;
    uint8_t  current = (SIO_GPIO_IN >> s->pin_num) & 1u;
    uint32_t diff    = now - s->last_chg;

    if (diff >= DEBOUNCE_US && current != s->last_state) {
        if (current) {
            s->low_us = diff;
        } else {
            s->high_us = diff;
        }
        s->last_upd   = now;
        s->last_chg   = now;
        s->last_state = current;
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(mp_irq_cb_obj, mp_irq_cb);

// ==================== get_raw(state_buf) → (high_us, low_us, age_us) ====================
static mp_obj_t mp_get_raw(mp_obj_t buf_obj) {
    mp_buffer_info_t buf;
    mp_get_buffer_raise(buf_obj, &buf, MP_BUFFER_READ);
    pwmfb_state_t *s = (pwmfb_state_t*)buf.buf;

    uint32_t age = TIMER_TIMELR - s->last_upd;

    mp_obj_t items[3] = {
        mp_obj_new_int(s->high_us),
        mp_obj_new_int(s->low_us),
        mp_obj_new_int(age),
    };
    return mp_obj_new_tuple(3, items);
}
static MP_DEFINE_CONST_FUN_OBJ_1(mp_get_raw_obj, mp_get_raw);

// ==================== Modul-Einstiegspunkt ====================
mp_obj_t mpy_init(mp_obj_fun_bc_t *self, size_t n_args, size_t n_kw, mp_obj_t *args) {
    MP_DYNRUNTIME_INIT_ENTRY

    mp_store_global(MP_QSTR_irq_cb,  MP_OBJ_FROM_PTR(&mp_irq_cb_obj));
    mp_store_global(MP_QSTR_get_raw, MP_OBJ_FROM_PTR(&mp_get_raw_obj));

    MP_DYNRUNTIME_INIT_EXIT
}
