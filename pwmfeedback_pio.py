# pwmfeedback_pio.py – v1.0-pio – Hardware PIO-basierte Pulsmessung für RP2040
# Drop-in-Ersatz für pwmfeedback.py — gleiche API, kein IRQ-Overhead
#
# Messprinzip: PIO State Machine misst HIGH- und LOW-Zeit cycle-genau.
# PIO-Takt: 1 MHz → 1 µs Auflösung, 2 µs pro Zählschritt (2 Instructions/Loop).
# Robuster gegen GC-Pausen als IRQ-basierte Variante.
#
# Verwendung in main.py — keine Änderung nötig:
#   import pwmfeedback_pio as pwmfeedback

import utime
import rp2
from machine import Pin

# ==================== KONFIGURATION ====================
PIN_FEEDBACK     = 5
TACHO_TIMEOUT_MS = 50
ERROR_TIMEOUT_S  = 15
ERROR_DUTY_MIN   = 79.0
ERROR_DUTY_MAX   = 95.5

STATUS_MAP = [
    (lambda d: d >= 97.5,               "Interface Damaged / Power OFF (100%)"),
    (lambda d: d >= 92.5,               "Permanent Failure (95%) - Pump stopped due to internal error"),
    (lambda d: d >= 82.5 and d <= 92.5, "Abnormal Function Mode (85-90%) - Temporarily stopped/Warning"),
    (lambda d: d > 77.5 and d < 82.5,   "Abnormal Running Mode (80%) - Not optimal performance"),
    (lambda d: d >= 5.0 and d <= 77.5,  "Normal Operation (5-75%) - Flow/Power feedback"),
    (lambda d: d >= 1.5 and d < 5.0,    "Stand-by (2%) - Active stop mode by PWM-Input"),
    (lambda d: d < 1.5,                  "Interface Damaged / Low Pulse (<2%)"),
]

# ==================== PIO PROGRAMM ====================
# Ablauf:
#   1. Einmalig: TX FIFO → OSR → Y  (Y = 0xFFFFFFFF als Reset-Wert für X)
#   2. Endlosschleife:
#      a. Auf LOW warten (Sync), dann auf steigende Flanke warten
#      b. HIGH messen: X von 0xFFFFFFFF abwärts zählen, Push wenn LOW
#      c. LOW  messen: X von 0xFFFFFFFF abwärts zählen, Push wenn HIGH
#
# Zeitauflösung: jede Zählschleife = 2 PIO-Zyklen = 2 µs @ 1 MHz
# Berechnung:   HIGH_us = (0xFFFFFFFF - x_wert) * 2

@rp2.asm_pio()
def _pwm_measure():
    # Einmalige Initialisierung: Y = 0xFFFFFFFF (Reset-Wert für X)
    pull()
    mov(y, osr)

    wrap_target()

    # Synchronisation auf steigende Flanke
    wait(0, pin, 0)          # warte auf LOW
    wait(1, pin, 0)          # warte auf HIGH (steigende Flanke)

    # HIGH-Zeit messen
    mov(x, y)                # X = 0xFFFFFFFF
    label("high_loop")
    jmp(pin, "high_count")   # Pin HIGH? → weiterzählen
    jmp("high_done")         # Pin LOW? → fertig
    label("high_count")
    jmp(x_dec, "high_loop")  # X--, zurück (immer gesprungen solange X != 0)
    label("high_done")
    mov(isr, x)
    push(noblock)            # noblock: veraltete Werte verwerfen wenn FIFO voll

    # LOW-Zeit messen
    mov(x, y)                # X = 0xFFFFFFFF
    label("low_loop")
    jmp(pin, "low_done")     # Pin HIGH? → LOW-Phase vorbei
    jmp(x_dec, "low_loop")   # X--, weiterzählen
    label("low_done")
    mov(isr, x)
    push(noblock)

    wrap()

# ==================== GLOBALE ZUSTANDSVARIABLEN ====================
_sm                  = None
_last_high_us        = 0
_last_low_us         = 0
_last_update_us      = 0
_error_state_start_ms = 0
_is_in_error_state   = False

# ==================== HILFSFUNKTIONEN ====================
def _get_pump_status(duty):
    for check, status in STATUS_MAP:
        if check(duty):
            return status
    return "UNKNOWN STATUS"

def _drain_fifo():
    """Liest alle verfügbaren HIGH/LOW-Paare aus dem PIO-RX-FIFO."""
    global _last_high_us, _last_low_us, _last_update_us
    while _sm.rx_fifo() >= 2:
        x_high = _sm.get()
        x_low  = _sm.get()
        # Zählwert → Mikrosekunden: (0xFFFFFFFF - x) * 2µs/Count
        _last_high_us   = (0xFFFFFFFF - x_high) * 2
        _last_low_us    = (0xFFFFFFFF - x_low)  * 2
        _last_update_us = utime.ticks_us()

# ==================== ÖFFENTLICHE API ====================
def init_feedback_pin():
    """Initialisiert PIO State Machine auf PIN_FEEDBACK. Gibt Pin-Objekt zurück."""
    global _sm
    pin = Pin(PIN_FEEDBACK, Pin.IN, Pin.PULL_UP)
    _sm = rp2.StateMachine(
        0, _pwm_measure,
        freq=1_000_000,   # 1 MHz → 1 µs pro Zyklus
        in_base=pin,
        jmp_pin=pin,
    )
    _sm.put(0xFFFFFFFF)   # Y-Initialwert in TX FIFO
    _sm.active(1)
    return pin

def get_pump_feedback(current_pin_value):
    """Gibt aktuelles Feedback-Dict zurück. Gleiche Struktur wie IRQ-Variante."""
    global _is_in_error_state, _error_state_start_ms

    _drain_fifo()

    now_us = utime.ticks_us()
    now_ms = utime.ticks_ms()
    age_ms = utime.ticks_diff(now_us, _last_update_us) / 1000

    freq   = 0.0
    duty   = 0.0
    status = "TIMEOUT / NO PULSE"

    if age_ms < TACHO_TIMEOUT_MS and _last_high_us > 0:
        T = _last_high_us + _last_low_us
        if T > 1000:
            freq  = round(1_000_000.0 / T, 2)
            duty  = round((_last_high_us / T) * 100.0, 2)
            duty  = min(max(duty, 0.0), 100.0)
            status = _get_pump_status(duty)

        # Fehler-Timeout-Logik (identisch zur IRQ-Variante)
        if ERROR_DUTY_MIN <= duty <= ERROR_DUTY_MAX:
            if not _is_in_error_state:
                _is_in_error_state    = True
                _error_state_start_ms = now_ms
            if utime.ticks_diff(now_ms, _error_state_start_ms) / 1000 >= ERROR_TIMEOUT_S:
                status = f"Pump Stopped (Error Timeout after {ERROR_TIMEOUT_S}s)"
                duty   = 0.0
        else:
            _is_in_error_state    = False
            _error_state_start_ms = 0
    else:
        _is_in_error_state    = False
        _error_state_start_ms = 0

    return {
        "PIN5":          current_pin_value,
        "PIN5_Flank_us": _last_low_us,   # letzte LOW-Dauer ≈ letzte Flankenzeit
        "PIN5_HIGH_us":  _last_high_us,
        "PIN5_LOW_us":   _last_low_us,
        "PIN5_Freq_Hz":  freq,
        "PumpDuty":      round(duty, 2),
        "PumpStatus":    status,
    }
