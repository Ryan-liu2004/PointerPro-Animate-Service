#include "rpc_cleanup.h"
#include "rpc_tool.h"

void destroy_canvas_resource_locked(CanvasState *state,
                                    Resources *canvas_resource)
{
    struct canvas *canvas_ptr = NULL;

    if (!state || !canvas_resource)
        return;
    pthread_mutex_lock(&state->canvas_mutex);

    for (ssize_t i = 0; i < state->placements->size; i++)
    {
        Resources *placement_resource = (Resources *)state->placements->data[i];
        if (placement_resource)
            mark_canvas_placement_deleted(placement_resource);
    }
    state->placements->size = 0;

    pthread_mutex_lock(&canvas_resource->meta_mutex);
    canvas_ptr = (struct canvas *)canvas_resource->resource;
    canvas_resource->resource = NULL;
    canvas_resource->deleted = 1;
    pthread_mutex_unlock(&canvas_resource->meta_mutex);

    if (canvas_ptr)
        animate_destroy_canvas(canvas_ptr);
    pthread_mutex_unlock(&state->canvas_mutex);
}

void destroy_placement_resource(Resources *placement_resource)
{
    Resources *canvas_resource = NULL;
    Resources *sprite_resource = NULL;
    struct sprite_placement *placement = NULL;
    CanvasState *state = NULL;

    if (!placement_resource)
        return;
    canvas_resource = placement_resource->canvas_resource;
    sprite_resource = placement_resource->sprite_resource;
    state = canvas_resource ? canvas_resource->canvas_state : NULL;
    if (state)
    {
        pthread_mutex_lock(&state->meta_mutex);
        pthread_mutex_lock(&state->canvas_mutex);
    }

    pthread_mutex_lock(&placement_resource->meta_mutex);
    placement = (struct sprite_placement *)placement_resource->resource;
    placement_resource->resource = NULL;
    placement_resource->deleted = 1;
    pthread_mutex_unlock(&placement_resource->meta_mutex);

    if (placement)
    {
        animate_destroy_placement(placement);
        sprite_ref_decrement(sprite_resource);
    }
    if (state && state->placements)
    {
        for (ssize_t i = 0; i < state->placements->size; i++)
        {
            if (state->placements->data[i] == placement_resource)
            {
                for (ssize_t j = i + 1; j < state->placements->size; j++)
                    state->placements->data[j - 1] = state->placements->data[j];
                state->placements->size--;
                break;
            }
        }
    }
    if (state)
    {
        pthread_mutex_unlock(&state->canvas_mutex);
        pthread_mutex_unlock(&state->meta_mutex);
    }
}

void mark_canvas_placement_deleted(Resources *placement_resource)
{
    Resources *sprite_resource = NULL;
    struct sprite_placement *placement = NULL;

    if (!placement_resource)
        return;
    sprite_resource = placement_resource->sprite_resource;
    pthread_mutex_lock(&placement_resource->meta_mutex);
    placement = (struct sprite_placement *)placement_resource->resource;
    placement_resource->resource = NULL;
    placement_resource->deleted = 1;
    pthread_mutex_unlock(&placement_resource->meta_mutex);

    if (placement)
    {
        animate_destroy_placement(placement);
        if (sprite_resource)
        {
            sprite_ref_decrement(sprite_resource);

            pthread_mutex_lock(&sprite_resource->meta_mutex);
            if (sprite_resource->sprite_ref_count == 0 &&
                !client_id_is_online(sprite_resource->owner_client_id))
            {
                pthread_mutex_unlock(&sprite_resource->meta_mutex);
                cleanup_sprite_resource(sprite_resource);
            }
            else
                pthread_mutex_unlock(&sprite_resource->meta_mutex);
        }
    }
}

void cleanup_sprite_resource(Resources *sprite_resource)
{
    struct sprite *sprite_ptr = NULL;

    if (!sprite_resource)
        return;
    pthread_mutex_lock(&sprite_resource->meta_mutex);
    if (sprite_resource->sprite_ref_count > 0)
    {
        pthread_mutex_unlock(&sprite_resource->meta_mutex);
        return;
    }
    sprite_ptr = (struct sprite *)sprite_resource->resource;
    pthread_mutex_unlock(&sprite_resource->meta_mutex);
    if (sprite_ptr && !animate_destroy_sprite(sprite_ptr))
        mark_resource_deleted(sprite_resource);
}

static Vector *snapshot_vector(Vector *source)
{
    Vector *snapshot = Vector_init();

    if (!snapshot)
        return NULL;
    if (!source)
        return snapshot;

    for (ssize_t i = 0; i < source->size; i++)
        Vector_push_back(snapshot, source->data[i]);
    return snapshot;
}

void rpc_cleanup_client_resources(ClientData *data)
{
    Vector *access_snapshot = NULL;
    Vector *resource_snapshot = NULL;

    if (!data || !data->resources)
        return;

    pthread_mutex_lock(&data->resources_mutex);
    access_snapshot = snapshot_vector(data->accessiable_canvas);
    resource_snapshot = snapshot_vector(data->resources);
    pthread_mutex_unlock(&data->resources_mutex);
    if (!access_snapshot || !resource_snapshot)
    {
        Vector_free(access_snapshot);
        Vector_free(resource_snapshot);
        return;
    }

    for (ssize_t i = 0; i < access_snapshot->size; i++)
    {
        Resources *canvas_resource = (Resources *)access_snapshot->data[i];
        release_barrier_waiters(canvas_resource);

        if (canvas_resource && canvas_resource->canvas_state)
        {
            CanvasState *state = canvas_resource->canvas_state;
            pthread_mutex_lock(&state->meta_mutex);
            if (canvas_online_participant_count_locked(state) == 0)
                destroy_canvas_resource_locked(state, canvas_resource);
            pthread_mutex_unlock(&state->meta_mutex);
        }
    }

    for (ssize_t i = 0; i < resource_snapshot->size; i++)
    {
        Resources *resource = (Resources *)resource_snapshot->data[i];
        Resources *canvas_resource =
            resource ? resource->canvas_resource : NULL;
        CanvasState *state =
            canvas_resource ? canvas_resource->canvas_state : NULL;
        int canvas_still_used = 0;

        if (!resource || resource->type != Sprite_Placement)
            continue;
        if (state)
        {
            pthread_mutex_lock(&state->meta_mutex);
            canvas_still_used =
                canvas_online_participant_count_locked(state) > 0;
            pthread_mutex_unlock(&state->meta_mutex);
        }
        if (!canvas_still_used)
            destroy_placement_resource(resource);
    }

    for (ssize_t i = 0; i < resource_snapshot->size; i++)
    {
        Resources *resource = (Resources *)resource_snapshot->data[i];
        if (resource && resource->type == Sprite)
            cleanup_sprite_resource(resource);
    }

    Vector_free(access_snapshot);
    Vector_free(resource_snapshot);
}

static int resource_is_live(Resources *resource)
{
    int live = 0;

    if (!resource)
        return 0;
    pthread_mutex_lock(&resource->meta_mutex);
    live = !resource->deleted && resource->resource;
    pthread_mutex_unlock(&resource->meta_mutex);
    return live;
}

static int canvas_still_references_placement(Resources *placement_resource)
{
    Resources *canvas_resource = NULL;
    CanvasState *state = NULL;
    int referenced = 0;

    if (!placement_resource)
        return 0;
    canvas_resource = placement_resource->canvas_resource;
    state = canvas_resource ? canvas_resource->canvas_state : NULL;
    if (!state || !state->placements)
        return 0;

    pthread_mutex_lock(&state->meta_mutex);
    for (ssize_t i = 0; i < state->placements->size; i++)
    {
        if (state->placements->data[i] == placement_resource)
        {
            referenced = 1;
            break;
        }
    }
    pthread_mutex_unlock(&state->meta_mutex);
    return referenced;
}

static int disconnected_storage_can_be_released(ClientData *data)
{
    if (!data || !data->resources)
        return 0;

    for (ssize_t i = 0; i < data->resources->size; i++)
    {
        Resources *resource = (Resources *)data->resources->data[i];
        Resources *canvas_resource = NULL;

        if (!resource)
            continue;
        if (resource_is_live(resource))
            return 0;

        if (resource->type == Canvas)
            return 0;

        canvas_resource = resource->canvas_resource;
        if (resource->type == Sprite_Placement)
        {
            if (canvas_still_references_placement(resource))
                return 0;
            if (canvas_resource && resource_is_live(canvas_resource))
                return 0;
        }
    }
    return 1;
}

void release_disconnected_resource_storage(ClientData *data)
{
    Vector *old_resources = NULL;
    Vector *old_accessiable_canvas = NULL;
    Vector *new_resources = NULL;
    Vector *new_accessiable_canvas = NULL;

    if (!data || client_is_alive(data) || !data->resources ||
        !data->accessiable_canvas)
        return;

    new_resources = Vector_init();
    new_accessiable_canvas = Vector_init();
    if (!new_resources || !new_accessiable_canvas)
    {
        Vector_free(new_resources);
        Vector_free(new_accessiable_canvas);
        return;
    }

    pthread_mutex_lock(&data->resources_mutex);
    if (!disconnected_storage_can_be_released(data))
    {
        pthread_mutex_unlock(&data->resources_mutex);
        Vector_free(new_resources);
        Vector_free(new_accessiable_canvas);
        return;
    }

    old_resources = data->resources;
    old_accessiable_canvas = data->accessiable_canvas;
    data->resources = new_resources;
    data->accessiable_canvas = new_accessiable_canvas;
    pthread_mutex_unlock(&data->resources_mutex);

    Vector_deep_free(old_resources, (CleanFunc)Resources_free);
    Vector_free(old_accessiable_canvas);
}
