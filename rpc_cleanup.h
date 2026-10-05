#ifndef RPC_CLEANUP_H
#define RPC_CLEANUP_H

#include "thread_pool.h"

void destroy_canvas_resource_locked(CanvasState *state,
                                    Resources *canvas_resource);
void destroy_placement_resource(Resources *placement_resource);
void mark_canvas_placement_deleted(Resources *placement_resource);
void cleanup_sprite_resource(Resources *sprite_resource);
void rpc_cleanup_client_resources(ClientData *data);
void release_disconnected_resource_storage(ClientData *data);

#endif /* RPC_CLEANUP_H */
