// Diesen Code in ports/rp2/main.c vor mp_main() einfuegen:
//
//   #include "pico/multicore.h"
//   #include "pwmfb_core1_task.h"
//   multicore_launch_core1(pwmfb_core1_task);
//
// Dann bauen:
//   make BOARD=RPI_PICO_W \
//        USER_C_MODULES=/home/gh/python/pwmfb_core1/micropython.cmake \
//        -j$(nproc)
