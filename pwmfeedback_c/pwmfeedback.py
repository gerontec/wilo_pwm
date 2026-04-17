# pwmfeedback.py – Wrapper um _pwmfeedback.mpy (natmod)
# Drop-in-Ersatz. State liegt in _state bytearray (20 Bytes).
# _pwmfeedback.mpy muss auf dem Pico liegen.

import _pwmfeedback
import utime
from machine import Pin

_PIN = 5
_TIMEOUT_US = 50000

# State-Buffer (20 Bytes, heap-allokiert, 4-Byte-aligned)
# Layout: [pin_num, last_state, pad, pad, high_us(4), low_us(4), last_upd(4), last_chg(4)]
_state = bytearray(20)
_state[0] = _PIN  # pin_num

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
    pin = Pin(_PIN, Pin.IN, Pin.PULL_UP)
    # Closure hält _state am Leben und übergibt ihn dem C-Handler
    def _irq(p):
        _pwmfeedback.irq_cb(_state)
    pin.irq(_irq, Pin.IRQ_RISING | Pin.IRQ_FALLING, hard=True)
    return pin

def get_pump_feedback(pin_value):
    global _in_error, _error_start_ms

    high_us, low_us, age_us = _pwmfeedback.get_raw(_state)

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
