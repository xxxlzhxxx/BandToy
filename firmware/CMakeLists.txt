cmake_minimum_required(VERSION 3.16)

set(COMPONENTS main)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(bandtoy)

spiffs_create_partition_image(assets assets FLASH_IN_PROJECT)
