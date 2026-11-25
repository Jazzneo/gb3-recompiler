// SPDX-License-Identifier: GPL-2.0-or-later
// GUNDAM BREAKER 3 BREAK EDITION (CUSA07651): its profile (profile.cpp) places the temporal
// upscaler and frame generation in its frame.
#include "game_profile.h"

namespace Game {

extern const Profile Gb3Profile;

namespace {
constexpr const char* Serials[] = {"CUSA07651"};
} // namespace

extern const Title Gb3Title = {
    .sz_name = "GUNDAM BREAKER 3 BREAK EDITION",
    .serials = Serials,
    .p_profile = &Gb3Profile,
};

} // namespace Game
