#ifndef THREAD_POOL_H
#define THREAD_POOL_H

#include "tool.h"
#include "vector.h"
#include <pthread.h>

extern int num_threads;
extern int epoll_fd;
// extern pthread_t *threads;
extern Vector *ClientResources;
extern pthread_mutex_t timer_mutex;
extern pthread_mutex_t ClientResources_mutex;

typedef enum
{
    Canvas,
    Sprite,
    Sprite_Placement
} ResourcesType;

typedef struct ClientData ClientData;
typedef struct Resources Resources;

typedef struct CanvasBarrierWaiter
{
    int client_id;
} CanvasBarrierWaiter;

typedef struct CanvasState
{
    // Protects participants, placements and barrier_waiters.
    pthread_mutex_t meta_mutex;
    // Protects libanimate canvas operations.
    pthread_mutex_t canvas_mutex;

    // Vector<(void*)(intptr_t)client_id> for active canvas participants.
    Vector *participants;
    // Vector<Resources*> for placements created on this canvas.
    Vector *placements;
    Vector *barrier_waiters;
    size_t height;
    size_t width;
} CanvasState;
CanvasState *CanvasState_init();
void CanvasState_free(CanvasState *state);

typedef struct Resources
{
    int resource_id;
    int owner_client_id;
    ResourcesType type;
    pthread_mutex_t meta_mutex;
    void *resource;
    int deleted;
    int sprite_ref_count; // only used for Sprite

    CanvasState *canvas_state;         // only used for Canvas
    struct Resources *canvas_resource; // only used for Sprite_Placement
    struct Resources *sprite_resource; // only used for Sprite_Placement
} Resources;
Resources *Resources_init(int resource_id, ResourcesType type, void *resource);
void Resources_free(Resources *res);

struct ClientData
{
    int client_id;
    pthread_mutex_t state_mutex;
    int client_alive;

    Client *client;
    Vector *accessiable_canvas;

    // thread shared data
    pthread_mutex_t resources_mutex;
    Vector *resources;
    pthread_mutex_t ready_command_mutex;
    Vector *ready_commands;
    pthread_mutex_t Client_process_mutex;
    Vector *doing_commands;
    int blocked_on_barrier;
};
ClientData *ClientData_init(Client *client);
void ClientData_free(ClientData *data);
int client_is_alive(ClientData *data);
int client_is_blocked_on_barrier(ClientData *data);
void client_set_blocked_on_barrier(ClientData *data, int blocked);
int client_mark_disconnected(ClientData *data, int *fd_read);
Client *client_detach(ClientData *data);

void init_thread_pool(int num_threads, CleanTaskArray *clean_tasks);
void threads_free();
void push_client_to_queue(ClientData *data);

#endif /* THREAD_POOL_H */
