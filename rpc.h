#ifndef RPC_H
#define RPC_H

#include <animate/animate.h>

#include "thread_pool.h"

typedef struct canvas canvas;
typedef struct sprite_placement sprite_placement;
typedef struct sprite sprite;
void rpc_create_canvas(ClientData *data, Vector *tokens, char *response);
void rpc_create_sprite(ClientData *data, Vector *tokens, char *response);
void rpc_create_rectangle(ClientData *data, Vector *tokens, char *response);
void rpc_create_circle(ClientData *data, Vector *tokens, char *response);
void rpc_place_sprite(ClientData *data, Vector *tokens, char *response);
void rpc_placement_up(ClientData *data, Vector *tokens, char *response);
void rpc_placement_down(ClientData *data, Vector *tokens, char *response);
void rpc_placement_top(ClientData *data, Vector *tokens, char *response);
void rpc_placement_bottom(ClientData *data, Vector *tokens, char *response);
void rpc_set_animation_params(ClientData *data, Vector *tokens, char *response);
void rpc_destroy_canvas(ClientData *data, Vector *tokens, char *response);
void rpc_destroy_sprite(ClientData *data, Vector *tokens, char *response);
void rpc_destroy_placement(ClientData *data, Vector *tokens, char *response);
void rpc_generate(ClientData *data, Vector *tokens, char *response);
void rpc_share_canvas(ClientData *data, Vector *tokens, char *response);
int rpc_barrier(ClientData *data, Vector *tokens, char *response);

#endif /* RPC_H */
