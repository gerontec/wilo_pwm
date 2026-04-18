# pwmfeedback_core1.py — gleiche API wie pwmfeedback.py, Backend: Core 1
import pwmfb_core1
import utime
from machine import Pin

_TIMEOUT_US = 50000

_STATUS_MAP = [
    (97.5, "Interface Damaged / Power OFF (100%)"),
    (92.5, "Permanent Failure (95%) - Pump stopped due to internal error"),
    (82.5, "Abnormal Function Mode (85-90%) - Temporarily stopped/Warning"),
    (77.5, "Abnormal Running Mode (80%) - Not optimal performance"),
    ( 5.0, "Normal Operation (5-75%) - Flow/Power feedback"),
    ( 1.5, "Stand-by (2%) - Active stop mode by PWM-Input"),
    ( 0.0, "Interface Damaged / Low Pulse (<2%)"),
]

_ERROR_DUTY_MIN  = 79.0
_ERROR_DUTY_MAX  = 95.5
_ERROR_TIMEOUT_S = 15

_error_start_ms = 0
_in_error       = False

def _get_status(duty):
    for threshold, text in _STATUS_MAP:
        if duty >= threshold:
            return text
    return "UNKNOWN STATUS"

def init_feedback_pin():
    pwmfb_core1.start()  # Core 1 starten — einmalig, Guard intern
    return Pin(5, Pin.IN, Pin.PULL_UP)  # Pin-Objekt für .value() Kompatibilität

def get_health():
    h = pwmfb_core1.get_health()
    return (h[1], h[2])  # (edge_count, debounce_drop) — kompatibel mit natmod API

def get_pump_feedback(pin_value):
    global _in_error, _error_start_ms

    high_us, low_us, age_us = pwmfb_core1.get_raw()

    freq   = 0.0
    duty   = 0.0
    status = "TIMEOUT / NO PULSE"

    if age_us < _TIMEOUT_US and high_us > 0:
        T = high_us + low_us
        if T > 1000:
            freq   = round(1000000.0 / T, 2)
            duty   = round(high_us / T * 100.0, 2)
            duty   = min(max(duty, 0.0), 100.0)
            status = _get_status(duty)

        now_ms = utime.ticks_ms()
        if _ERROR_DUTY_MIN <= duty <= _ERROR_DUTY_MAX:
            if not _in_error:
                _in_error       = True
                _error_start_ms = now_ms
            if utime.ticks_diff(now_ms, _error_start_ms) / 1000 >= _ERROR_TIMEOUT_S:
                status = "Pump Stopped (Error Timeout after {}s)".format(_ERROR_TIMEOUT_S)
                duty   = 0.0
        else:
            _in_error       = False
            _error_start_ms = 0
    else:
        _in_error       = False
        _error_start_ms = 0

    return {
        "PIN5":          pin_value,
        "PIN5_Flank_us": low_us,
        "PIN5_HIGH_us":  high_us,
        "PIN5_LOW_us":   low_us,
        "PIN5_Freq_Hz":  freq,
        "PumpDuty":      duty,
        "PumpStatus":    status,
    }
