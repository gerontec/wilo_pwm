add_library(usermod_pwmfeedback INTERFACE)

target_sources(usermod_pwmfeedback INTERFACE
    ${CMAKE_CURRENT_LIST_DIR}/_pwmfeedback.c
)

target_include_directories(usermod_pwmfeedback INTERFACE
    ${CMAKE_CURRENT_LIST_DIR}
)

target_link_libraries(usermod_pwmfeedback INTERFACE
    pico_multicore
    hardware_gpio
    hardware_timer
    hardware_sync
)

target_link_libraries(usermod INTERFACE usermod_pwmfeedback)
