idf_component_register(
    SRCS
        "main.cpp"
        "song_runtime.cpp"
        "box3_audio_output.cpp"
        "display_signals.cpp"
        "recognition_client.cpp"
        "device_sync.cpp"
        "life_signals.cpp"
    INCLUDE_DIRS "."
    REQUIRES
        esp_driver_gpio
        esp_driver_i2c
        esp_driver_i2s
        esp_driver_spi
        esp_codec_dev
        esp_event
        esp_http_client
        esp_lcd
        esp_lcd_ili9341
        esp_netif
        esp_timer
        esp_wifi
        nvs_flash
)

if(NOT DEFINED BANDTOY_ROLE)
    set(BANDTOY_ROLE "follower")
endif()

if(BANDTOY_ROLE STREQUAL "leader")
    target_compile_definitions(${COMPONENT_LIB} PRIVATE BANDTOY_ROLE_LEADER=1)
else()
    target_compile_definitions(${COMPONENT_LIB} PRIVATE BANDTOY_ROLE_LEADER=0)
endif()

message(STATUS "BandToy role: ${BANDTOY_ROLE}")
