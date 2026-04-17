# Build-Anleitung: MicroPython mit _pwmfeedback C-Modul

## Einmalig: Abhängigkeiten

```bash
sudo apt install cmake gcc-arm-none-eabi libnewlib-arm-none-eabi build-essential git
```

## MicroPython + Pico SDK holen

```bash
git clone https://github.com/micropython/micropython ~/micropython
cd ~/micropython
git submodule update --init lib/pico-sdk lib/tinyusb
make -C mpy-cross   # Cross-Compiler bauen (~2 min)
```

## Firmware bauen (Pico W)

```bash
cd ~/micropython/ports/rp2

cmake -B build \
    -DPICO_BOARD=pico_w \
    -DUSER_C_MODULES=/home/gh/python/pwmfeedback_c/micropython.cmake

cmake --build build -j4
# → build/firmware.uf2  (~5 min)
```

## Firmware flashen

Pico im BOOTSEL-Modus anschließen (BOOTSEL-Knopf halten beim Einstecken):

```bash
cp ~/micropython/ports/rp2/build/firmware.uf2 /media/$USER/RPI-RP2/
```

## pwmfeedback.py auf den Pico übertragen

```bash
python3 ~/webrepl_cli.py -p 7291 \
    /home/gh/python/pwmfeedback_c/pwmfeedback.py \
    192.168.178.167:pwmfeedback.py
```

Die alte pwmfeedback.py auf dem Pico kann danach gelöscht werden —
das C-Modul `_pwmfeedback` ist in der Firmware eingebaut.

## Wichtig

- `_thread` und dieses Modul nicht gleichzeitig verwenden (beide nutzen Core 1)
- main.py bleibt unverändert — gleiche API
