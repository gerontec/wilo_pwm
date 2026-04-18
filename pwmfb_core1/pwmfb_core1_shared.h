#pragma once
#include <stdint.h>

// Shared between Core 0 (MicroPython C module) and Core 1 (polling loop).
// All fields volatile, uint32_t writes on RP2040 SRAM are atomic.
typedef struct {
    volatile uint32_t high_us;      // last measured HIGH duration
    volatile uint32_t low_us;       // last measured LOW duration
    volatile uint32_t last_upd;     // TIMER_TIMELR at last valid edge pair
    // --- health / debug ---
    volatile uint32_t poll_count;   // incremented every Core 1 loop iteration
    volatile uint32_t edge_count;   // incremented on every valid edge
    volatile uint32_t debounce_drop;// edges dropped by debounce filter
    volatile uint32_t debounce_us; // aktuell verwendeter Schwellwert (adaptiv)
    volatile uint8_t  ready;        // 1 = at least one valid measurement
    volatile uint8_t  _pad[3];
} pwmfb_shared_t;

extern pwmfb_shared_t g_pwmfb;
