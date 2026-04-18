import time
import gc
import network
from machine import Pin, PWM, Timer, WDT, ADC
from umqtt.simple import MQTTClient
import sys
import os
import ujson
import utime
import pwmfeedback_pio as pwmfeedback

# ==================== KONFIGURATION ====================
WATCHDOG_ENABLED = True
WATCHDOG_TIMEOUT = 8000 # ms
PWM_MIN_HARD = 0       # absolutes Hardware-Minimum (unveränderlich)
PWM_MAX = 64000
RAMP_DURATION = 240.0  # Sekunden für sanfte Rampe (4 Minuten)

TARGET_PWM = 33000
INTERVAL_SECONDS = 900 # 15 Minuten
BOOST_DURATION = 5 # 5 Sekunden

mqtt_server = '192.168.178.218'
client_id = 'picow2'
topic_sub_pump  = b'heatp/pump'
topic_pub       = b'heatp/pico120'
topic_pins      = b'heatp/pins'

FIRMWARE_VERSION = "v2.50-pio-feedback"
MQTT_TIMEOUT_S = 30  # Reset wenn kein Publish seit 30s
start_time = time.time()
last_publish_time = time.time()

# ==================== GLOBALE VARIABLEN ====================
PWM_MIN = 33000        # per MQTT setzbares Minimum (min:VALUE)
current_pwm = PWM_MAX   # Hardware startet auf MAX (Sicherheit)
target_pwm = TARGET_PWM  # Ziel: sofort rampen auf Normalbetrieb
ramp_start_time = None
ramp_start_value = None
last_boost_start = None  # wird beim ersten publish_all_pins gesetzt
boost_active = False
timers = []
client = None
_feedback_err_count = 0 # Hysterese: Emergency erst nach 3 Fehlmessungen

# ==================== HARDWARE & PIN-DEFINITIONEN ====================
pwm0 = PWM(Pin(0), freq=800)
pwm0.duty_u16(PWM_MAX)

LED = Pin("LED", Pin.OUT)
LED.on()

feedback_pin7 = Pin(7, Pin.IN, Pin.PULL_UP)
test_pin1 = Pin(1, Pin.IN, Pin.PULL_UP)
pump_feedback_pin19 = Pin(19, Pin.IN)

# Pin 5 Initialisierung über das Modul
feedback_pin5 = pwmfeedback.init_feedback_pin()

# ADC Pins
adc26 = ADC(Pin(26))
adc27 = ADC(Pin(27))
adc28 = ADC(Pin(28))

# WLAN Setup
sta = network.WLAN(network.STA_IF)
sta.active(True)
sta.connect("f24", "9876543210")

# Watchdog Setup
if WATCHDOG_ENABLED:
    wdt = WDT(timeout=WATCHDOG_TIMEOUT)

def feed_watchdog():
    if WATCHDOG_ENABLED and wdt:
        wdt.feed()

# ----------------------------------------------------------------------
## 🔗 MQTT LOGGING und Hilfsfunktionen
# ----------------------------------------------------------------------

def mqtt_log(msg):
    try:
        if client:
            ts = time.localtime()
            payload = f"{ts[3]:02d}:{ts[4]:02d}:{ts[5]:02d} - {msg}"
            client.publish(b'heatp/log', payload.encode())
    except:
        pass

def get_mem_percent():
    try:
        gc.collect()
        return int(gc.mem_alloc() / (gc.mem_alloc() + gc.mem_free()) * 100)
    except:
        return 0.0

def read_adc_voltage(adc):
    try:
        raw = adc.read_u16()
        return round((raw / 65535) * 3.3, 3)
    except:
        return 0.0

# ----------------------------------------------------------------------
## 📊 MQTT-Payload-Erzeugung (Modularisiert)
# ----------------------------------------------------------------------

def _is_feedback_error(feedback_data):
    duty = feedback_data["PumpDuty"]
    status = feedback_data["PumpStatus"]
    if duty < 9.0:
        return True  # TIMEOUT/NO PULSE (duty=0) → ebenfalls MAX PWM
    for kw in ("Damaged", "Failure", "Abnormal", "Error Timeout"):
        if kw in status:
            return True
    return False

def publish_all_pins(t):
    global target_pwm, current_pwm, ramp_start_time, boost_active, _feedback_err_count

    # --- PUMPEN FEEDBACK aus Modul ---
    feedback_data = pwmfeedback.get_pump_feedback(feedback_pin5.value())

    # --- FEEDBACK-NOTFALL: erst nach 60s Startup-Grace-Period, 3× bestätigt ---
    uptime = int(time.time() - start_time)
    if target_pwm > 0 and uptime > 60 and _is_feedback_error(feedback_data):
        _feedback_err_count += 1
        if _feedback_err_count >= 3:
            target_pwm = PWM_MAX
            current_pwm = PWM_MAX
            ramp_start_time = None
            pwm0.duty_u16(PWM_MAX)
            boost_active = False
            _feedback_err_count = 0
            mqtt_log(f"NOTFALL: Feedback-Fehler ({feedback_data['PumpStatus']}) → MAX PWM")
    else:
        _feedback_err_count = 0

    # --- ENDE PWM BERECHNUNG ---

    try:
        ip = sta.ifconfig()[0] if sta.isconnected() else "0.0.0.0"
        wlan_status = 1 if sta.isconnected() else 0
        mem_pct = get_mem_percent()
        if mem_pct > 55:
            gc.collect()
            mem_pct = get_mem_percent()
        uptime = int(time.time() - start_time)

        mp_version = f"{os.uname().sysname} v{os.uname().release}"
        build_date = os.uname().version.split(';')[1].strip() if ';' in os.uname().version else "unknown"
        machine = os.uname().machine

        full_fw = f"{FIRMWARE_VERSION} | {mp_version} | {machine} | {build_date}"

        pins = {
            "FW": full_fw,
            "UPTIME": uptime,
            "WLAN": wlan_status,
            "LED": LED.value(),
            "PWM": current_pwm,
            "PWM_MIN": PWM_MIN,
            "PIN0": current_pwm,
            "PIN1": test_pin1.value(),
            "PIN7": feedback_pin7.value(),

            # FEEDBACK LOGIK aus Modul
            "PIN5": feedback_data["PIN5"],
            "PIN5_Flank_us": feedback_data["PIN5_Flank_us"],
            "PIN5_HIGH_us": feedback_data["PIN5_HIGH_us"],
            "PIN5_LOW_us": feedback_data["PIN5_LOW_us"],
            "PIN5_Freq_Hz": feedback_data["PIN5_Freq_Hz"],
            "PumpDuty": feedback_data["PumpDuty"],
            "PumpStatus": feedback_data["PumpStatus"],

            "PIN19": pump_feedback_pin19.value(),
            "PumpFeedback": pump_feedback_pin19.value(),

            # ADC PINS
            "PIN26": read_adc_voltage(adc26),
            "PIN27": read_adc_voltage(adc27),
            "PIN28": read_adc_voltage(adc28),
        }

        # Schleife über die restlichen GPIOs
        for gp in [2,3,4,6,8,9,10,11,12,13,14,15,16,17,18,20,21]:
            if gp in (5, 19):
                continue
            try:
                p = Pin(gp, Pin.IN)
                val = p.value()
                p.deinit()
                pins[f"PIN{gp}"] = val
            except:
                pins[f"PIN{gp}"] = 0

        # JSON-Serialisierung
        json_str = ujson.dumps(pins)
        client.publish(topic_pins, json_str.encode())

        # Statusmeldung (kurze Form)
        pin7_state = "LOW" if feedback_pin7.value() == 0 else "HIGH"
        pin5_state = "LOW" if feedback_pin5.value() == 0 else "HIGH"
        pump_state = "LOW" if pump_feedback_pin19.value() == 0 else "HIGH"
        pump_duty_cycle_pct = feedback_data["PumpDuty"]
        pump_status_text = feedback_data["PumpStatus"]

        status = f"PWM:{current_pwm},IP:{ip},MEM:{mem_pct}%,PIN7:{pin7_state},PIN5:{pin5_state},PUMP:{pump_state},Duty:{pump_duty_cycle_pct}%,Status:{pump_status_text}"
        client.publish(topic_pub, status.encode())
        global last_publish_time
        last_publish_time = time.time()
        # WDT wird NUR im Main-Loop gefüttert (Zeile ~382)
        # Hier KEIN feed_watchdog() — Timer-IRQ darf WDT nicht füttern

    except Exception as e:
        mqtt_log(f"publish_all_pins error: {e}")

# ----------------------------------------------------------------------
## ⏱️ Steuerung und MQTT-Logik
# ----------------------------------------------------------------------

def update_pwm_ramp(t):
    global current_pwm, target_pwm, ramp_start_time, ramp_start_value
    if ramp_start_time is None:
        if current_pwm == target_pwm:
            pwm0.duty_u16(current_pwm)
            return
        ramp_start_time = time.time()
        ramp_start_value = current_pwm

    elapsed = time.time() - ramp_start_time
    if elapsed >= RAMP_DURATION:
        current_pwm = target_pwm
        ramp_start_time = None
        pwm0.duty_u16(current_pwm)
        return

    progress = elapsed / RAMP_DURATION
    new_pwm = int(ramp_start_value + (target_pwm - ramp_start_value) * progress)
    new_pwm = max(max(PWM_MIN_HARD, PWM_MIN), min(PWM_MAX, new_pwm))

    if new_pwm != current_pwm:
        current_pwm = new_pwm
        pwm0.duty_u16(current_pwm)

def boost_cycle(t):
    global target_pwm, TARGET_PWM, ramp_start_time, last_boost_start, boost_active, current_pwm
    now = time.time()
    if last_boost_start is None:
        last_boost_start = now  # Startzeitpunkt initialisieren — verhindert Sofort-Boost
    if not boost_active and now - last_boost_start >= INTERVAL_SECONDS:
        # BOOST START
        mqtt_log("15-Min-Boost: 5s auf 100%")
        target_pwm = PWM_MAX
        ramp_start_time = None
        pwm0.duty_u16(PWM_MAX)
        current_pwm = PWM_MAX # <--- FIX: current_pwm synchronisieren
        LED.on()
        last_boost_start = now
        boost_active = True

    if boost_active and now - last_boost_start >= BOOST_DURATION:
        # BOOST ENDE
        mqtt_log(f"Boost Ende → 4min Rampe auf {TARGET_PWM}")
        target_pwm = TARGET_PWM
        ramp_start_time = None
        boost_active = False

def sub_cb(topic, msg):
    global target_pwm, TARGET_PWM, PWM_MIN, ramp_start_time, last_boost_start, boost_active, current_pwm
    try:
        if topic == topic_sub_pump:
            cmd = msg.decode().strip().lower()

            if cmd == "reset":
                mqtt_log("REMOTE RESET → Watchdog läuft aus in 8s")
                for t in timers:
                    try: t.deinit()
                    except: pass
                timers.clear()
                try:
                    sta.active(False)
                except:
                    pass
                while True:
                    pass

            if cmd == "off":
                target_pwm = 0
                ramp_start_time = None
                pwm0.duty_u16(0)
                current_pwm = 0 # <--- FIX: current_pwm synchronisieren
                LED.off()
                boost_active = False
                mqtt_log("Pumpe AUS")
            elif cmd in ("auto", ""):
                boost_active = True
                last_boost_start = time.time() - INTERVAL_SECONDS + 10
                LED.on()
                mqtt_log("Auto reaktiviert")
            elif cmd.isdigit():
                val = int(cmd)
                TARGET_PWM = max(PWM_MIN, val) if val > 0 else 0
                target_pwm = TARGET_PWM
                ramp_start_time = None
                if target_pwm > 0:
                    LED.on()
                else:
                    LED.off()
                mqtt_log(f"Manuell → {val}")
            elif cmd == "on":
                target_pwm = PWM_MAX
                ramp_start_time = None
                pwm0.duty_u16(PWM_MAX) # Hardware direkt setzen
                current_pwm = PWM_MAX # <--- FIX: current_pwm synchronisieren
                boost_active = False
                LED.on()
                mqtt_log("Manuell → 100%")
            elif cmd.startswith("min:"):
                val = int(cmd[4:])
                PWM_MIN = max(0, min(PWM_MAX, val))
                mqtt_log(f"PWM_MIN gesetzt → {PWM_MIN}")
            else:
                mqtt_log(f"Unbekannt: {cmd}")

            publish_all_pins(None)
    except Exception as e:
        mqtt_log(f"sub_cb error: {e}")

def mqtt_connect():
    try:
        # ANNAHME: Broker braucht keine Auth
        c = MQTTClient(client_id, mqtt_server, keepalive=300)
        c.set_callback(sub_cb)
        c.connect()
        mqtt_log("MQTT verbunden")
        c.subscribe(topic_sub_pump)
        return c
    except:
        return None

def reconnect():
    mqtt_log("MQTT verloren → harter Reset in <8s")
    time.sleep(9)      # länger als WDT → garantiert Reset
    while True: pass   # fallback, falls sleep irgendwie überlebt

def add_timer(period, callback):
    t = Timer()
    t.init(period=period, mode=Timer.PERIODIC, callback=callback)
    timers.append(t)

# ----------------------------------------------------------------------
## 🚀 INIT & HAUPTSCHLEIFE
# ----------------------------------------------------------------------

client = mqtt_connect()
LED.on()
# Warten auf WLAN (max 7s, dann WDT-Reset)
wlan_wait = 0
while not sta.isconnected():
    utime.sleep_ms(100)
    wlan_wait += 1
    if wlan_wait % 20 == 0:  # alle 2s WDT füttern solange noch kein WLAN
        feed_watchdog()
    if wlan_wait >= 70:      # nach 7s aufhören → WDT resetet in <1s
        break

ip = sta.ifconfig()[0]
mqtt_log(f"Start – IP: {ip} | FW: {FIRMWARE_VERSION}")
publish_all_pins(None)

# Timer-Initialisierung
add_timer(200,      update_pwm_ramp)
add_timer(1000,     boost_cycle)
add_timer(5000,     publish_all_pins)
add_timer(240000,   lambda t: client.ping() if client else None)
add_timer(3600000,  lambda t: (gc.collect(), mqtt_log(f"GC: {gc.mem_free()}")))

while True:
    try:
        if client:
            client.check_msg()
        # Kein Publish seit MQTT_TIMEOUT_S → WDT absichtlich verhungern lassen
        if time.time() - last_publish_time > MQTT_TIMEOUT_S:
            mqtt_log("MQTT Timeout → WDT Reset")
            while True: pass
        feed_watchdog()
    except Exception as e:
        mqtt_log(f"Error: {e}")
        reconnect()
