// SPDX-License-Identifier: GPL-2.0-or-later
// GUNDAM BREAKER 3 BREAK EDITION (CUSA07651): what the translator knows about it
// (Game::Profile; its title is title.cpp): where the temporal upscaler and frame generation go
// in its frame.
//
// Scene combine: compute shader 0x11f684d5, the pass that reads the 1920x1080 scene colour
// (B10G11R11), the lighting buffer, the main depth and the R16G16Snorm buffer and writes the
// full-size image the post chain consumes (frame capture pass #40).
// UI trigger, camera constants and bone palettes: not identified yet (zeros); the upscaler runs
// without motion vectors and passes the scene through at its own resolution until they are.
#include "game_profile.h"

namespace Game {

extern const Profile Gb3Profile = {
    .upscaler =
        {
            .scene_combine_shader = 0x11f684d5,
        },
};

} // namespace Game
