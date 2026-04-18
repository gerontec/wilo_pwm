#include "pwmfb_core1_shared.h"
#include "pico/stdlib.h"

#define SIO_GPIO_IN  (*(volatile uint32_t*)0xD0000004u)
#define TIMER_TIMELR (*(volatile uint32_t*)0x4005400Cu)
#define PIN_MASK     (1u << 5)
#define DEBOUNCE_US_INIT  50u    // Startwert bis erste Messung vorliegt
#define DEBOUNCE_US_MIN    2u    // absolutes Minimum (Glitch-Schutz)
#define DEBOUNCE_US_MAX 5000u    // absolutes Maximum
#define POLL_BATCH       10000u

pwmfb_shared_t g_pwmfb = { .debounce_us = DEBOUNCE_US_INIT };

void *pwmfb_core1_task(void *arg) {
    (void)arg;
    uint32_t last_t   = TIMER_TIMELR;
    uint8_t  last_lvl = (SIO_GPIO_IN & PIN_MASK) ? 1 : 0;

    while (1) {
        uint32_t deb = g_pwmfb.debounce_us;  // lokale Kopie fuer Batch
        for (uint32_t i = 0; i < POLL_BATCH; i++) {
            g_pwmfb.poll_count++;
            uint8_t lvl = (SIO_GPIO_IN & PIN_MASK) ? 1 : 0;
            if (lvl != last_lvl) {
                uint32_t now  = TIMER_TIMELR;
                uint32_t diff = now - last_t;
                if (diff >= deb) {
                    if (lvl == 1)
                        g_pwmfb.low_us  = diff;
                    else
                        g_pwmfb.high_us = diff;
                    g_pwmfb.last_upd  = now;
                    g_pwmfb.ready     = 1;
                    g_pwmfb.edge_count++;

                    // Adaptive Debounce: 5% der Periode, geklemmt auf [MIN, MAX]
                    uint32_t period = g_pwmfb.high_us + g_pwmfb.low_us;
                    if (period > 0) {
                        uint32_t new_deb = period / 20;
                        if (new_deb < DEBOUNCE_US_MIN) new_deb = DEBOUNCE_US_MIN;
                        if (new_deb > DEBOUNCE_US_MAX) new_deb = DEBOUNCE_US_MAX;
                        g_pwmfb.debounce_us = new_deb;
                        deb = new_deb;
                    }
                } else {
                    g_pwmfb.debounce_drop++;
                }
                last_t   = now;
                last_lvl = lvl;
            }
        }
        sleep_us(1);
    }
    return NULL;
}
