#include <stdbool.h>
#include <stdint.h>
#include <sys/types.h>

#include "animate/animate.h"

struct canvas *bridge_create_canvas(size_t height, size_t width,
                                    color_t background_color)
{
    return animate_create_canvas(height, width, background_color);
}

void bridge_destroy_canvas(struct canvas *canvas)
{
    animate_destroy_canvas(canvas);
}

struct sprite *bridge_create_sprite(const char *file)
{
    return animate_create_sprite(file);
}

struct sprite *bridge_create_rectangle(size_t width, size_t height, color_t c,
                                       bool filled)
{
    return animate_create_rectangle(width, height, c, filled);
}

struct sprite *bridge_create_circle(size_t radius, color_t c, bool filled)
{
    return animate_create_circle(radius, c, filled);
}

int bridge_destroy_sprite(struct sprite *sprite)
{
    return animate_destroy_sprite(sprite) ? 1 : 0;
}

struct sprite_placement *bridge_place_sprite(struct canvas *canvas,
                                             struct sprite *sprite,
                                             ssize_t x, ssize_t y)
{
    return animate_place_sprite(canvas, sprite, x, y);
}

void bridge_placement_up(struct sprite_placement *placement)
{
    animate_placement_up(placement);
}

void bridge_placement_down(struct sprite_placement *placement)
{
    animate_placement_down(placement);
}

void bridge_placement_top(struct sprite_placement *placement)
{
    animate_placement_top(placement);
}

void bridge_placement_bottom(struct sprite_placement *placement)
{
    animate_placement_bottom(placement);
}

void bridge_destroy_placement(struct sprite_placement *placement)
{
    animate_destroy_placement(placement);
}

void bridge_set_animation_params(struct sprite_placement *placement,
                                 ssize_t vx, ssize_t vy,
                                 ssize_t ax, ssize_t ay)
{
    animate_set_animation_params(placement, vx, vy, ax, ay);
}

size_t bridge_frame_size_bytes(struct canvas *canvas)
{
    return animate_frame_size_bytes(canvas);
}

void bridge_generate_frame(struct canvas *canvas, size_t frame,
                           size_t frame_rate, void *buf)
{
    animate_generate_frame(canvas, frame, frame_rate, buf);
}

