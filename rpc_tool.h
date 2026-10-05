#ifndef RPC_TOOL_H
#define RPC_TOOL_H

#include "thread_pool.h"
#include <animate/animate.h>
#include <stdbool.h>
#include <stdint.h>

void set_response(char *response, const char *message);
int has_unsigned_leading_zero(const char *token);
int has_signed_leading_zero(const char *token);
int parse_u64_token(const char *token, uint64_t *value);
int parse_size_token(const char *token, size_t *value);
int parse_bool_token(const char *token, bool *value);
int parse_color_token(const char *token, color_t *value);
int parse_ssize_token(const char *token, ssize_t *value);

uint64_t encode_resource_id(ClientData *data, Resources *resource);
uint32_t decode_client_id(uint64_t handle);
int handle_belongs_to_client(uint64_t handle, ClientData *data);
uint32_t decode_resource_id(uint64_t handle);

int resource_limit_reached(ClientData *data);
ClientData *find_client_data(uint32_t client_id);
int client_is_online(ClientData *data);
int client_id_is_online(int client_id);
ClientData *find_logged_in_client_by_username(const char *username);

int canvas_has_participant_locked(CanvasState *state, int client_id);
int canvas_online_participant_count_locked(CanvasState *state);
void add_canvas_access(ClientData *data, Resources *canvas_resource);

void mark_resource_deleted(Resources *resource);
void sprite_ref_increment(Resources *sprite_resource);
void sprite_ref_decrement(Resources *sprite_resource);

Resources *get_resource_from_handle(uint64_t handle,
                                    ResourcesType expected_type);
Resources *get_accessible_placement(ClientData *data, uint64_t handle);
void finish_created_resource(ClientData *data, Resources *resource,
                             char *response);
int has_canvas_access(ClientData *data, Resources *canvas_resource);

int barrier_waiter_index_locked(CanvasState *state, int client_id);
int all_online_participants_waiting_locked(CanvasState *state);
void release_barrier_waiters(Resources *canvas_resource);

void rpc_move_placement(ClientData *data, Vector *tokens, char *response,
                        void (*move_func)(struct sprite_placement *));

#endif /* RPC_TOOL_H */
