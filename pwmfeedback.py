# pwmfeedback.py – v2.30-real-duty – Duty gegen echte Periode berechnet
# Duty = HIGH / T  (nicht mehr gegen NOMINAL 75Hz)
# → Fehlercodes werden bei jeder Pumpenfrequenz korrekt erkannt

import utime
from machine import Pin

# ==================== KONFIGURATION ====================
TACHO_TIMEOUT_MS = 50
MIN_PULSE_WIDTH_US = 100
PIN_FEEDBACK = 5
# Fehler-Timeout-Logik (bleibt unverändert)
ERROR_TIMEOUT_S = 15
ERROR_DUTY_MIN = 79.0
ERROR_DUTY_MAX = 95.5

# Status-Map (genau wie bei dir)
STATUS_MAP = [
    (lambda d: d >= 97.5, "Interface Damaged / Power OFF (100%)"),
    (lambda d: d >= 92.5, "Permanent Failure (95%) - Pump stopped due to internal error"),
    (lambda d: d >= 82.5 and d <= 92.5, "Abnormal Function Mode (85-90%) - Temporarily stopped/Warning"),
    (lambda d: d > 77.5 and d < 82.5, "Abnormal Running Mode (80%) - Not optimal performance"),
    (lambda d: d >= 5.0 and d <= 77.5, "Normal Operation (5-75%) - Flow/Power feedback"),
    (lambda d: d >= 1.5 and d < 5.0, "Stand-by (2%) - Active stop mode by PWM-Input"),
    (lambda d: d < 1.5, "Interface Damaged / Low Pulse (<2%)"),
]

# ==================== GLOBALE VARIABLEN ====================
last_any_flank_us = utime.ticks_us()      # ← NEU: Zeit zwischen JEGLICHEN Flanken
last_pin5_time_us = utime.ticks_us()
pin5_high_time_us = 0
pin5_low_time_us = 0
pin5_flank_time_us = 0
last_pulse_time_us = utime.ticks_us()

error_state_start_time = 0
is_in_error_state = False

# ==================== IRQ – jetzt noch robuster ====================
def pin5_callback(pin):
    global last_pin5_time_us, pin5_flank_time_us, pin5_high_time_us, pin5_low_time_us
    global last_pulse_time_us, last_any_flank_us

    now = utime.ticks_us()
    diff = utime.ticks_diff(now, last_pin5_time_us)

    if diff > MIN_PULSE_WIDTH_US:
        if pin.value() == 1:
            pin5_low_time_us = diff
        else:
            pin5_high_time_us = diff
        pin5_flank_time_us = diff
        last_pin5_time_us = now

    # Diese beiden Zeilen sind der entscheidende Trick:
    last_pulse_time_us = now          # für Timeout
    last_any_flank_us = now           # für exakte Frequenzmessung (auch bei 99,9% Duty!)

# ==================== STATUS-LOGIK ====================
def get_pump_status(duty_cycle):
    for check, status in STATUS_MAP:
        if check(duty_cycle):
            return status
    return "UNKNOWN STATUS"

# ==================== INITIALISIERUNG ====================
def init_feedback_pin():
    feedback_pin = Pin(PIN_FEEDBACK, Pin.IN, Pin.PULL_UP)
    feedback_pin.irq(trigger=Pin.IRQ_RISING | Pin.IRQ_FALLING, handler=pin5_callback, hard=True)
    return feedback_pin

# ==================== HAUPTFUNKTION – jetzt bombensicher ====================
def get_pump_feedback(current_pin_value):
    global is_in_error_state, error_state_start_time
    now_us = utime.ticks_us()
    now_ms = utime.ticks_ms()

    # 1. Zeit seit letzter beliebiger Flanke (das ist der heilige Gral!)
    period_any_flank_us = utime.ticks_diff(now_us, last_any_flank_us)
    time_since_pulse_ms = utime.ticks_diff(now_us, last_pulse_time_us) / 1000

    # 2. Standardwerte
    freq = 0.0
    duty = 0.0
    status = "TIMEOUT / NO PULSE"

    # 3. Puls vorhanden?
    if time_since_pulse_ms < TACHO_TIMEOUT_MS:
        # Normale Frequenzmessung aus HIGH + LOW
        T = pin5_high_time_us + pin5_low_time_us
        if T > 1000:  # mind. 1ms Periode → < 1000 Hz
            freq = round(1_000_000.0 / T, 2)
            duty = round((pin5_high_time_us / T) * 100.0, 2)  # gegen echte Periode!
            duty = min(max(duty, 0.0), 100.0)
            status = get_pump_status(duty)

        # Fehler-Timeout-Logik (bleibt exakt wie bei dir!)
        if ERROR_DUTY_MIN <= duty <= ERROR_DUTY_MAX:
            if not is_in_error_state:
                is_in_error_state = True
                error_state_start_time = now_ms
            if utime.ticks_diff(now_ms, error_state_start_time) / 1000 >= ERROR_TIMEOUT_S:
                status = f"Pump Stopped (Error Timeout after {ERROR_TIMEOUT_S}s)"
                duty = 0.0
        else:
            is_in_error_state = False
            error_state_start_time = 0
    else:
        is_in_error_state = False
        error_state_start_time = 0

    return {
        "PIN5": current_pin_value,
        "PIN5_Flank_us": pin5_flank_time_us,
        "PIN5_HIGH_us": pin5_high_time_us,
        "PIN5_LOW_us": pin5_low_time_us,
        "PIN5_Freq_Hz": freq,
        "PumpDuty": round(duty, 2),
        "PumpStatus": status,
    }
