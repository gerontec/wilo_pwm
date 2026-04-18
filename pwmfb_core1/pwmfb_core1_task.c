#include "pwmfb_core1_shared.h"
#include "pico/stdlib.h"

#define SIO_GPIO_IN  (*(volatile uint32_t*)0xD0000004u)
#define TIMER_TIMELR (*(volatile uint32_t*)0x4005400Cu)
#define PIN_MASK     (1u << 5)
#define DEBOUNCE_US  50u
// Batch-Groesse: so viele Polls pro Schleife bevor kurz geyieldet wird
#define POLL_BATCH   10000u

pwmfb_shared_t g_pwmfb = {0};

void *pwmfb_core1_task(void *arg) {
    (void)arg;
    uint32_t last_t   = TIMER_TIMELR;
    uint8_t  last_lvl = (SIO_GPIO_IN & PIN_MASK) ? 1 : 0;

    while (1) {
        // Batch-Polling: POLL_BATCH Iterationen ohne sleep → ~1us Latenz
        for (uint32_t i = 0; i < POLL_BATCH; i++) {
            g_pwmfb.poll_count++;
            uint8_t lvl = (SIO_GPIO_IN & PIN_MASK) ? 1 : 0;
            if (lvl != last_lvl) {
                uint32_t now  = TIMER_TIMELR;
                uint32_t diff = now - last_t;
                if (diff >= DEBOUNCE_US) {
                    if (lvl == 1)
                        g_pwmfb.low_us  = diff;
                    else
                        g_pwmfb.high_us = diff;
                    g_pwmfb.last_upd = now;
                    g_pwmfb.ready    = 1;
                    g_pwmfb.edge_count++;
                } else {
                    g_pwmfb.debounce_drop++;
                }
                last_t   = now;
                last_lvl = lvl;
            }
        }
        // kurzer sleep damit MicroPython-Thread-System nicht verhungert
        sleep_us(1);
    }
    return NULL;
}
