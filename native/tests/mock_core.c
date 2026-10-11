/* SPDX-License-Identifier: GPL-2.0-or-later
 * Test-only libretro core: exercises the frontend ABI without ARM hardware.
 * This is never packaged as the game core. */
#include "../libretro.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static retro_environment_t env;
static retro_video_refresh_t video;
static retro_input_poll_t poll;
static retro_input_state_t input;
static retro_audio_sample_batch_t audio;
static unsigned frame;
static uint16_t pixels[160][247];

unsigned retro_api_version(void) { return RETRO_API_VERSION; }
void retro_set_environment(retro_environment_t cb) { env=cb; }
void retro_set_video_refresh(retro_video_refresh_t cb) { video=cb; }
void retro_set_audio_sample(retro_audio_sample_t cb) { (void)cb; }
void retro_set_audio_sample_batch(retro_audio_sample_batch_t cb) { audio=cb; }
void retro_set_input_poll(retro_input_poll_t cb) { poll=cb; }
void retro_set_input_state(retro_input_state_t cb) { input=cb; }
void retro_set_controller_port_device(unsigned port,unsigned device) { (void)port;(void)device; }
void retro_get_system_info(struct retro_system_info *info)
{
    memset(info,0,sizeof(*info));info->library_name="gpSP";
    info->library_version="test-only";info->valid_extensions="gba";
}
void retro_get_system_av_info(struct retro_system_av_info *info)
{
    memset(info,0,sizeof(*info));info->geometry.base_width=240;
    info->geometry.base_height=160;info->timing.fps=59.72750057;
    info->timing.sample_rate=32768;
}
void retro_init(void) { frame=0; }
void retro_deinit(void) {}
bool retro_load_game(const struct retro_game_info *game)
{
    static const char *keys[]={"gpsp_bios","gpsp_boot_mode","gpsp_frameskip",
        "gpsp_frameskip_threshold","gpsp_frameskip_interval","gpsp_color_correction",
        "gpsp_frame_mixing","gpsp_save_method","gpsp_drc","gpsp_turbo_period"};
    static const char *values[]={"builtin","game","disabled","33","1",
        "disabled","disabled","libretro","enabled","4"};
    enum retro_pixel_format fmt=RETRO_PIXEL_FORMAT_RGB565;
    unsigned i;
    if(getenv("MOCK_CORE_STDOUT")) {
        puts("config_path is : /test-only/game_config.txt"); fflush(stdout);
    }
    if(!game->data || !game->size || getenv("MOCK_FAIL_LOAD")) return false;
    for(i=0;i<sizeof(keys)/sizeof(keys[0]);i++) {
        struct retro_variable var={keys[i],NULL};
        if(!env(RETRO_ENVIRONMENT_GET_VARIABLE,&var) || strcmp(var.value,values[i])) return false;
    }
    return env(RETRO_ENVIRONMENT_SET_PIXEL_FORMAT,&fmt);
}
void retro_unload_game(void) {}
void retro_run(void)
{
    int16_t samples[16]={0};
    unsigned x,y;
    uint16_t tint=0;
    poll();
    if(input(0,RETRO_DEVICE_JOYPAD,0,RETRO_DEVICE_ID_JOYPAD_UP)) tint|=0xf800;
    if(input(0,RETRO_DEVICE_JOYPAD,0,RETRO_DEVICE_ID_JOYPAD_A)) tint|=0x07e0;
    if(input(0,RETRO_DEVICE_JOYPAD,0,RETRO_DEVICE_ID_JOYPAD_START)) tint|=0x001f;
    for(y=0;y<160;y++) for(x=0;x<240;x++) pixels[y][x]=0xffff;
    for(y=0;y<8;y++) for(x=0;x<8;x++) pixels[y][x]=tint;
    pixels[159][frame%240]=0;
    video(pixels,getenv("MOCK_BAD_VIDEO")?239:240,160,sizeof(pixels[0]));
    audio(samples,8);frame++;
}
