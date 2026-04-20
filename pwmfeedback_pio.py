# pwmfeedback_pio.py – v2.60-pio – Ringpuffer + Median-Filter
# Drop-in-Ersatz für pwmfeedback.py — gleiche API, kein IRQ-Overhead
#
# Messprinzip: PIO State Machine misst HIGH- und LOW-Zeit cycle-genau.
# PIO-Takt: 1 MHz → 2 µs Auflösung (natürlicher Tiefpass gegen HF-Glitches)
#
# Robustheit: interner 25ms-Timer leert FIFO kontinuierlich → Ringpuffer mit
# ~300 Messungen/5s. Duty/Freq aus Median → Ausreißer (HIGH=0 etc.) wirkungslos.
# Keine Hardcode-Frequenz — funktioniert für jedes PWM-Feedback-Signal.
#
# Verwendung in main.py — keine Änderung nötig:
#   import pwmfeedback_pio as pwmfeedback

import utime
import rp2
from machine import Pin, Timer

# ==================== KONFIGURATION ====================
PIN_FEEDBACK     = 5
TACHO_TIMEOUT_MS = 2000   # Kein gültiger Wert seit 2s → TIMEOUT
DRAIN_INTERVAL_MS = 25    # FIFO-Drain-Intervall: schneller als FIFO-Füllzeit (~27ms)
_BUF_SIZE        = 30     # Ringpuffer: ~400ms Datenfenster @ 75 Hz

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
# 1 MHz SM: 2 Zyklen/Loop → 2 µs/Count, Glitches < 2 µs unsichtbar
# Zählwert → µs: (0xFFFFFFFF - x) * 2

@rp2.asm_pio()
def _pwm_measure():
    pull()
    mov(y, osr)
    wrap_target()
    wait(0, pin, 0)
    wait(1, pin, 0)
    mov(x, y)
    label("high_loop")
    jmp(pin, "high_count")
    jmp("high_done")
    label("high_count")
    jmp(x_dec, "high_loop")
    label("high_done")
    mov(isr, x)
    push(noblock)
    mov(x, y)
    label("low_loop")
    jmp(pin, "low_done")
    jmp(x_dec, "low_loop")
    label("low_done")
    mov(isr, x)
    push(noblock)
    wrap()

# ==================== RINGPUFFER & ZUSTAND ====================
_sm              = None
_drain_timer     = None
_high_buf        = [0] * _BUF_SIZE
_low_buf         = [0] * _BUF_SIZE
_buf_idx         = 0
_buf_count       = 0           # Anzahl valider Einträge (0.._BUF_SIZE)
_last_update_us  = 0
_error_state_start_ms = 0
_is_in_error_state    = False

# Dynamische Drain-Anpassung
FREQ_STABLE_MS   = 1000        # 1s stabile Frequenz vor Drain-Anpassung
_drain_ms        = DRAIN_INTERVAL_MS
_freq_ref        = 0.0         # zuletzt bestätigte Basisfrequenz
_freq_seen_ms    = 0           # Zeitstempel seit wann aktuelle Freq stabil

# ==================== HILFSFUNKTIONEN ====================
def _get_pump_status(duty):
    for check, status in STATUS_MAP:
        if check(duty):
            return status
    return "UNKNOWN STATUS"

def _median(buf, count):
    """Median aus den ersten 'count' Einträgen (ohne Heap-Allokation bei count=1)."""
    if count == 1:
        return buf[0]
    tmp = sorted(buf[:count])
    return tmp[count // 2]

def _adapt_drain(freq):
    """Drain-Intervall an Frequenz anpassen: FIFO (4 Words = 2 Zyklen) vor Überlauf leeren."""
    global _drain_timer, _drain_ms
    # 1.5 Zyklen Sicherheitsabstand zum FIFO-Überlauf
    new_ms = max(2, int(1500 / freq))
    if new_ms == _drain_ms:
        return
    _drain_ms = new_ms
    if _drain_timer:
        _drain_timer.deinit()
        _drain_timer.init(period=_drain_ms, mode=Timer.PERIODIC, callback=_drain_fifo)

def _drain_fifo(t=None):
    """FIFO leeren und valide Messungen in Ringpuffer schreiben. Timer-safe."""
    global _buf_idx, _buf_count, _last_update_us
    if _sm is None:
        return
    while _sm.rx_fifo() >= 2:
        x_high = _sm.get()
        x_low  = _sm.get()
        h = (0xFFFFFFFF - x_high) * 2
        l = (0xFFFFFFFF - x_low)  * 2
        if h > 0 and l > 0 and (h + l) > 100:
            _high_buf[_buf_idx] = h
            _low_buf[_buf_idx]  = l
            _buf_idx = (_buf_idx + 1) % _BUF_SIZE
            if _buf_count < _BUF_SIZE:
                _buf_count += 1
            _last_update_us = utime.ticks_us()

# ==================== ÖFFENTLICHE API ====================
def init_feedback_pin():
    """Initialisiert PIO und startet internen Drain-Timer. Gibt Pin-Objekt zurück."""
    global _sm, _drain_timer, _buf_idx, _buf_count
    _buf_idx   = 0
    _buf_count = 0
    pin = Pin(PIN_FEEDBACK, Pin.IN, Pin.PULL_UP)
    _sm = rp2.StateMachine(
        0, _pwm_measure,
        freq=1_000_000,
        in_base=pin,
        jmp_pin=pin,
    )
    _sm.put(0xFFFFFFFF)
    _sm.active(1)
    # Interner Timer: FIFO schneller leeren als er volläuft (~27ms bei 75 Hz)
    _drain_timer = Timer()
    _drain_timer.init(period=DRAIN_INTERVAL_MS, mode=Timer.PERIODIC, callback=_drain_fifo)
    return pin

def get_pump_feedback(current_pin_value):
    """Gibt Feedback-Dict zurück. Duty/Freq aus Median des Ringpuffers."""
    global _is_in_error_state, _error_state_start_ms, _freq_ref, _freq_seen_ms

    now_us = utime.ticks_us()
    now_ms = utime.ticks_ms()
    age_ms = utime.ticks_diff(now_us, _last_update_us) / 1000

    freq   = 0.0
    duty   = 0.0
    status = "TIMEOUT / NO PULSE"
    high_med = 0
    low_med  = 0

    if age_ms < TACHO_TIMEOUT_MS and _buf_count > 0:
        n = _buf_count
        high_med = _median(_high_buf, n)
        low_med  = _median(_low_buf,  n)
        T = high_med + low_med
        if T > 100:
            freq  = round(1_000_000.0 / T, 2)
            duty  = round((high_med / T) * 100.0, 2)
            duty  = min(max(duty, 0.0), 100.0)
            status = _get_pump_status(duty)
            # Dynamische Drain-Anpassung: 1s stabile Frequenz abwarten
            if abs(freq - _freq_ref) / max(_freq_ref, 1) > 0.10:
                _freq_ref     = freq     # neue Frequenz → Stabilitätszähler reset
                _freq_seen_ms = now_ms
            elif utime.ticks_diff(now_ms, _freq_seen_ms) >= FREQ_STABLE_MS:
                _adapt_drain(freq)       # 1s stabil → Drain-Intervall anpassen

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
        "PIN5_Flank_us": low_med,
        "PIN5_HIGH_us":  high_med,
        "PIN5_LOW_us":   low_med,
        "PIN5_Freq_Hz":  freq,
        "PIN5_N":        _buf_count,
        "DrainMs":       _drain_ms,
        "PumpDuty":      round(duty, 2),
        "PumpStatus":    status,
    }
