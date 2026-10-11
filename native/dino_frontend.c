/* SPDX-License-Identifier: GPL-2.0-or-later
 * Copyright (C) 2026 Dino frontend contributors
 *
 * A small libretro host for the unmodified SeedConsole gpSP core and Dino ROM.
 * No save RAM, state, configuration or game file is written. Only explicit
 * headless capture requests write files. libretro.h retains its MIT notice.
 * The ST7789 init values follow the MIT-licensed st7789_mpy.py by Russ Hughes
 * (2020-2023) and Ivan Belokobylskiy (2019); see NOTICE.txt.
 */
#define _POSIX_C_SOURCE 200809L
#include "libretro.h"
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <limits.h>
#include <signal.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>
#include <math.h>
#ifdef __linux__
#include <linux/spi/spidev.h>
#include <sys/ioctl.h>
#endif

#ifndef DINO_LCD_WIDTH
#define DINO_LCD_WIDTH 320
#endif
#if DINO_LCD_WIDTH != 240 && DINO_LCD_WIDTH != 320
#error "DINO_LCD_WIDTH must be 240 (regular) or 320 (Plus)"
#endif
#define LCD_W DINO_LCD_WIDTH
#define LCD_H 240
#define GBA_W 240
#define GBA_H 160
#define VIEW_H (LCD_W * GBA_H / GBA_W)
#define VIEW_Y ((LCD_H - VIEW_H) / 2)
#define TILE_W 16
#define TILE_H 8
#define TILE_COLS (LCD_W / TILE_W)
#define TILE_ROWS (LCD_H / TILE_H)
#define MAX_RECTS (TILE_COLS * TILE_ROWS)
#define MAX_FRAME_BYTES (LCD_W * LCD_H * 2 + MAX_RECTS * 11)
#define MAX_EVENTS 4096
#define NS_SECOND UINT64_C(1000000000)
#define HOLD_NS (2 * NS_SECOND)
#define RELEASE_NS UINT64_C(80000000)
#define SPI_SPEED UINT32_C(25000000)
#define SPI_CHUNK 4096
#define EXIT_UNLOCK 42
#define PRESENT_INTERVAL_NS UINT64_C(33333333)
#define MAX_GAME_LAG_NS UINT64_C(250000000)

enum button {
    B_UP = 1 << 0, B_DOWN = 1 << 1, B_LEFT = 1 << 2,
    B_RIGHT = 1 << 3, B_CENTER = 1 << 4, B_KEY1 = 1 << 5,
    B_KEY2 = 1 << 6, B_KEY3 = 1 << 7
};
static const unsigned button_pins[] = {6, 19, 5, 26, 13, 21, 20, 16};
enum { PIN_DC = 25, PIN_RESET = 27, PIN_BL = 24 };

struct gate {
    uint64_t hold_start, release_start, previous;
    bool holding, releasing, latched, complete, has_previous;
};
struct axis { unsigned lo, hi, weight; };
struct rect { unsigned x, y, w, h; };
struct event { unsigned long start, end; unsigned buttons; };
struct hardware {
    int spi_fd, gpio_fd;
    volatile uint32_t *gpio;
    uint32_t owned_mask, original_fsel[3];
    bool configured;
};
struct core_api {
    void *handle;
    unsigned (*api_version)(void);
    void (*set_environment)(retro_environment_t);
    void (*set_video_refresh)(retro_video_refresh_t);
    void (*set_audio_sample)(retro_audio_sample_t);
    void (*set_audio_sample_batch)(retro_audio_sample_batch_t);
    void (*set_input_poll)(retro_input_poll_t);
    void (*set_input_state)(retro_input_state_t);
    void (*set_controller_port_device)(unsigned, unsigned);
    void (*get_system_info)(struct retro_system_info *);
    void (*get_system_av_info)(struct retro_system_av_info *);
    void (*init)(void);
    void (*deinit)(void);
    bool (*load_game)(const struct retro_game_info *);
    void (*unload_game)(void);
    void (*run)(void);
};
struct frontend {
    struct hardware hw;
    int bridge_output;
    struct gate gate;
    struct axis xs[LCD_W], ys[VIEW_H];
    uint16_t pixels[LCD_W * LCD_H], previous[LCD_W * LCD_H];
    uint16_t raw[GBA_W * GBA_H];
    struct event events[MAX_EVENTS];
    size_t event_count;
    unsigned buttons;
    unsigned long frame, frame_limit, capture_every;
    uint64_t video_frames, audio_frames, rects, bytes, dirty_pixels;
    uint64_t presented_frames, suppressed_frames, discarded_clock_frames;
    uint64_t max_lag_ns, input_requests;
    uint64_t max_frame_bytes, max_steady_frame_bytes, over_wire_budget;
    uint64_t steady_frames;
    uint32_t byte_histogram[MAX_FRAME_BYTES + 1];
    double fps;
    bool headless, realtime, bridge, initialized_pixels, got_video, fatal, unlock;
    bool suppress_presentation;
    bool pixel_format, core_shutdown;
    unsigned option_reads;
    const char *core_path, *rom_path, *script_path, *capture_dir;
};
static struct frontend app;
static volatile sig_atomic_t interrupted;
static unsigned entry_chord = B_KEY1 | B_KEY3;
static uint64_t entry_hold_ns = HOLD_NS;

static uint64_t now_ns(void)
{
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) return 0;
    return (uint64_t)ts.tv_sec * NS_SECOND + (uint64_t)ts.tv_nsec;
}

static void sleep_ns(uint64_t ns)
{
    struct timespec ts = {(time_t)(ns / NS_SECOND), (long)(ns % NS_SECOND)};
    while (nanosleep(&ts, &ts) && errno == EINTR && !interrupted) {}
}

static void on_signal(int sig) { interrupted = sig; }

static bool gate_update(struct gate *g, uint64_t now, unsigned buttons)
{
    const unsigned chord = entry_chord;
    if (g->has_previous && now < g->previous) memset(g, 0, sizeof(*g));
    g->previous = now;
    g->has_previous = true;
    if (g->complete) return true;
    if (!g->latched) {
        if ((buttons & chord) != chord) g->holding = false;
        else if (!g->holding) { g->holding = true; g->hold_start = now; }
        else if (now - g->hold_start >= entry_hold_ns) g->latched = true;
    }
    if (g->latched) {
        if (buttons) g->releasing = false;
        else if (!g->releasing) { g->releasing = true; g->release_start = now; }
        else if (now - g->release_start >= RELEASE_NS) g->complete = true;
    }
    return g->complete;
}

/* Pixel-centre, clamp-to-edge sampling. Preserve the 3:2 GBA aspect ratio on
 * either the regular 240x240 panel or the Plus 320x240 panel.
 * Linux RetroArch's video_smooth default is false: preserve nearest filtering. */
static void prepare_axis(struct axis *axis, unsigned dest, unsigned src)
{
    unsigned x;
    for (x = 0; x < dest; x++) {
        int64_t p = (((int64_t)(2 * x + 1) * src) << 15) / dest - 32768;
        if (p <= 0) axis[x] = (struct axis){0, 0, 0};
        else if (p >= (int64_t)(src - 1) * 65536)
            axis[x] = (struct axis){src - 1, src - 1, 0};
        else axis[x] = (struct axis){(unsigned)(p >> 16),
            (unsigned)(p >> 16) + 1, (unsigned)p & 65535};
    }
}

static void scale_frame(const void *data, size_t pitch, uint16_t *dst,
                        const struct axis *xs, const struct axis *ys)
{
    unsigned y, x;
    for (y = 0; y < VIEW_H; y++) {
        unsigned sy = ys[y].weight >= 32768 ? ys[y].hi : ys[y].lo;
        const uint16_t *row = (const uint16_t *)((const uint8_t *)data + sy * pitch);
        uint16_t *out = dst + (y + VIEW_Y) * LCD_W;
        for (x = 0; x < LCD_W; x++) {
            struct axis s = xs[x];
            out[x] = row[s.weight >= 32768 ? s.hi : s.lo];
        }
    }
}

/* Dirty 16x8 tiles coalesce horizontally, then vertically where spans match.
 * This keeps sparse score/dino/ground movement from transmitting the entire
 * 153600-byte LCD image, while bounding every write inside the physical panel. */
static size_t dirty_rects(const uint16_t *pixels, const uint16_t *previous,
                         bool initialized, struct rect *rects)
{
    bool dirty[TILE_ROWS][TILE_COLS];
    size_t count = 0;
    unsigned ty, tx, y, x;
    if (!initialized) { rects[0] = (struct rect){0, 0, LCD_W, LCD_H}; return 1; }
    memset(dirty, 0, sizeof(dirty));
    for (ty = 0; ty < TILE_ROWS; ty++) for (tx = 0; tx < TILE_COLS; tx++) {
        for (y = ty * TILE_H; y < (ty + 1) * TILE_H; y++) {
            size_t offset = y * LCD_W + tx * TILE_W;
            if (memcmp(pixels + offset, previous + offset, TILE_W * sizeof(uint16_t))) {
                dirty[ty][tx] = true; break;
            }
        }
    }
    for (ty = 0; ty < TILE_ROWS; ty++) for (tx = 0; tx < TILE_COLS;) {
        unsigned first, end, last;
        if (!dirty[ty][tx]) { tx++; continue; }
        first = tx;
        while (tx < TILE_COLS && dirty[ty][tx]) tx++;
        end = tx;
        last = ty + 1;
        while (last < TILE_ROWS) {
            bool same = (first == 0 || !dirty[last][first - 1]) &&
                        (end == TILE_COLS || !dirty[last][end]);
            for (x = first; x < end; x++) if (!dirty[last][x]) same = false;
            if (!same) break;
            for (x = first; x < end; x++) dirty[last][x] = false;
            last++;
        }
        rects[count++] = (struct rect){first * TILE_W, ty * TILE_H,
                                      (end - first) * TILE_W, (last - ty) * TILE_H};
    }
    return count;
}

static bool rect_valid(struct rect r)
{
    return r.w && r.h && r.x < LCD_W && r.y < LCD_H &&
           r.w <= LCD_W - r.x && r.h <= LCD_H - r.y;
}

static void pack565(uint8_t *dst, const uint16_t *src, size_t n)
{
    size_t i;
    for (i = 0; i < n; i++) { dst[2*i] = src[i] >> 8; dst[2*i+1] = src[i] & 255; }
}

/* The production bridge delegates GPIO/SPI to the same Python driver that the
 * first image used successfully. Only packed dirty rectangles cross the pipe;
 * emulation, scaling and pixel differences stay native. Every frame is ACKed
 * after the display write, preventing queued frames from adding input latency. */
static int bridge_write(const void *data, size_t size)
{
    const uint8_t *p = data;
    while (size) {
        ssize_t n = write(app.bridge_output, p, size);
        if (n < 0 && errno == EINTR && !interrupted) continue;
        if (n <= 0) return -1;
        p += n; size -= (size_t)n;
    }
    return 0;
}

static int bridge_reply(uint8_t *reply)
{
    ssize_t n;
    do { n = read(STDIN_FILENO, reply, 1); }
    while (n < 0 && errno == EINTR && !interrupted);
    if (n != 1) { if (n == 0) errno = EPIPE; return -1; }
    return 0;
}

static int bridge_input(void)
{
    uint8_t buttons;
    if (bridge_write("INP1", 4) || bridge_reply(&buttons)) return -1;
    app.input_requests++;
    app.buttons = buttons;
    return 0;
}

static int bridge_frame(const struct rect *rects, size_t count)
{
    static uint8_t packet[MAX_FRAME_BYTES + 6];
    uint8_t ack;
    size_t i, used = 6;
    unsigned y;
    if (count > MAX_RECTS) { errno = EINVAL; return -1; }
    memcpy(packet, "FRM1", 4);
    packet[4] = (uint8_t)(count >> 8); packet[5] = (uint8_t)count;
    for (i = 0; i < count; i++) {
        struct rect r = rects[i];
        uint8_t *header;
        if (!rect_valid(r)) { errno = EINVAL; return -1; }
        if (used + 8 + (size_t)r.w * r.h * 2 > sizeof(packet)) {
            errno = EOVERFLOW; return -1;
        }
        header = packet + used;
        header[0] = r.x >> 8; header[1] = r.x & 255;
        header[2] = r.y >> 8; header[3] = r.y & 255;
        header[4] = r.w >> 8; header[5] = r.w & 255;
        header[6] = r.h >> 8; header[7] = r.h & 255;
        used += 8;
        for (y = r.y; y < r.y + r.h; y++) {
            pack565(packet + used, app.pixels + y * LCD_W + r.x, r.w);
            used += r.w * 2;
        }
    }
    if (bridge_write(packet, used)) return -1;
    if (bridge_reply(&ack)) return -1;
    if (ack) { errno = EPROTO; return -1; }
    return 0;
}

static void gpio_output(struct hardware *hw, unsigned pin, bool high)
{
    hw->gpio[high ? 7 : 10] = UINT32_C(1) << pin;
}

static void gpio_function(struct hardware *hw, unsigned pin, unsigned fn)
{
    unsigned index = pin / 10, shift = (pin % 10) * 3;
    uint32_t value = hw->gpio[index];
    hw->gpio[index] = (value & ~(UINT32_C(7) << shift)) | (fn << shift);
}

static void gpio_pull(struct hardware *hw, uint32_t mask, unsigned pull)
{
    hw->gpio[37] = pull;
    sleep_ns(10000); /* Pi0 requires >=150 peripheral clocks, not CPU clocks. */
    hw->gpio[38] = mask;
    sleep_ns(10000);
    hw->gpio[37] = 0;
    hw->gpio[38] = 0;
}

static int spi_write(struct hardware *hw, const void *data, size_t size)
{
    const uint8_t *ptr = data;
    while (size) {
        size_t n = size > SPI_CHUNK ? SPI_CHUNK : size;
        ssize_t written = write(hw->spi_fd, ptr, n);
        if (written < 0 && errno == EINTR && !interrupted) continue;
        if (written != (ssize_t)n) { if (written >= 0) errno = EIO; return -1; }
        ptr += n; size -= n;
    }
    return 0;
}

static int lcd_command(struct hardware *hw, uint8_t command, const uint8_t *data, size_t size)
{
    gpio_output(hw, PIN_DC, false);
    if (spi_write(hw, &command, 1)) return -1;
    if (size) {
        gpio_output(hw, PIN_DC, true);
        if (spi_write(hw, data, size)) return -1;
    }
    return 0;
}

static int lcd_rect(struct hardware *hw, const uint16_t *pixels, struct rect r)
{
    uint8_t pos[4], buffer[SPI_CHUNK];
    unsigned y, x, used = 0;
    if (!rect_valid(r)) { errno = EINVAL; return -1; }
    pos[0] = r.x >> 8; pos[1] = r.x & 255;
    pos[2] = (r.x + r.w - 1) >> 8; pos[3] = (r.x + r.w - 1) & 255;
    if (lcd_command(hw, 0x2a, pos, 4)) return -1;
    pos[0] = r.y >> 8; pos[1] = r.y & 255;
    pos[2] = (r.y + r.h - 1) >> 8; pos[3] = (r.y + r.h - 1) & 255;
    if (lcd_command(hw, 0x2b, pos, 4) || lcd_command(hw, 0x2c, NULL, 0)) return -1;
    gpio_output(hw, PIN_DC, true);
    for (y = r.y; y < r.y + r.h; y++) for (x = r.x; x < r.x + r.w; x++) {
        uint16_t pixel = pixels[y * LCD_W + x];
        buffer[used++] = pixel >> 8; buffer[used++] = pixel & 255;
        if (used == sizeof(buffer)) {
            if (spi_write(hw, buffer, used)) return -1;
            used = 0;
        }
    }
    return used ? spi_write(hw, buffer, used) : 0;
}

static int lcd_init(struct hardware *hw)
{
    static const struct { uint8_t command, length, delay; uint8_t data[14]; } init[] = {
        {0x11,1,120,{0}}, {0x13,1,0,{0}}, {0xb6,2,0,{0x0a,0x82}},
        {0x3a,1,10,{0x55}}, {0xb2,5,0,{0x0c,0x0c,0,0x33,0x33}},
        {0xb7,1,0,{0x35}}, {0xbb,1,0,{0x28}}, {0xc0,1,0,{0x0c}},
        {0xc2,2,0,{0x01,0xff}}, {0xc3,1,0,{0x10}}, {0xc4,1,0,{0x20}},
        {0xc6,1,0,{0x0f}}, {0xd0,2,0,{0xa4,0xa1}},
        {0xe0,14,0,{0xd0,0,2,7,0x0a,0x28,0x32,0x44,0x42,6,0x0e,0x12,0x14,0x17}},
        {0xe1,14,0,{0xd0,0,2,7,0x0a,0x28,0x31,0x54,0x47,0x0e,0x1c,0x17,0x1b,0x1e}},
        {0x21,1,0,{0}}, {0x29,1,120,{0}}
    };
    unsigned pass, i;
    uint8_t madctl = 0x68;
    gpio_output(hw, PIN_BL, false);
    gpio_output(hw, PIN_RESET, true); sleep_ns(10000000);
    gpio_output(hw, PIN_RESET, false); sleep_ns(10000000);
    gpio_output(hw, PIN_RESET, true); sleep_ns(120000000);
    for (pass = 0; pass < 2; pass++) for (i = 0; i < sizeof(init)/sizeof(init[0]); i++) {
        if (lcd_command(hw, init[i].command, init[i].data, init[i].length)) return -1;
        if (init[i].delay) sleep_ns((uint64_t)init[i].delay * 1000000);
    }
    if (lcd_command(hw, 0x36, &madctl, 1) ||
        lcd_rect(hw, app.pixels, (struct rect){0,0,LCD_W,LCD_H})) return -1;
    gpio_output(hw, PIN_BL, true);
    return 0;
}

static int hardware_open(struct hardware *hw)
{
#ifdef __linux__
    unsigned i;
    uint8_t mode = SPI_MODE_0, bits = 8, read_mode = 255, read_bits = 0;
    uint32_t speed = SPI_SPEED, read_speed = 0;
    hw->gpio_fd = open("/dev/gpiomem", O_RDWR | O_SYNC);
    if (hw->gpio_fd < 0) return -1;
    hw->gpio = mmap(NULL, 4096, PROT_READ | PROT_WRITE, MAP_SHARED, hw->gpio_fd, 0);
    if (hw->gpio == MAP_FAILED) { hw->gpio = NULL; return -1; }
    close(hw->gpio_fd); hw->gpio_fd = -1;
    hw->owned_mask = (UINT32_C(1) << PIN_DC) | (UINT32_C(1) << PIN_RESET) | (UINT32_C(1) << PIN_BL);
    for (i = 0; i < 8; i++) hw->owned_mask |= UINT32_C(1) << button_pins[i];
    for (i = 0; i < 3; i++) hw->original_fsel[i] = hw->gpio[i];
    hw->configured = true;
    for (i = 0; i < 8; i++) gpio_function(hw, button_pins[i], 0);
    gpio_pull(hw, hw->owned_mask & ~((UINT32_C(1) << PIN_DC) | (UINT32_C(1) << PIN_RESET) | (UINT32_C(1) << PIN_BL)), 2);
    gpio_function(hw, PIN_DC, 1); gpio_function(hw, PIN_RESET, 1); gpio_function(hw, PIN_BL, 1);
    gpio_output(hw, PIN_BL, false);
    /* SPI pins are already configured by the kernel; never alter their FSEL. */
    hw->spi_fd = open("/dev/spidev0.0", O_RDWR);
    if (hw->spi_fd < 0) return -1;
    if (ioctl(hw->spi_fd, SPI_IOC_WR_MODE, &mode) ||
        ioctl(hw->spi_fd, SPI_IOC_WR_BITS_PER_WORD, &bits) ||
        ioctl(hw->spi_fd, SPI_IOC_WR_MAX_SPEED_HZ, &speed) ||
        ioctl(hw->spi_fd, SPI_IOC_RD_MODE, &read_mode) ||
        ioctl(hw->spi_fd, SPI_IOC_RD_BITS_PER_WORD, &read_bits) ||
        ioctl(hw->spi_fd, SPI_IOC_RD_MAX_SPEED_HZ, &read_speed)) return -1;
    if (read_mode != mode || read_bits != bits || read_speed != speed) { errno = EIO; return -1; }
    return lcd_init(hw);
#else
    (void)hw; (void)gpio_function; (void)lcd_init; errno = ENOTSUP; return -1;
#endif
}

static void hardware_close(struct hardware *hw)
{
    unsigned pin, reg;
    if (hw->gpio && hw->configured) {
        gpio_output(hw, PIN_BL, false);
        gpio_pull(hw, hw->owned_mask, 0);
        for (reg = 0; reg < 3; reg++) {
            uint32_t mask = 0;
            for (pin = reg * 10; pin < reg * 10 + 10; pin++)
                if (hw->owned_mask & (UINT32_C(1) << pin)) mask |= UINT32_C(7) << ((pin % 10) * 3);
            hw->gpio[reg] = (hw->gpio[reg] & ~mask) | (hw->original_fsel[reg] & mask);
        }
    }
    if (hw->spi_fd >= 0) { close(hw->spi_fd); hw->spi_fd = -1; }
    if (hw->gpio) { munmap((void *)hw->gpio, 4096); hw->gpio = NULL; }
    if (hw->gpio_fd >= 0) { close(hw->gpio_fd); hw->gpio_fd = -1; }
}

static unsigned read_buttons(void)
{
    unsigned buttons = 0, i;
    if (app.bridge) return app.buttons;
    if (app.headless) {
        size_t e;
        for (e = 0; e < app.event_count; e++)
            if (app.frame >= app.events[e].start && app.frame < app.events[e].end)
                buttons |= app.events[e].buttons;
    } else {
        uint32_t levels = app.hw.gpio[13];
        for (i = 0; i < 8; i++) if (!(levels & (UINT32_C(1) << button_pins[i]))) buttons |= 1u << i;
    }
    return buttons;
}

static void poll_input(void)
{
    uint64_t time = app.headless && !app.realtime ?
        (uint64_t)((double)app.frame * 1e9 / app.fps) : now_ns();
    app.buttons = read_buttons();
    if (gate_update(&app.gate, time, app.buttons)) app.unlock = true;
}

static int16_t input_state(unsigned port, unsigned device, unsigned index, unsigned id)
{
    unsigned mask = 0;
    bool suppress_chord = app.gate.latched ||
        (app.buttons & entry_chord) == entry_chord;
    unsigned buttons = suppress_chord ? app.buttons & ~entry_chord : app.buttons;
    if (port || device != RETRO_DEVICE_JOYPAD || index) return 0;
    if (buttons & B_UP) mask |= 1 << RETRO_DEVICE_ID_JOYPAD_UP;
    if (buttons & B_DOWN) mask |= 1 << RETRO_DEVICE_ID_JOYPAD_DOWN;
    if (buttons & B_LEFT) mask |= 1 << RETRO_DEVICE_ID_JOYPAD_LEFT;
    if (buttons & B_RIGHT) mask |= 1 << RETRO_DEVICE_ID_JOYPAD_RIGHT;
    if (buttons & B_CENTER) mask |= 1 << RETRO_DEVICE_ID_JOYPAD_SELECT;
    if (buttons & B_KEY1) mask |= 1 << RETRO_DEVICE_ID_JOYPAD_A;
    if (buttons & B_KEY2) mask |= 1 << RETRO_DEVICE_ID_JOYPAD_B;
    if (buttons & B_KEY3) mask |= 1 << RETRO_DEVICE_ID_JOYPAD_START;
    /* Original SeedConsole KEY3 is GBA START, never a standalone emulator exit.
     * Suppress every configured entry button, including directional chords. */
    if (id == RETRO_DEVICE_ID_JOYPAD_MASK) return (int16_t)mask;
    return id < 16 ? !!(mask & (1u << id)) : 0;
}

static void core_log(enum retro_log_level level, const char *fmt, ...)
{
    va_list args;
    (void)level;
    va_start(args, fmt); vfprintf(stderr, fmt, args); va_end(args);
}

struct option { const char *key, *value; };
static const struct option options[] = {
    {"gpsp_bios", "builtin"}, {"gpsp_boot_mode", "game"},
    {"gpsp_frameskip", "disabled"}, {"gpsp_frameskip_threshold", "33"},
    {"gpsp_frameskip_interval", "1"}, {"gpsp_color_correction", "disabled"},
    {"gpsp_frame_mixing", "disabled"}, {"gpsp_save_method", "libretro"},
    {"gpsp_drc", "enabled"}, {"gpsp_turbo_period", "4"}
};

static bool environment(unsigned cmd, void *data)
{
    switch (cmd) {
    case RETRO_ENVIRONMENT_GET_VARIABLE: {
        struct retro_variable *v = data;
        unsigned i;
        v->value = NULL;
        for (i = 0; i < sizeof(options)/sizeof(options[0]); i++) if (!strcmp(v->key, options[i].key)) {
            v->value = options[i].value; app.option_reads |= 1u << i; return true;
        }
        return false;
    }
    case RETRO_ENVIRONMENT_GET_VARIABLE_UPDATE: *(bool *)data = false; return true;
    case RETRO_ENVIRONMENT_GET_CORE_OPTIONS_VERSION: *(unsigned *)data = 1; return true;
    case RETRO_ENVIRONMENT_SET_CORE_OPTIONS:
    case RETRO_ENVIRONMENT_SET_CORE_OPTIONS_INTL:
    case RETRO_ENVIRONMENT_SET_VARIABLES:
    case RETRO_ENVIRONMENT_SET_INPUT_DESCRIPTORS:
    case RETRO_ENVIRONMENT_SET_CONTROLLER_INFO:
    case RETRO_ENVIRONMENT_SET_MEMORY_MAPS:
    case RETRO_ENVIRONMENT_SET_SUPPORT_NO_GAME:
    case RETRO_ENVIRONMENT_SET_MINIMUM_AUDIO_LATENCY: return true;
    case RETRO_ENVIRONMENT_SET_PIXEL_FORMAT:
        app.pixel_format = *(enum retro_pixel_format *)data == RETRO_PIXEL_FORMAT_RGB565;
        return app.pixel_format;
    case RETRO_ENVIRONMENT_GET_CAN_DUPE: *(bool *)data = true; return true;
    case RETRO_ENVIRONMENT_GET_INPUT_BITMASKS: return true;
    case RETRO_ENVIRONMENT_GET_LANGUAGE: *(unsigned *)data = RETRO_LANGUAGE_ENGLISH; return true;
    case RETRO_ENVIRONMENT_GET_LOG_INTERFACE:
        ((struct retro_log_callback *)data)->log = core_log; return true;
    case RETRO_ENVIRONMENT_GET_SYSTEM_DIRECTORY:
        *(const char **)data = "/nonexistent/dino-system"; return true;
    case RETRO_ENVIRONMENT_GET_SAVE_DIRECTORY:
        *(const char **)data = "/nonexistent/dino-save"; return true;
    case RETRO_ENVIRONMENT_GET_LIBRETRO_PATH: *(const char **)data = app.core_path; return true;
    case RETRO_ENVIRONMENT_GET_FASTFORWARDING: *(bool *)data = false; return true;
    case RETRO_ENVIRONMENT_GET_AUDIO_VIDEO_ENABLE: *(int *)data = 3; return true;
    case RETRO_ENVIRONMENT_GET_MESSAGE_INTERFACE_VERSION: *(unsigned *)data = 1; return true;
    case RETRO_ENVIRONMENT_SET_MESSAGE:
        fprintf(stderr, "core: %s\n", ((struct retro_message *)data)->msg); return true;
    case RETRO_ENVIRONMENT_SET_MESSAGE_EXT:
        fprintf(stderr, "core: %s\n", ((struct retro_message_ext *)data)->msg); return true;
    case RETRO_ENVIRONMENT_SET_ROTATION: return *(unsigned *)data == 0;
    case RETRO_ENVIRONMENT_SHUTDOWN: app.core_shutdown = true; return true;
    default: return false;
    }
}

static size_t audio_batch(const int16_t *data, size_t frames)
{
    (void)data; app.audio_frames += frames; return frames;
}
static void audio_sample(int16_t left, int16_t right)
{
    (void)left; (void)right; app.audio_frames++;
}

static void video_refresh(const void *data, unsigned width, unsigned height, size_t pitch)
{
    struct rect rects[MAX_RECTS];
    size_t n, i;
    unsigned y;
    app.video_frames++;
    /* Emulation must keep advancing when the physical display is slower than
     * the core. Leave 'previous' as the last transmitted image, so the next
     * presentation includes every change made during skipped output frames. */
    if (app.suppress_presentation) { app.suppressed_frames++; return; }
    if (!data) {
        /* Even a duplicate frame is acknowledged by the bridge. */
        if (app.bridge && bridge_frame(NULL, 0)) {
            perror("Bridge duplicate frame"); app.fatal = true;
        }
        if (!app.fatal) app.presented_frames++;
        return;
    }
    if (data == RETRO_HW_FRAME_BUFFER_VALID || !app.pixel_format || width != GBA_W ||
        height != GBA_H || pitch < GBA_W * 2 || (pitch & 1)) {
        fprintf(stderr, "Unsupported core video buffer: %ux%u pitch=%zu\n", width, height, pitch);
        app.fatal = true; return;
    }
    if (app.headless) for (y = 0; y < GBA_H; y++)
        memcpy(app.raw + y * GBA_W, (const uint8_t *)data + y * pitch, GBA_W * 2);
    scale_frame(data, pitch, app.pixels, app.xs, app.ys);
    n = dirty_rects(app.pixels, app.previous, app.initialized_pixels, rects);
    if (app.bridge && bridge_frame(rects, n)) {
        perror("Bridge frame write"); app.fatal = true; return;
    }
    for (i = 0; i < n; i++) {
        uint64_t pixels = (uint64_t)rects[i].w * rects[i].h;
        if (!app.headless && !app.bridge && lcd_rect(&app.hw, app.pixels, rects[i])) {
            perror("LCD frame write"); app.fatal = true; return;
        }
        app.rects++; app.dirty_pixels += pixels; app.bytes += pixels * 2 + 11;
    }
    memcpy(app.previous, app.pixels, sizeof(app.previous));
    app.initialized_pixels = true; app.got_video = true;
    app.presented_frames++;
}

static void record_frame_bytes(uint64_t bytes)
{
    if(bytes > app.max_frame_bytes) app.max_frame_bytes = bytes;
    if(app.frame <= 1) return;
    if(bytes > app.max_steady_frame_bytes) app.max_steady_frame_bytes = bytes;
    if(bytes * 8.0 / SPI_SPEED > 1.0 / app.fps) app.over_wire_budget++;
    app.steady_frames++;
    if(bytes <= MAX_FRAME_BYTES) app.byte_histogram[bytes]++;
}

static unsigned percentile95_bytes(void)
{
    uint64_t target = (app.steady_frames * 95 + 99) / 100, count = 0;
    unsigned i;
    if(!target) return 0;
    for(i=0;i<=MAX_FRAME_BYTES;i++) {
        count += app.byte_histogram[i];
        if(count >= target) return i;
    }
    return MAX_FRAME_BYTES;
}

static uint64_t frame_hash(const uint16_t *pixels, size_t count)
{
    uint64_t h = UINT64_C(14695981039346656037);
    size_t i;
    for (i = 0; i < count; i++) {
        h ^= pixels[i] >> 8; h *= UINT64_C(1099511628211);
        h ^= pixels[i] & 255; h *= UINT64_C(1099511628211);
    }
    return h;
}

static int write_ppm(const char *path, const uint16_t *pixels, unsigned w, unsigned h)
{
    FILE *fp = fopen(path, "wb");
    unsigned x, y;
    uint8_t row[LCD_W * 3];
    if (!fp) return -1;
    if (fprintf(fp, "P6\n%u %u\n255\n", w, h) < 0) { fclose(fp); return -1; }
    for (y = 0; y < h; y++) {
        for (x = 0; x < w; x++) {
            uint16_t p = pixels[y * w + x];
            row[x*3] = ((p >> 11) * 255 + 15) / 31;
            row[x*3+1] = (((p >> 5) & 63) * 255 + 31) / 63;
            row[x*3+2] = ((p & 31) * 255 + 15) / 31;
        }
        if (fwrite(row, 3, w, fp) != w) { fclose(fp); return -1; }
    }
    return fclose(fp);
}

static int capture_frame(void)
{
    char path[4096];
    int n = snprintf(path, sizeof(path), "%s/frame-%06lu.ppm", app.capture_dir, app.frame);
    if (n < 0 || (size_t)n >= sizeof(path)) { errno = ENAMETOOLONG; return -1; }
    if (write_ppm(path, app.pixels, LCD_W, LCD_H)) return -1;
    n = snprintf(path, sizeof(path), "%s/raw-%06lu.ppm", app.capture_dir, app.frame);
    if (n < 0 || (size_t)n >= sizeof(path)) { errno = ENAMETOOLONG; return -1; }
    return write_ppm(path, app.raw, GBA_W, GBA_H);
}

static int parse_buttons(char *text, unsigned *buttons)
{
    static const char *names[] = {"UP","DOWN","LEFT","RIGHT","CENTER","KEY1","KEY2","KEY3"};
    char *token, *save = NULL;
    *buttons = 0;
    token = strtok_r(text, "| \t\r\n", &save);
    if (!token) return -1;
    do {
        unsigned i;
        if (!strcmp(token, "NONE")) continue;
        for (i = 0; i < 8; i++) if (!strcmp(token, names[i])) { *buttons |= 1u << i; break; }
        if (i == 8) return -1;
    } while ((token = strtok_r(NULL, "| \t\r\n", &save)));
    return 0;
}

static int load_script(const char *path)
{
    FILE *fp = fopen(path, "r");
    char line[512];
    unsigned lineno = 0;
    if (!fp) return -1;
    while (fgets(line, sizeof(line), fp)) {
        unsigned long first, end;
        int consumed = 0;
        unsigned buttons;
        char *p = line;
        lineno++;
        while (*p == ' ' || *p == '\t') p++;
        if (*p == '#' || *p == '\n' || !*p) continue;
        if (sscanf(p, "%lu,%lu,%n", &first, &end, &consumed) != 2 || !consumed ||
            first >= end || app.event_count == MAX_EVENTS ||
            parse_buttons(p + consumed, &buttons)) {
            fprintf(stderr, "Invalid input script line %u\n", lineno); fclose(fp); errno = EINVAL; return -1;
        }
        app.events[app.event_count++] = (struct event){first,end,buttons};
    }
    if (ferror(fp)) { fclose(fp); return -1; }
    return fclose(fp);
}

static int load_core(struct core_api *c, const char *path)
{
    c->handle = dlopen(path, RTLD_NOW | RTLD_LOCAL);
    if (!c->handle) { fprintf(stderr, "Load core: %s\n", dlerror()); return -1; }
#define LOAD(name) do { \
    void *symbol = dlsym(c->handle, "retro_" #name); \
    if (!symbol) { fprintf(stderr, "Missing core function retro_%s\n", #name); return -1; } \
    memcpy(&c->name, &symbol, sizeof(symbol)); \
} while (0)
    LOAD(api_version); LOAD(set_environment); LOAD(set_video_refresh);
    LOAD(set_audio_sample); LOAD(set_audio_sample_batch); LOAD(set_input_poll);
    LOAD(set_input_state); LOAD(set_controller_port_device); LOAD(get_system_info);
    LOAD(get_system_av_info); LOAD(init); LOAD(deinit); LOAD(load_game);
    LOAD(unload_game); LOAD(run);
#undef LOAD
    if (c->api_version() != RETRO_API_VERSION) { fprintf(stderr, "Wrong libretro API version\n"); return -1; }
    return 0;
}

static int read_rom(const char *path, void **data, size_t *size)
{
    struct stat st;
    FILE *fp;
    if (stat(path, &st) || st.st_size <= 0 || st.st_size > 64 * 1024 * 1024) { errno = EINVAL; return -1; }
    fp = fopen(path, "rb");
    if (!fp) return -1;
    *size = (size_t)st.st_size;
    *data = malloc(*size);
    if (!*data) { fclose(fp); return -1; }
    if (fread(*data, 1, *size, fp) != *size) { fclose(fp); errno = EIO; return -1; }
    return fclose(fp);
}

static int self_test(void)
{
    struct gate g = {0};
    uint16_t *source = calloc(GBA_H * (GBA_W + 7), sizeof(uint16_t));
    uint16_t *dest = calloc(LCD_W * LCD_H, sizeof(uint16_t));
    uint16_t *before = calloc(LCD_W * LCD_H, sizeof(uint16_t));
    struct rect rects[MAX_RECTS];
    uint8_t packed[8];
    uint16_t colors[] = {0xf800,0x07e0,0x001f,0xffff};
    unsigned i, x, y;
    size_t n;
#define CHECK(condition) do { if (!(condition)) { fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#condition); goto fail; } } while (0)
    CHECK(source && dest && before);
    CHECK(!gate_update(&g, 0, B_KEY1 | B_KEY3));
    CHECK(!gate_update(&g, HOLD_NS-1, B_KEY1 | B_KEY3));
    CHECK(!g.latched);
    CHECK(!gate_update(&g, HOLD_NS, B_KEY1 | B_KEY3)); CHECK(g.latched);
    CHECK(!gate_update(&g, HOLD_NS+1, 0));
    CHECK(!gate_update(&g, HOLD_NS+RELEASE_NS, 0));
    CHECK(gate_update(&g, HOLD_NS+RELEASE_NS+1, 0));
    CHECK(gate_update(&g, HOLD_NS+RELEASE_NS+2, B_UP));
    memset(&g, 0, sizeof(g));
    CHECK(!gate_update(&g, 0, B_KEY1 | B_KEY3));
    CHECK(!gate_update(&g, HOLD_NS-1, B_KEY1));
    CHECK(!gate_update(&g, HOLD_NS, B_KEY1 | B_KEY3));
    CHECK(!gate_update(&g, 2*HOLD_NS-1, B_KEY1 | B_KEY3)); CHECK(!g.latched);
    CHECK(!gate_update(&g, 2*HOLD_NS, B_KEY1 | B_KEY3)); CHECK(g.latched);
    CHECK(!gate_update(&g, 2*HOLD_NS+1, B_UP));
    CHECK(!gate_update(&g, 2*HOLD_NS+RELEASE_NS+1, B_UP));
    CHECK(!gate_update(&g, 3*HOLD_NS, 0));
    CHECK(!gate_update(&g, 3*HOLD_NS+RELEASE_NS-1, 0));
    CHECK(!gate_update(&g, 3*HOLD_NS+RELEASE_NS, B_KEY2));
    CHECK(!gate_update(&g, 4*HOLD_NS, 0));
    CHECK(gate_update(&g, 4*HOLD_NS+RELEASE_NS, 0));
    CHECK(!gate_update(&g, 1, 0)); CHECK(!g.complete && !g.latched);
    prepare_axis(app.xs,LCD_W,GBA_W); prepare_axis(app.ys,VIEW_H,GBA_H);
    CHECK(app.xs[0].lo == 0 && app.xs[LCD_W-1].hi == GBA_W-1);
    CHECK(app.ys[0].lo == 0 && app.ys[VIEW_H-1].hi == GBA_H-1);
    for (i = 0; i < 4; i++) {
        for (y = 0; y < GBA_H; y++) for (x = 0; x < GBA_W; x++) source[y*(GBA_W+7)+x]=colors[i];
        memset(dest, 0, LCD_W*LCD_H*2);
        scale_frame(source, (GBA_W+7)*2, dest, app.xs, app.ys);
        for (y = 0; y < LCD_H; y++) for (x = 0; x < LCD_W; x++)
            CHECK(dest[y*LCD_W+x] == (y >= VIEW_Y && y < VIEW_Y+VIEW_H ? colors[i] : 0));
    }
    /* Unique source values prove nearest selection and padded-row addressing. */
    for(y=0;y<GBA_H;y++) for(x=0;x<GBA_W;x++) source[y*(GBA_W+7)+x]=(uint16_t)(y*GBA_W+x);
    scale_frame(source,(GBA_W+7)*2,dest,app.xs,app.ys);
    for(y=0;y<VIEW_H;y++) for(x=0;x<LCD_W;x++) {
        unsigned sx=((2*x+1)*GBA_W)/(2*LCD_W);
        unsigned sy=((2*y+1)*GBA_H)/(2*VIEW_H);
        CHECK(dest[(y+VIEW_Y)*LCD_W+x]==source[sy*(GBA_W+7)+sx]);
    }
    pack565(packed,colors,4);
    CHECK(!memcmp(packed,"\xf8\x00\x07\xe0\x00\x1f\xff\xff",8));
    memset(dest,0,LCD_W*LCD_H*2);
    CHECK(dirty_rects(dest,before,true,rects)==0);
    CHECK(dirty_rects(dest,before,false,rects)==1 && rect_valid(rects[0]));
    dest[0]=1; dest[LCD_W*LCD_H-1]=1;
    n=dirty_rects(dest,before,true,rects); CHECK(n==2);
    for(i=0;i<n;i++) CHECK(rect_valid(rects[i]) && rects[i].w==TILE_W && rects[i].h==TILE_H);
    CHECK(!rect_valid((struct rect){0,0,0,1}));
    CHECK(!rect_valid((struct rect){LCD_W-1,0,2,1}));
    CHECK(!rect_valid((struct rect){0,LCD_H-1,1,2}));
    CHECK(!rect_valid((struct rect){UINT_MAX,0,1,1}));
    /* Random sparse changes must be covered by in-bounds, non-overlapping rects. */
    memset(dest,0,LCD_W*LCD_H*2);
    for (i=0;i<500;i++) dest[(i*7919u)%(LCD_W*LCD_H)]=0xffff;
    n=dirty_rects(dest,before,true,rects); CHECK(n<=MAX_RECTS);
    for (i=0;i<n;i++) {
        CHECK(rect_valid(rects[i]));
        for(y=rects[i].y;y<rects[i].y+rects[i].h;y++) for(x=rects[i].x;x<rects[i].x+rects[i].w;x++) {
            CHECK(before[y*LCD_W+x]==0); before[y*LCD_W+x]=1;
        }
    }
    for(i=0;i<LCD_W*LCD_H;i++) if(dest[i]) CHECK(before[i]);
    app.buttons=B_KEY1|B_KEY2|B_CENTER|B_UP;
    CHECK(input_state(0,RETRO_DEVICE_JOYPAD,0,RETRO_DEVICE_ID_JOYPAD_A));
    CHECK(input_state(0,RETRO_DEVICE_JOYPAD,0,RETRO_DEVICE_ID_JOYPAD_B));
    CHECK(input_state(0,RETRO_DEVICE_JOYPAD,0,RETRO_DEVICE_ID_JOYPAD_SELECT));
    CHECK(!input_state(0,RETRO_DEVICE_JOYPAD,0,RETRO_DEVICE_ID_JOYPAD_START));
    CHECK(!input_state(1,RETRO_DEVICE_JOYPAD,0,RETRO_DEVICE_ID_JOYPAD_A));
    app.buttons=B_KEY3;
    CHECK(input_state(0,RETRO_DEVICE_JOYPAD,0,RETRO_DEVICE_ID_JOYPAD_START));
    app.buttons=B_KEY1|B_KEY3;
    CHECK(!input_state(0,RETRO_DEVICE_JOYPAD,0,RETRO_DEVICE_ID_JOYPAD_START));
    CHECK(!input_state(0,RETRO_DEVICE_JOYPAD,0,RETRO_DEVICE_ID_JOYPAD_A));
    entry_chord=B_UP|B_CENTER; entry_hold_ns=NS_SECOND;
    app.buttons=B_UP|B_CENTER|B_KEY2;
    CHECK(!input_state(0,RETRO_DEVICE_JOYPAD,0,RETRO_DEVICE_ID_JOYPAD_UP));
    CHECK(!input_state(0,RETRO_DEVICE_JOYPAD,0,RETRO_DEVICE_ID_JOYPAD_SELECT));
    CHECK(input_state(0,RETRO_DEVICE_JOYPAD,0,RETRO_DEVICE_ID_JOYPAD_B));
    memset(&g,0,sizeof(g));
    CHECK(!gate_update(&g,0,entry_chord));
    CHECK(!gate_update(&g,NS_SECOND-1,entry_chord)); CHECK(!g.latched);
    CHECK(!gate_update(&g,NS_SECOND,entry_chord)); CHECK(g.latched);
    CHECK(!gate_update(&g,NS_SECOND+1,0));
    CHECK(gate_update(&g,NS_SECOND+RELEASE_NS+1,0));
    free(source);free(dest);free(before);
    puts("{\"self_test\":\"PASS\",\"checks\":[\"hold_release\",\"clock_regression\",\"all_keys_release\",\"padded_pitch\",\"nearest_scaler\",\"rgb565\",\"viewport_bars\",\"dirty_rect_coverage\",\"rectangle_bounds\",\"input_mapping\"]}");
    return 0;
fail:
    free(source);free(dest);free(before);return 1;
#undef CHECK
}

static void usage(const char *name)
{
    fprintf(stderr,"Usage: %s [--core PATH] [--rom PATH]\n"
        "          [--bridge] (packed-frame/input pipe, no native GPIO/SPI access)\n"
        "          [--display-width 240|320] [--enter-buttons KEY1+KEY3] [--hold-seconds 2]\n"
        "       %s --headless [--frames N] [--script CSV] [--capture-dir DIR]\n"
        "          [--capture-every N] [--realtime] [--core PATH] [--rom PATH]\n"
        "       %s --self-test\n"
        "CSV: start_frame,end_frame,UP|DOWN|LEFT|RIGHT|CENTER|KEY1|KEY2|KEY3\n"
        "Frame ranges are zero-based, end-exclusive. Capture numbers are one-based.\n",name,name,name);
}

static int unsigned_arg(const char *s, unsigned long *value)
{
    char *end;
    if (!*s || *s == '-') return -1;
    errno=0;*value=strtoul(s,&end,10);
    return errno || *end || !*value ? -1 : 0;
}

static int entry_buttons_arg(const char *text, unsigned *buttons)
{
    static const char *names[] = {"UP","DOWN","LEFT","RIGHT","CENTER","KEY1","KEY2","KEY3"};
    char copy[96], *token, *save = NULL;
    unsigned mask = 0, count = 0;
    size_t length = strlen(text);
    if (!length || length >= sizeof(copy) || text[0] == '+' || text[length-1] == '+'
            || strstr(text,"++")) return -1;
    memcpy(copy,text,length+1);
    for (token = strtok_r(copy,"+",&save); token; token = strtok_r(NULL,"+",&save)) {
        unsigned i;
        for (i=0;i<8;i++) if (!strcmp(token,names[i])) break;
        if (i==8 || (mask & (1u<<i))) return -1;
        mask |= 1u<<i; count++;
    }
    if (count < 2 || count > 8) return -1;
    *buttons = mask;
    return 0;
}

static int entry_hold_arg(const char *text, uint64_t *nanoseconds)
{
    char *end;
    double seconds;
    if (!*text) return -1;
    errno=0; seconds=strtod(text,&end);
    if (errno || *end || !isfinite(seconds) || seconds<1.0 || seconds>10.0) return -1;
    *nanoseconds=(uint64_t)(seconds*1e9);
    return 0;
}

int main(int argc, char **argv)
{
    struct core_api core={0};
    struct retro_system_info info={0};
    struct retro_system_av_info av={0};
    struct retro_game_info game={0};
    void *rom=NULL;
    size_t rom_size=0;
    uint64_t started=0, elapsed=0, deadline=0, next_present=0, period;
    int i, result=1;
    bool initialized=false, loaded=false;
    app.hw.spi_fd=app.hw.gpio_fd=-1;
    app.bridge_output=-1;
    app.core_path="/opt/dino/native/gpsp_libretro.so";
    app.rom_path="/opt/dino/native/Google-Dino-Advance.gba";
    app.frame_limit=600; app.fps=59.72750057;
    for(i=1;i<argc;i++) {
        if(!strcmp(argv[i],"--headless")) app.headless=true;
        else if(!strcmp(argv[i],"--bridge")) app.bridge=true;
        else if(!strcmp(argv[i],"--realtime")) app.realtime=true;
        else if(!strcmp(argv[i],"--self-test")) return argc==2 ? self_test() : 1;
        else if(!strcmp(argv[i],"--help")) {usage(argv[0]);return 0;}
        else if(i+1<argc && !strcmp(argv[i],"--core")) app.core_path=argv[++i];
        else if(i+1<argc && !strcmp(argv[i],"--rom")) app.rom_path=argv[++i];
        else if(i+1<argc && !strcmp(argv[i],"--enter-buttons")) {
            if(entry_buttons_arg(argv[++i],&entry_chord)) {usage(argv[0]);return 1;}
        }
        else if(i+1<argc && !strcmp(argv[i],"--hold-seconds")) {
            if(entry_hold_arg(argv[++i],&entry_hold_ns)) {usage(argv[0]);return 1;}
        }
        else if(i+1<argc && !strcmp(argv[i],"--display-width")) {
            unsigned long requested;
            if(unsigned_arg(argv[++i],&requested) || requested != LCD_W) {
                fprintf(stderr,"Native binary does not match display profile (expected %d)\n",LCD_W);
                return 1;
            }
        }
        else if(i+1<argc && !strcmp(argv[i],"--script")) app.script_path=argv[++i];
        else if(i+1<argc && !strcmp(argv[i],"--capture-dir")) app.capture_dir=argv[++i];
        else if(i+1<argc && !strcmp(argv[i],"--frames")) {if(unsigned_arg(argv[++i],&app.frame_limit)) {usage(argv[0]);return 1;}}
        else if(i+1<argc && !strcmp(argv[i],"--capture-every")) {if(unsigned_arg(argv[++i],&app.capture_every)) {usage(argv[0]);return 1;}}
        else {usage(argv[0]);return 1;}
    }
    if(app.bridge && app.headless) {
        fprintf(stderr,"Bridge and headless modes are mutually exclusive\n"); return 1;
    }
    if(!app.headless && (app.script_path || app.capture_dir || app.capture_every || app.realtime)) {
        fprintf(stderr,"Script/capture/realtime options require --headless\n");return 1;
    }
    if(app.script_path && load_script(app.script_path)) {perror("Input script");goto cleanup;}
    if(app.capture_dir && mkdir(app.capture_dir,0755) && errno!=EEXIST) {perror("Capture directory");goto cleanup;}
    signal(SIGINT,on_signal);signal(SIGTERM,on_signal);signal(SIGHUP,on_signal);
    signal(SIGPIPE,SIG_IGN);
    if(app.bridge) {
        /* gpSP itself prints configuration diagnostics on stdout. Give the
         * protocol its own descriptor and route all core stdout to stderr. */
        fflush(stdout);
        app.bridge_output=dup(STDOUT_FILENO);
        if(app.bridge_output < 0 || dup2(STDERR_FILENO,STDOUT_FILENO) < 0) {
            perror("Bridge output setup"); goto cleanup;
        }
    }
    prepare_axis(app.xs,LCD_W,GBA_W);prepare_axis(app.ys,VIEW_H,GBA_H);
    if(!app.headless && !app.bridge && hardware_open(&app.hw)) {perror("Dino hardware initialization");goto cleanup;}
    if(load_core(&core,app.core_path)) goto cleanup;
    core.set_environment(environment);core.set_video_refresh(video_refresh);
    core.set_audio_sample(audio_sample);core.set_audio_sample_batch(audio_batch);
    core.set_input_poll(poll_input);core.set_input_state(input_state);
    core.get_system_info(&info);
    fprintf(stderr,"Core: %s %s; ROM: %s\n",info.library_name,info.library_version,app.rom_path);
    if(!info.library_name || strcmp(info.library_name,"gpSP")) {fprintf(stderr,"Expected gpSP core\n");goto cleanup;}
    core.init();initialized=true;
    core.set_controller_port_device(0,RETRO_DEVICE_JOYPAD);
    if(read_rom(app.rom_path,&rom,&rom_size)) {perror("Read ROM");goto cleanup;}
    game.path=app.rom_path;game.data=info.need_fullpath ? NULL : rom;game.size=info.need_fullpath ? 0 : rom_size;
    if(!core.load_game(&game)) {fprintf(stderr,"Core refused Dino ROM\n");goto cleanup;}
    loaded=true;
    core.get_system_av_info(&av);
    if(av.geometry.base_width!=GBA_W || av.geometry.base_height!=GBA_H ||
       !(av.timing.fps>59.72 && av.timing.fps<59.74) || !app.pixel_format) {
        fprintf(stderr,"Unexpected GBA video/timing\n");goto cleanup;
    }
    /* Save method must be read before the first emulated frame; otherwise gpSP
     * could write its own backup file. Never continue with an unknown core. */
    if(!(app.option_reads & (1u<<7))) {fprintf(stderr,"Core did not accept libretro save method\n");goto cleanup;}
    app.fps=av.timing.fps;
    fprintf(stderr,"Video: 240x160 RGB565 -> %dx%d @ y%d; %.8f Hz; audio discarded\n",
            LCD_W,VIEW_H,VIEW_Y,app.fps);
    started=now_ns();deadline=next_present=started;period=(uint64_t)(1e9/app.fps);
    while(!interrupted && !app.fatal && !app.core_shutdown) {
        uint64_t bytes_before;
        poll_input();
        if(app.unlock) {result=EXIT_UNLOCK;break;}
        if(!app.headless || app.realtime) {
            uint64_t now=now_ns();
            if(now<deadline) {uint64_t delay=deadline-now;sleep_ns(delay>1000000?1000000:delay);continue;}
            if(now-deadline>app.max_lag_ns) app.max_lag_ns=now-deadline;
            /* Retain elapsed game time across ordinary SPI stalls. Only cap a
             * genuinely large pause; otherwise catch up without presenting. */
            if(now-deadline>MAX_GAME_LAG_NS) {
                uint64_t lost=(now-deadline-MAX_GAME_LAG_NS+period-1)/period;
                deadline+=lost*period;
                app.discarded_clock_frames+=lost;
            }
        }
        if(app.bridge) {
            if(bridge_input()) {perror("Bridge input");app.fatal=true;break;}
            poll_input();
            if(app.unlock) {result=EXIT_UNLOCK;break;}
        }
        if(!app.headless) {
            uint64_t now=now_ns();
            app.suppress_presentation=now<next_present || now-deadline>=period;
            if(!app.suppress_presentation) next_present=now+PRESENT_INTERVAL_NS;
        }
        bytes_before=app.bytes;
        core.run();app.frame++;
        record_frame_bytes(app.bytes-bytes_before);
        if(app.fatal || app.core_shutdown) break;
        if(app.headless && app.capture_dir && app.got_video &&
           ((app.capture_every && app.frame%app.capture_every==0) || app.frame==app.frame_limit))
            if(capture_frame()) {perror("Capture frame");app.fatal=true;break;}
        if(app.headless && app.frame>=app.frame_limit) {result=app.got_video ? 0 : 1;break;}
        deadline+=period;
    }
    elapsed=now_ns()-started;
    if(interrupted) result=128+interrupted;
    if(app.fatal || app.core_shutdown) result=1;
cleanup:
    /* All non-gesture paths retain a non-42 status, including emulator errors,
     * signals, missing files, headless completion and hardware failures. */
    hardware_close(&app.hw);
    if(loaded) core.unload_game();
    if(initialized) core.deinit();
    if(core.handle) dlclose(core.handle);
    if(app.bridge_output >= 0) close(app.bridge_output);
    free(rom);
    if((app.headless || app.bridge) && started) fprintf(app.bridge ? stderr : stdout,
        "{\"frames\":%lu,\"video_frames\":%" PRIu64 ",\"audio_frames\":%" PRIu64
        ",\"elapsed_seconds\":%.6f,\"emulated_fps\":%.3f,\"target_fps\":%.8f,\"frame_hash\":\"%016" PRIx64
        "\",\"raw_frame_hash\":\"%016" PRIx64 "\",\"dirty_rects\":%" PRIu64 ",\"spi_bytes_estimate\":%" PRIu64
        ",\"max_frame_bytes\":%" PRIu64 ",\"max_steady_frame_bytes\":%" PRIu64
        ",\"p95_steady_frame_bytes\":%u,\"steady_frames\":%" PRIu64
        ",\"mean_frame_bytes\":%.2f,\"p95_steady_wire_ms\":%.3f,\"max_steady_wire_ms\":%.3f,\"frames_over_wire_budget\":%" PRIu64
        ",\"option_reads\":%u,\"exit_code\":%d,\"presented_frames\":%" PRIu64
        ",\"suppressed_frames\":%" PRIu64 ",\"discarded_clock_frames\":%" PRIu64
        ",\"max_lag_ms\":%.3f,\"input_requests\":%" PRIu64 "}\n",app.frame,app.video_frames,app.audio_frames,
        elapsed/1e9,elapsed ? app.frame*1e9/elapsed : 0.0,app.fps,
        frame_hash(app.pixels,LCD_W*LCD_H),frame_hash(app.raw,GBA_W*GBA_H),
        app.rects,app.bytes,app.max_frame_bytes,app.max_steady_frame_bytes,
        percentile95_bytes(),app.steady_frames,
        app.frame ? (double)app.bytes/app.frame : 0.0,
        percentile95_bytes()*8000.0/SPI_SPEED,
        app.max_steady_frame_bytes*8000.0/SPI_SPEED,app.over_wire_budget,app.option_reads,result,
        app.presented_frames,app.suppressed_frames,app.discarded_clock_frames,
        app.max_lag_ns/1e6,app.input_requests);
    return result;
}
