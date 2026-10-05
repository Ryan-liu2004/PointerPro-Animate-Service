#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "rpc_tool.h"

void set_response(char *response, const char *message)
{
    if (!response || !message)
        return;
    snprintf(response, MAX_COMMAND, "%s", message);
}

int has_unsigned_leading_zero(const char *token)
{
    return token && token[0] == '0' && token[1] != '\0';
}

int has_signed_leading_zero(const char *token)
{
    const char *digits = token;

    if (!token)
        return 0;
    if (token[0] == '-' || token[0] == '+')
        digits = token + 1;
    return digits[0] == '0' && digits[1] != '\0';
}

int parse_u64_token(const char *token, uint64_t *value)
{
    char *end = NULL;
    unsigned long long parsed = 0;

    if (!token || !value || token[0] == '\0' || token[0] == '-' ||
        token[0] == '+')
        return -1;
    if (has_unsigned_leading_zero(token))
        return -1;

    errno = 0;
    parsed = strtoull(token, &end, 10);
    if (errno != 0 || !end || *end != '\0')
        return -1;

    *value = (uint64_t)parsed;
    return 0;
}

int parse_size_token(const char *token, size_t *value)
{
    uint64_t parsed = 0;

    if (parse_u64_token(token, &parsed) != 0)
        return -1;
    if (parsed > (uint64_t)((size_t)-1))
        return -1;

    *value = (size_t)parsed;
    return 0;
}

int parse_bool_token(const char *token, bool *value)
{
    uint64_t parsed = 0;

    if (parse_u64_token(token, &parsed) != 0)
        return -1;
    if (parsed > 1)
        return -1;

    *value = parsed ? true : false;
    return 0;
}

int parse_color_token(const char *token, color_t *value)
{
    uint64_t parsed = 0;

    if (parse_u64_token(token, &parsed) != 0)
        return -1;
    if (parsed > UINT32_MAX)
        return -1;

    *value = (color_t)parsed;
    return 0;
}

int parse_ssize_token(const char *token, ssize_t *value)
{
    char *end = NULL;
    long parsed = 0;

    if (!token || !value || token[0] == '\0')
        return -1;
    if (has_signed_leading_zero(token))
        return -1;

    errno = 0;
    parsed = strtol(token, &end, 10);
    if (errno != 0 || !end || *end != '\0')
        return -1;
    if ((long)((ssize_t)parsed) != parsed)
        return -1;

    *value = (ssize_t)parsed;
    return 0;
}

uint64_t encode_resource_id(ClientData *data, Resources *resource)
{
    return ((uint64_t)(uint32_t)data->client_id << 32) |
           (uint32_t)resource->resource_id;
}

uint32_t decode_client_id(uint64_t handle) { return (uint32_t)(handle >> 32); }

int handle_belongs_to_client(uint64_t handle, ClientData *data)
{
    return data && decode_client_id(handle) == (uint32_t)data->client_id;
}

uint32_t decode_resource_id(uint64_t handle) { return (uint32_t)handle; }

int resource_limit_reached(ClientData *data)
{
    int reached = 0;

    if (!data || !data->resources)
        return 1;

    pthread_mutex_lock(&data->resources_mutex);
    reached = data->resources->size < 0 || data->resources->size > INT_MAX;
    pthread_mutex_unlock(&data->resources_mutex);
    return reached;
}

ClientData *find_client_data(uint32_t client_id)
{
    ClientData *client_data = NULL;

    pthread_mutex_lock(&ClientResources_mutex);
    if (client_id != 0 && ClientResources &&
        client_id < (uint32_t)ClientResources->size)
        client_data = (ClientData *)ClientResources->data[client_id];
    pthread_mutex_unlock(&ClientResources_mutex);

    return client_data;
}

int client_is_online(ClientData *data)
{
    int online = 0;

    if (!data)
        return 0;
    pthread_mutex_lock(&data->state_mutex);
    online = data->client_alive && data->client && data->client->is_logged_in;
    pthread_mutex_unlock(&data->state_mutex);
    return online;
}

int client_id_is_online(int client_id)
{
    return client_is_online(find_client_data((uint32_t)client_id));
}

ClientData *find_logged_in_client_by_username(const char *username)
{
    ClientData *result = NULL;

    if (!username || username[0] == '\0')
        return NULL;

    pthread_mutex_lock(&ClientResources_mutex);
    if (ClientResources)
    {
        for (ssize_t i = 1; i < ClientResources->size; i++)
        {
            ClientData *candidate = (ClientData *)ClientResources->data[i];
            int username_matches = 0;

            if (candidate)
            {
                pthread_mutex_lock(&candidate->state_mutex);
                username_matches =
                    candidate->client_alive && candidate->client &&
                    candidate->client->is_logged_in &&
                    strcmp(candidate->client->username, username) == 0;
                pthread_mutex_unlock(&candidate->state_mutex);
            }
            if (username_matches)
            {
                result = candidate;
                break;
            }
        }
    }
    pthread_mutex_unlock(&ClientResources_mutex);

    return result;
}

int canvas_has_participant_locked(CanvasState *state, int client_id)
{
    if (!state || !state->participants)
        return 0;
    for (ssize_t i = 0; i < state->participants->size; i++)
    {
        if ((int)(intptr_t)state->participants->data[i] == client_id)
            return 1;
    }
    return 0;
}

int canvas_online_participant_count_locked(CanvasState *state)
{
    int count = 0;

    if (!state || !state->participants)
        return 0;
    for (ssize_t i = 0; i < state->participants->size; i++)
    {
        int client_id = (int)(intptr_t)state->participants->data[i];
        if (client_id_is_online(client_id))
            count++;
    }
    return count;
}

void add_canvas_access(ClientData *data, Resources *canvas_resource)
{
    if (!data || !canvas_resource)
        return;

    pthread_mutex_lock(&data->state_mutex);
    if (!data->client_alive || !data->client || !data->client->is_logged_in)
    {
        pthread_mutex_unlock(&data->state_mutex);
        return;
    }
    pthread_mutex_lock(&data->resources_mutex);
    pthread_mutex_unlock(&data->state_mutex);
    for (ssize_t i = 0; i < data->accessiable_canvas->size; i++)
    {
        if (data->accessiable_canvas->data[i] == canvas_resource)
        {
            pthread_mutex_unlock(&data->resources_mutex);
            return;
        }
    }
    Vector_push_back(data->accessiable_canvas, canvas_resource);
    pthread_mutex_unlock(&data->resources_mutex);
}

void mark_resource_deleted(Resources *resource)
{
    if (!resource)
        return;
    pthread_mutex_lock(&resource->meta_mutex);
    resource->resource = NULL;
    resource->deleted = 1;
    pthread_mutex_unlock(&resource->meta_mutex);
}

void sprite_ref_increment(Resources *sprite_resource)
{
    if (!sprite_resource)
        return;
    pthread_mutex_lock(&sprite_resource->meta_mutex);
    sprite_resource->sprite_ref_count++;
    pthread_mutex_unlock(&sprite_resource->meta_mutex);
}

void sprite_ref_decrement(Resources *sprite_resource)
{
    if (!sprite_resource)
        return;
    pthread_mutex_lock(&sprite_resource->meta_mutex);
    if (sprite_resource->sprite_ref_count > 0)
        sprite_resource->sprite_ref_count--;
    pthread_mutex_unlock(&sprite_resource->meta_mutex);
}

Resources *get_resource_from_handle(uint64_t handle,
                                    ResourcesType expected_type)
{
    uint32_t client_id = decode_client_id(handle);
    uint32_t resource_id = decode_resource_id(handle);
    ClientData *resource_owner = find_client_data(client_id);
    Resources *resource = NULL;

    if (!resource_owner || !resource_owner->resources)
        return NULL;

    pthread_mutex_lock(&resource_owner->resources_mutex);
    if ((uint64_t)resource_id < (uint64_t)resource_owner->resources->size)
    {
        resource = (Resources *)resource_owner->resources->data[resource_id];
        if (!resource || resource->type != expected_type ||
            resource->resource_id != (int)resource_id)
            resource = NULL;
    }
    pthread_mutex_unlock(&resource_owner->resources_mutex);

    if (resource)
    {
        int invalid = 0;

        pthread_mutex_lock(&resource->meta_mutex);
        invalid = resource->deleted || !resource->resource;
        pthread_mutex_unlock(&resource->meta_mutex);
        if (invalid)
            resource = NULL;
    }
    return resource;
}

Resources *get_accessible_placement(ClientData *data, uint64_t handle)
{
    Resources *placement_resource =
        get_resource_from_handle(handle, Sprite_Placement);

    if (!placement_resource || !placement_resource->canvas_resource)
        return NULL;
    if (!handle_belongs_to_client(handle, data))
        return NULL;

    return placement_resource;
}

void finish_created_resource(ClientData *data, Resources *resource,
                             char *response)
{
    pthread_mutex_lock(&data->resources_mutex);
    resource->resource_id = (int)data->resources->size;
    resource->owner_client_id = data->client_id;
    Vector_push_back(data->resources, resource);
    if (resource->type == Canvas)
    {
        Vector_push_back(data->accessiable_canvas, resource);
        if (resource->canvas_state)
        {
            pthread_mutex_lock(&resource->canvas_state->meta_mutex);
            Vector_push_back(resource->canvas_state->participants,
                             (void *)(intptr_t)data->client_id);
            pthread_mutex_unlock(&resource->canvas_state->meta_mutex);
        }
    }
    pthread_mutex_unlock(&data->resources_mutex);

    snprintf(response, MAX_COMMAND, "0 %llu",
             (unsigned long long)encode_resource_id(data, resource));
}

int has_canvas_access(ClientData *data, Resources *canvas_resource)
{
    if (!data || !data->accessiable_canvas || !canvas_resource)
        return 0;
    int has_access = 0;
    pthread_mutex_lock(&data->resources_mutex);
    for (ssize_t i = 0; i < data->accessiable_canvas->size; i++)
    {
        if (data->accessiable_canvas->data[i] == canvas_resource)
        {
            has_access = 1;
            break;
        }
    }
    pthread_mutex_unlock(&data->resources_mutex);
    return has_access;
}

int barrier_waiter_index_locked(CanvasState *state, int client_id)
{
    if (!state || !state->barrier_waiters)
        return -1;
    for (ssize_t i = 0; i < state->barrier_waiters->size; i++)
    {
        CanvasBarrierWaiter *waiter =
            (CanvasBarrierWaiter *)state->barrier_waiters->data[i];
        if (waiter && waiter->client_id == client_id)
            return (int)i;
    }
    return -1;
}

int all_online_participants_waiting_locked(CanvasState *state)
{
    if (!state || !state->participants)
        return 0;

    for (ssize_t i = 0; i < state->participants->size; i++)
    {
        int client_id = (int)(intptr_t)state->participants->data[i];
        if (client_id_is_online(client_id) &&
            barrier_waiter_index_locked(state, client_id) < 0)
            return 0;
    }
    return 1;
}

void release_barrier_waiters(Resources *canvas_resource)
{
    CanvasState *state = canvas_resource ? canvas_resource->canvas_state : NULL;
    Vector *released_client_ids = NULL;

    if (!state)
        return;

    pthread_mutex_lock(&state->meta_mutex);
    if (!all_online_participants_waiting_locked(state))
    {
        pthread_mutex_unlock(&state->meta_mutex);
        return;
    }

    released_client_ids = Vector_init();
    for (ssize_t i = 0; i < state->barrier_waiters->size; i++)
    {
        CanvasBarrierWaiter *waiter =
            (CanvasBarrierWaiter *)state->barrier_waiters->data[i];
        if (waiter)
        {
            if (client_id_is_online(waiter->client_id))
                Vector_push_back(released_client_ids,
                                 (void *)(intptr_t)waiter->client_id);
            free(waiter);
        }
    }
    state->barrier_waiters->size = 0;
    pthread_mutex_unlock(&state->meta_mutex);

    if (!released_client_ids)
        return;
    for (ssize_t i = 0; i < released_client_ids->size; i++)
    {
        int client_id = (int)(intptr_t)released_client_ids->data[i];
        ClientData *released = find_client_data((uint32_t)client_id);
        int fd_write = -1;
        int should_release = 0;

        if (released)
        {
            pthread_mutex_lock(&released->state_mutex);
            if (released->client_alive && released->client &&
                released->client->is_logged_in)
            {
                released->blocked_on_barrier = 0;
                fd_write = released->client->fd_write;
                should_release = 1;
            }
            pthread_mutex_unlock(&released->state_mutex);
        }
        if (should_release)
        {
            if (fd_write != -1)
                nonblock_writen_with_terminator(fd_write, "0", strlen("0"));
            push_client_to_queue(released);
        }
    }
    Vector_free(released_client_ids);
}

void rpc_move_placement(ClientData *data, Vector *tokens, char *response,
                        void (*move_func)(struct sprite_placement *))
{
    uint64_t placement_handle = 0;
    Resources *placement_resource = NULL;
    Resources *canvas_resource = NULL;

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

    canvas_resource = placement_resource->canvas_resource;
    pthread_mutex_lock(&canvas_resource->canvas_state->canvas_mutex);
    move_func((struct sprite_placement *)placement_resource->resource);
    pthread_mutex_unlock(&canvas_resource->canvas_state->canvas_mutex);
    set_response(response, "0");
}
