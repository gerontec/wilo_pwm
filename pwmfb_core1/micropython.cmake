add_library(usermod_pwmfb_core1 INTERFACE)

target_sources(usermod_pwmfb_core1 INTERFACE
    ${CMAKE_CURRENT_LIST_DIR}/pwmfb_core1_mp.c
    ${CMAKE_CURRENT_LIST_DIR}/pwmfb_core1_task.c
)

target_include_directories(usermod_pwmfb_core1 INTERFACE
    ${CMAKE_CURRENT_LIST_DIR}
)

target_link_libraries(usermod INTERFACE usermod_pwmfb_core1)
