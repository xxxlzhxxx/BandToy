#pragma once

#include "driver/gpio.h"

namespace bandtoy {

constexpr gpio_num_t kStatusLedPin = GPIO_NUM_NC;
constexpr gpio_num_t kPlayButtonPin = GPIO_NUM_0;

constexpr gpio_num_t kBox3DisplayMosiPin = GPIO_NUM_6;
constexpr gpio_num_t kBox3DisplaySclkPin = GPIO_NUM_7;
constexpr gpio_num_t kBox3DisplayCsPin = GPIO_NUM_5;
constexpr gpio_num_t kBox3DisplayDcPin = GPIO_NUM_4;
constexpr gpio_num_t kBox3DisplayResetPin = GPIO_NUM_48;
constexpr gpio_num_t kBox3DisplayBacklightPin = GPIO_NUM_47;
constexpr int kBox3DisplayWidth = 320;
constexpr int kBox3DisplayHeight = 240;

constexpr gpio_num_t kBox3AudioMclkPin = GPIO_NUM_2;
constexpr gpio_num_t kBox3AudioBclkPin = GPIO_NUM_17;
constexpr gpio_num_t kBox3AudioWsPin = GPIO_NUM_45;
constexpr gpio_num_t kBox3AudioDoutPin = GPIO_NUM_15;
constexpr gpio_num_t kBox3AudioDinPin = GPIO_NUM_16;
constexpr gpio_num_t kBox3AudioPaPin = GPIO_NUM_46;
constexpr gpio_num_t kBox3AudioI2cSdaPin = GPIO_NUM_8;
constexpr gpio_num_t kBox3AudioI2cSclPin = GPIO_NUM_18;

constexpr uint32_t kBox3AudioSampleRate = 24000;

}  // namespace bandtoy
