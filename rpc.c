#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>

#include "rpc.h"
#include "rpc_cleanup.h"
#include "rpc_tool.h"
#include "tool.h"

void rpc_create_canvas(ClientData *data, Vector *tokens, char *response)
{
    if (resource_limit_reached(data) || !data->accessiable_canvas || !tokens ||
        !data->client)
    {
        set_response(response, "-3");
        return;
    }
    if (tokens->size != 4)
    {
        set_response(response, "-1");
        return;
    }

    size_t height = 0;
    size_t width = 0;
    color_t color = 0;
    canvas *canvas = NULL;
    Resources *resource = NULL;
    if (parse_size_token((char *)tokens->data[1], &height) != 0 ||
        parse_size_token((char *)tokens->data[2], &width) != 0 ||
        parse_color_token((char *)tokens->data[3], &color) != 0)
    {
        set_response(response, "-2");
        return;
    }

    canvas = animate_create_canvas(height, width, color);
    if (!canvas)
    {
        set_response(response, "-3");
        return;
    }

    resource = Resources_init(-1, Canvas, canvas);
    if (!resource)
    {
        animate_destroy_canvas(canvas);
        set_response(response, "-3");
        return;
    }
    resource->canvas_state->height = height;
    resource->canvas_state->width = width;

    finish_created_resource(data, resource, response);
}

void rpc_create_sprite(ClientData *data, Vector *tokens, char *response)
{
    if (resource_limit_reached(data) || !data->client || !tokens)
    {
        set_response(response, "-3");
        return;
    }
    if (tokens->size != 2)
    {
        set_response(response, "-1");
        return;
    }

    Resources *resource;
    sprite *sprite = animate_create_sprite((char *)tokens->data[1]);
    if (!sprite)
    {
        set_response(response, "-3");
        return;
    }

    resource = Resources_init(-1, Sprite, sprite);
    if (!resource)
    {
        animate_destroy_sprite(sprite);
        set_response(response, "-3");
        return;
    }

    finish_created_resource(data, resource, response);
}

void rpc_create_rectangle(ClientData *data, Vector *tokens, char *response)
{
    if (resource_limit_reached(data) || !data->client || !tokens)
    {
        set_response(response, "-3");
        return;
    }
    if (tokens->size != 5)
    {
        set_response(response, "-1");
        return;
    }

    size_t width = 0;
    size_t height = 0;
    color_t color = 0;
    bool filled = false;
    sprite *sprite = NULL;
    Resources *resource = NULL;
    if (parse_size_token((char *)tokens->data[1], &width) != 0 ||
        parse_size_token((char *)tokens->data[2], &height) != 0 ||
        parse_color_token((char *)tokens->data[3], &color) != 0 ||
        parse_bool_token((char *)tokens->data[4], &filled) != 0)
    {
        set_response(response, "-2");
        return;
    }

    sprite = animate_create_rectangle(width, height, color, filled);
    if (!sprite)
    {
        set_response(response, "-3");
        return;
    }

    resource = Resources_init(-1, Sprite, sprite);
    if (!resource)
    {
        animate_destroy_sprite(sprite);
        set_response(response, "-3");
        return;
    }

    finish_created_resource(data, resource, response);
}

void rpc_create_circle(ClientData *data, Vector *tokens, char *response)
{
    if (resource_limit_reached(data) || !data->client || !tokens)
    {
        set_response(response, "-3");
        return;
    }
    if (tokens->size != 4)
    {
        set_response(response, "-1");
        return;
    }

    size_t radius = 0;
    color_t color = 0;
    bool filled = false;
    sprite *sprite = NULL;
    Resources *resource = NULL;
    if (parse_size_token((char *)tokens->data[1], &radius) != 0 ||
        parse_color_token((char *)tokens->data[2], &color) != 0 ||
        parse_bool_token((char *)tokens->data[3], &filled) != 0)
    {
        set_response(response, "-2");
        return;
    }

    sprite = animate_create_circle(radius, color, filled);
    if (!sprite)
    {
        set_response(response, "-3");
        return;
    }

    resource = Resources_init(-1, Sprite, sprite);
    if (!resource)
    {
        animate_destroy_sprite(sprite);
        set_response(response, "-3");
        return;
    }

    finish_created_resource(data, resource, response);
}

void rpc_place_sprite(ClientData *data, Vector *tokens, char *response)
{
    if (resource_limit_reached(data) || !data->client || !tokens)
    {
        set_response(response, "-3");
        return;
    }
    if (tokens->size != 5)
    {
        set_response(response, "-1");
        return;
    }

    uint64_t canvas_handle = 0;
    uint64_t sprite_handle = 0;
    ssize_t x = 0;
    ssize_t y = 0;
    Resources *canvas_resource = NULL;
    Resources *sprite_resource = NULL;
    sprite_placement *placement = NULL;
    Resources *placement_resource = NULL;
    if (parse_u64_token((char *)tokens->data[1], &canvas_handle) != 0 ||
        parse_u64_token((char *)tokens->data[2], &sprite_handle) != 0 ||
        parse_ssize_token((char *)tokens->data[3], &x) != 0 ||
        parse_ssize_token((char *)tokens->data[4], &y) != 0)
    {
        set_response(response, "-2");
        return;
    }

    canvas_resource = get_resource_from_handle(canvas_handle, Canvas);
    sprite_resource = get_resource_from_handle(sprite_handle, Sprite);
    if (!canvas_resource || !sprite_resource ||
        !has_canvas_access(data, canvas_resource) ||
        !handle_belongs_to_client(sprite_handle, data))
    {
        set_response(response, "-2");
        return;
    }

    pthread_mutex_lock(&canvas_resource->canvas_state->canvas_mutex);
    placement = animate_place_sprite((canvas *)canvas_resource->resource,
                                     (sprite *)sprite_resource->resource, x, y);
    pthread_mutex_unlock(&canvas_resource->canvas_state->canvas_mutex);
    if (!placement)
    {
        set_response(response, "-3");
        return;
    }

    placement_resource = Resources_init(-1, Sprite_Placement, placement);
    if (!placement_resource)
    {
        pthread_mutex_lock(&canvas_resource->canvas_state->canvas_mutex);
        animate_destroy_placement(placement);
        pthread_mutex_unlock(&canvas_resource->canvas_state->canvas_mutex);
        set_response(response, "-3");
        return;
    }
    placement_resource->canvas_resource = canvas_resource;
    placement_resource->sprite_resource = sprite_resource;
    sprite_ref_increment(sprite_resource);
    pthread_mutex_lock(&canvas_resource->canvas_state->meta_mutex);
    Vector_push_back(canvas_resource->canvas_state->placements,
                     placement_resource);
    pthread_mutex_unlock(&canvas_resource->canvas_state->meta_mutex);

    finish_created_resource(data, placement_resource, response);
}

void rpc_placement_up(ClientData *data, Vector *tokens, char *response)
{
    rpc_move_placement(data, tokens, response, animate_placement_up);
}

void rpc_placement_down(ClientData *data, Vector *tokens, char *response)
{
    rpc_move_placement(data, tokens, response, animate_placement_down);
}

void rpc_placement_top(ClientData *data, Vector *tokens, char *response)
{
    rpc_move_placement(data, tokens, response, animate_placement_top);
}

void rpc_placement_bottom(ClientData *data, Vector *tokens, char *response)
{
    rpc_move_placement(data, tokens, response, animate_placement_bottom);
}

void rpc_set_animation_params(ClientData *data, Vector *tokens, char *response)
{
    uint64_t placement_handle = 0;
    ssize_t vx = 0;
    ssize_t vy = 0;
    ssize_t ax = 0;
    ssize_t ay = 0;
    Resources *placement_resource = NULL;
    Resources *canvas_resource = NULL;

    if (resource_limit_reached(data) || !data->client || !tokens)
    {
        set_response(response, "-3");
        return;
    }
    if (tokens->size != 6)
    {
        set_response(response, "-1");
        return;
    }
    if (parse_u64_token((char *)tokens->data[1], &placement_handle) != 0 ||
        parse_ssize_token((char *)tokens->data[2], &vx) != 0 ||
        parse_ssize_token((char *)tokens->data[3], &vy) != 0 ||
        parse_ssize_token((char *)tokens->data[4], &ax) != 0 ||
        parse_ssize_token((char *)tokens->data[5], &ay) != 0)
    {
        set_response(response, "-2");
        return;
    }

    placement_resource = get_accessible_placement(data, placement_handle);
    if (!placement_resource)
    {
        set_response(response, "-2");
        return;
    }

    canvas_resource = placement_resource->canvas_resource;
    pthread_mutex_lock(&canvas_resource->canvas_state->canvas_mutex);
    animate_set_animation_params(
        (sprite_placement *)placement_resource->resource, vx, vy, ax, ay);
    pthread_mutex_unlock(&canvas_resource->canvas_state->canvas_mutex);
    set_response(response, "0");
}

void rpc_destroy_canvas(ClientData *data, Vector *tokens, char *response)
{
    uint64_t canvas_handle = 0;
    Resources *canvas_resource = NULL;
    CanvasState *state = NULL;

    if (resource_limit_reached(data) || !data->client || !tokens)
    {
        set_response(response, "-3");
        return;
    }
    if (tokens->size != 2)
    {
        set_response(response, "-1");
        return;
    }
    if (parse_u64_token((char *)tokens->data[1], &canvas_handle) != 0)
    {
        set_response(response, "-2");
        return;
    }

    canvas_resource = get_resource_from_handle(canvas_handle, Canvas);
    if (!canvas_resource || !has_canvas_access(data, canvas_resource))
    {
        set_response(response, "-2");
        return;
    }

    state = canvas_resource->canvas_state;
    pthread_mutex_lock(&state->meta_mutex);
    if (canvas_online_participant_count_locked(state) > 1)
    {
        pthread_mutex_unlock(&state->meta_mutex);
        set_response(response, "-2");
        return;
    }
    destroy_canvas_resource_locked(state, canvas_resource);
    pthread_mutex_unlock(&state->meta_mutex);
    set_response(response, "0");
}

void rpc_destroy_sprite(ClientData *data, Vector *tokens, char *response)
{
    uint64_t sprite_handle = 0;
    Resources *sprite_resource = NULL;
    sprite *sprite_ptr = NULL;
    int result = 1;

    if (resource_limit_reached(data) || !data->client || !tokens)
    {
        set_response(response, "-3");
        return;
    }
    if (tokens->size != 2)
    {
        set_response(response, "-1");
        return;
    }
    if (parse_u64_token((char *)tokens->data[1], &sprite_handle) != 0)
    {
        set_response(response, "-2");
        return;
    }

    sprite_resource = get_resource_from_handle(sprite_handle, Sprite);
    if (!sprite_resource || !handle_belongs_to_client(sprite_handle, data))
    {
        set_response(response, "-2");
        return;
    }

    pthread_mutex_lock(&sprite_resource->meta_mutex);
    if (sprite_resource->sprite_ref_count > 0)
    {
        pthread_mutex_unlock(&sprite_resource->meta_mutex);
        set_response(response, "0 1");
        return;
    }
    sprite_ptr = (sprite *)sprite_resource->resource;
    pthread_mutex_unlock(&sprite_resource->meta_mutex);

    if (!sprite_ptr)
    {
        set_response(response, "-2");
        return;
    }

    result = animate_destroy_sprite(sprite_ptr) ? 1 : 0;
    if (result == 0)
        mark_resource_deleted(sprite_resource);
    snprintf(response, MAX_COMMAND, "0 %d", result);
}

void rpc_destroy_placement(ClientData *data, Vector *tokens, char *response)
{
    uint64_t placement_handle = 0;
    Resources *placement_resource = NULL;

    if (resource_limit_reached(data) || !data->client || !tokens)
    {
        set_response(response, "-3");
        return;
    }
    if (tokens->size != 2)
    {
        set_response(response, "-1");
        return;
    }
    if (parse_u64_token((char *)tokens->data[1], &placement_handle) != 0)
    {
        set_response(response, "-2");
        return;
    }

    placement_resource = get_accessible_placement(data, placement_handle);
    if (!placement_resource)
    {
        set_response(response, "-2");
        return;
    }

    destroy_placement_resource(placement_resource);
    set_response(response, "0");
}

static char *build_output_path(const char *filename, const char *suffix)
{
    size_t filename_len = strlen(filename);
    size_t suffix_len = strlen(suffix);
    char *path = malloc(filename_len + suffix_len + 1);

    if (!path)
        return NULL;
    memcpy(path, filename, filename_len);
    memcpy(path + filename_len, suffix, suffix_len + 1);
    return path;
}

static int write_frame_data(Resources *canvas_resource, const char *dat_path,
                            size_t start, size_t end, size_t frame_rate)
{
    CanvasState *state = canvas_resource->canvas_state;
    void *frame_buffer = NULL;
    size_t frame_size = 0;
    int status = 0;

    int fd = open(dat_path, O_WRONLY | O_CREAT | O_TRUNC, 0666);
    if (fd == -1)
        return -1;

    pthread_mutex_lock(&state->canvas_mutex);
    if (!canvas_resource->resource)
    {
        pthread_mutex_unlock(&state->canvas_mutex);
        close(fd);
        return -2;
    }

    frame_size = animate_frame_size_bytes((canvas *)canvas_resource->resource);
    frame_buffer = malloc(frame_size);
    if (!frame_buffer)
    {
        pthread_mutex_unlock(&state->canvas_mutex);
        close(fd);
        return -3;
    }

    for (size_t frame = start;; frame++)
    {
        animate_generate_frame((canvas *)canvas_resource->resource, frame,
                               frame_rate, frame_buffer);
        if (nonblock_writen_without_terminator(fd, frame_buffer, frame_size) !=
            WRITE_SUCCESS)
        {
            status = -1;
            break;
        }
        if (frame == end)
            break;
    }

    free(frame_buffer);
    pthread_mutex_unlock(&state->canvas_mutex);
    if (close(fd) != 0 && status == 0)
        status = -1;
    return status;
}

static int run_ffmpeg(const char *dat_path, const char *mp4_path,
                      const char *log_path, size_t width, size_t height,
                      size_t frame_rate)
{
    pid_t pid;
    int status = 0;
    char video_size[MAX_COMMAND];
    char frame_rate_arg[MAX_COMMAND];

    snprintf(video_size, sizeof(video_size), "%zux%zu", width, height);
    snprintf(frame_rate_arg, sizeof(frame_rate_arg), "%zu", frame_rate);

    pid = fork();
    if (pid == -1)
        return -1;
    if (pid == 0)
    {
        int log_fd = open(log_path, O_WRONLY | O_CREAT | O_TRUNC, 0666);
        if (log_fd == -1)
            _exit(127);
        dup2(log_fd, STDOUT_FILENO);
        dup2(log_fd, STDERR_FILENO);
        close(log_fd);
        execlp("ffmpeg", "ffmpeg", "-y", "-f", "rawvideo", "-pixel_format",
               "argb", "-video_size", video_size, "-framerate", frame_rate_arg,
               "-i", dat_path, mp4_path, (char *)NULL);
        _exit(127);
    }

    if (waitpid(pid, &status, 0) == -1)
        return -1;
    if (!WIFEXITED(status) || WEXITSTATUS(status) != 0)
        return -1;
    return 0;
}

void rpc_generate(ClientData *data, Vector *tokens, char *response)
{
    uint64_t canvas_handle = 0;
    size_t start = 0;
    size_t end = 0;
    size_t frame_rate = 0;
    Resources *canvas_resource = NULL;
    char *filename = NULL;
    char *dat_path = NULL;
    char *mp4_path = NULL;
    char *log_path = NULL;
    int frame_status = 0;

    if (resource_limit_reached(data) || !data->client || !tokens)
    {
        set_response(response, "-3");
        return;
    }
    if (tokens->size != 6)
    {
        set_response(response, "-1");
        return;
    }
    filename = (char *)tokens->data[2];
    if (parse_u64_token((char *)tokens->data[1], &canvas_handle) != 0 ||
        parse_size_token((char *)tokens->data[3], &start) != 0 ||
        parse_size_token((char *)tokens->data[4], &end) != 0 ||
        parse_size_token((char *)tokens->data[5], &frame_rate) != 0 ||
        frame_rate == 0 || start > end || !filename || filename[0] == '\0')
    {
        set_response(response, "-2");
        return;
    }

    canvas_resource = get_resource_from_handle(canvas_handle, Canvas);
    if (!canvas_resource || !has_canvas_access(data, canvas_resource))
    {
        set_response(response, "-2");
        return;
    }

    dat_path = build_output_path(filename, ".dat");
    mp4_path = build_output_path(filename, ".mp4");
    log_path = build_output_path(filename, ".log");
    if (!dat_path || !mp4_path || !log_path)
    {
        free(dat_path);
        free(mp4_path);
        free(log_path);
        set_response(response, "-3");
        return;
    }

    frame_status =
        write_frame_data(canvas_resource, dat_path, start, end, frame_rate);
    if (frame_status == -1)
        set_response(response, "0 -1");
    else if (frame_status == -2)
        set_response(response, "-2");
    else if (frame_status == -3)
        set_response(response, "-3");
    else if (run_ffmpeg(dat_path, mp4_path, log_path,
                        canvas_resource->canvas_state->width,
                        canvas_resource->canvas_state->height, frame_rate) != 0)
        set_response(response, "0 0 -1");
    else
        set_response(response, "0 0 0");

    free(dat_path);
    free(mp4_path);
    free(log_path);
}

void rpc_share_canvas(ClientData *data, Vector *tokens, char *response)
{
    uint64_t canvas_handle = 0;
    char *peer_username = NULL;
    ClientData *peer = NULL;
    Resources *canvas_resource = NULL;
    CanvasState *state = NULL;
    ClientData *client_to_add = NULL;
    int current_has_access = 0;
    int peer_has_access = 0;

    if (resource_limit_reached(data) || !data->client || !tokens)
    {
        set_response(response, "-3");
        return;
    }
    if (tokens->size != 3)
    {
        set_response(response, "-1");
        return;
    }
    peer_username = (char *)tokens->data[2];
    if (parse_u64_token((char *)tokens->data[1], &canvas_handle) != 0 ||
        !peer_username || peer_username[0] == '\0')
    {
        set_response(response, "-2");
        return;
    }

    peer = find_logged_in_client_by_username(peer_username);
    canvas_resource = get_resource_from_handle(canvas_handle, Canvas);
    if (!peer || peer == data || !canvas_resource)
    {
        set_response(response, "-2");
        return;
    }

    state = canvas_resource->canvas_state;
    pthread_mutex_lock(&state->meta_mutex);
    current_has_access = canvas_has_participant_locked(state, data->client_id);
    peer_has_access = canvas_has_participant_locked(state, peer->client_id);

    if (current_has_access)
        client_to_add = peer;
    else if (peer_has_access)
        client_to_add = data;
    else
    {
        pthread_mutex_unlock(&state->meta_mutex);
        set_response(response, "-2");
        return;
    }

    if (!canvas_has_participant_locked(state, client_to_add->client_id))
        Vector_push_back(state->participants,
                         (void *)(intptr_t)client_to_add->client_id);
    pthread_mutex_unlock(&state->meta_mutex);

    add_canvas_access(client_to_add, canvas_resource);
    set_response(response, "0");
}

int rpc_barrier(ClientData *data, Vector *tokens, char *response)
{
    uint64_t canvas_handle = 0;
    Resources *canvas_resource = NULL;
    CanvasState *state = NULL;
    CanvasBarrierWaiter *waiter = NULL;
    int should_release = 0;

    if (resource_limit_reached(data) || !data->client || !tokens)
    {
        set_response(response, "-3");
        return 0;
    }
    if (tokens->size != 2)
    {
        set_response(response, "-1");
        return 0;
    }
    if (parse_u64_token((char *)tokens->data[1], &canvas_handle) != 0)
    {
        set_response(response, "-2");
        return 0;
    }

    canvas_resource = get_resource_from_handle(canvas_handle, Canvas);
    if (!canvas_resource || !has_canvas_access(data, canvas_resource))
    {
        set_response(response, "-2");
        return 0;
    }

    state = canvas_resource->canvas_state;
    pthread_mutex_lock(&state->meta_mutex);
    if (!canvas_has_participant_locked(state, data->client_id))
    {
        pthread_mutex_unlock(&state->meta_mutex);
        set_response(response, "-2");
        return 0;
    }

    if (barrier_waiter_index_locked(state, data->client_id) < 0)
    {
        waiter = malloc(sizeof(CanvasBarrierWaiter));
        if (!waiter)
        {
            pthread_mutex_unlock(&state->meta_mutex);
            set_response(response, "-3");
            return 0;
        }
        waiter->client_id = data->client_id;
        Vector_push_back(state->barrier_waiters, waiter);
    }
    should_release = all_online_participants_waiting_locked(state);
    if (!should_release)
        client_set_blocked_on_barrier(data, 1);
    pthread_mutex_unlock(&state->meta_mutex);
    response[0] = '\0';
    if (!should_release)
        return 1;
    release_barrier_waiters(canvas_resource);
    return 0;
}
