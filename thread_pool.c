#include <errno.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/epoll.h>

#include "queue.h"
#include "rpc.h"
#include "rpc_cleanup.h"
#include "thread_pool.h"
#include "timer.h"

int num_threads;
pthread_t *threads;
int epoll_fd;
Vector *ClientResources;
pthread_mutex_t ClientResources_mutex = PTHREAD_MUTEX_INITIALIZER;
static Queue *client_queue;
static pthread_mutex_t queue_mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t queue_cond = PTHREAD_COND_INITIALIZER;

pthread_mutex_t timer_mutex = PTHREAD_MUTEX_INITIALIZER;

static void ClientResources_free(void *ptr)
{
    Vector_deep_free((Vector *)ptr, (CleanFunc)ClientData_free);
}

static void ClientQueue_free(void *ptr)
{
    Queue *queue = (Queue *)ptr;
    queue_node *current = NULL;

    if (!queue)
        return;
    current = queue->head;
    while (current)
    {
        queue_node *next = current->next;
        free(current);
        current = next;
    }
    free(queue);
}

CanvasState *CanvasState_init()
{
    CanvasState *state = malloc(sizeof(CanvasState));
    if (!state)
        return NULL;

    state->participants = NULL;
    state->placements = NULL;
    state->barrier_waiters = NULL;
    state->height = 0;
    state->width = 0;

    pthread_mutex_init(&state->meta_mutex, NULL);
    pthread_mutex_init(&state->canvas_mutex, NULL);

    state->participants = Vector_init();
    state->placements = Vector_init();
    state->barrier_waiters = Vector_init();
    if (!state->participants || !state->placements || !state->barrier_waiters)
    {
        CanvasState_free(state);
        return NULL;
    }
    return state;
}

void CanvasState_free(CanvasState *state)
{
    if (!state)
        return;

    Vector_free(state->participants);
    Vector_free(state->placements);
    Vector_deep_free(state->barrier_waiters, free_wrapper);
    pthread_mutex_destroy(&state->canvas_mutex);
    pthread_mutex_destroy(&state->meta_mutex);
    free(state);
}

Resources *Resources_init(int resource_id, ResourcesType type, void *resource)
{
    Resources *res = malloc(sizeof(Resources));
    if (!res)
        return NULL;
    res->resource_id = resource_id;
    res->owner_client_id = -1;
    res->type = type;
    res->resource = resource;
    res->deleted = resource ? 0 : 1;
    res->sprite_ref_count = 0;
    res->canvas_state = NULL;
    res->canvas_resource = NULL;
    res->sprite_resource = NULL;
    pthread_mutex_init(&res->meta_mutex, NULL);
    if (type == Canvas)
    {
        res->canvas_state = CanvasState_init();
        if (!res->canvas_state)
        {
            pthread_mutex_destroy(&res->meta_mutex);
            free(res);
            return NULL;
        }
    }
    return res;
}

void Resources_free(Resources *res)
{
    if (!res)
        return;
    if (res->resource)
    {
        if (res->type == Canvas)
        {
            if (res->canvas_state && res->canvas_state->placements)
            {
                for (ssize_t i = 0; i < res->canvas_state->placements->size;
                     i++)
                {
                    Resources *placement =
                        (Resources *)res->canvas_state->placements->data[i];
                    if (placement)
                    {
                        placement->resource = NULL;
                        placement->deleted = 1;
                    }
                }
            }
            animate_destroy_canvas((canvas *)res->resource);
        }
        else if (res->type == Sprite)
            animate_destroy_sprite((sprite *)res->resource);
        else if (res->type == Sprite_Placement)
            animate_destroy_placement((sprite_placement *)res->resource);
    }
    CanvasState_free(res->canvas_state);
    pthread_mutex_destroy(&res->meta_mutex);
    free(res);
}

ClientData *ClientData_init(Client *client)
{
    ClientData *data = malloc(sizeof(ClientData));
    if (!data)
        return NULL;
    data->client_id = 0;
    pthread_mutex_init(&data->state_mutex, NULL);
    data->client_alive = 1;
    data->client = client;

    pthread_mutex_init(&data->resources_mutex, NULL);
    pthread_mutex_init(&data->ready_command_mutex, NULL);
    pthread_mutex_init(&data->Client_process_mutex, NULL);
    data->resources = Vector_init();
    data->ready_commands = Vector_init();
    data->doing_commands = Vector_init();
    data->accessiable_canvas = Vector_init();
    data->blocked_on_barrier = 0;
    if (!data->resources || !data->ready_commands || !data->doing_commands ||
        !data->accessiable_canvas)
    {
        ClientData_free(data);
        return NULL;
    }
    return data;
}

void ClientData_free(ClientData *data)
{
    if (!data)
        return;
    Client_free(client_detach(data));
    // resources free
    Vector_deep_free(data->resources, (CleanFunc)Resources_free);
    // commands free
    Vector_deep_free(data->ready_commands, (CleanFunc)command_free);
    Vector_deep_free(data->doing_commands, (CleanFunc)command_free);
    Vector_free(data->accessiable_canvas);
    pthread_mutex_destroy(&data->state_mutex);
    pthread_mutex_destroy(&data->resources_mutex);
    pthread_mutex_destroy(&data->ready_command_mutex);
    pthread_mutex_destroy(&data->Client_process_mutex);
    free(data);
}

int client_is_alive(ClientData *data)
{
    int alive = 0;

    if (!data)
        return 0;
    pthread_mutex_lock(&data->state_mutex);
    alive = data->client_alive;
    pthread_mutex_unlock(&data->state_mutex);
    return alive;
}

int client_is_blocked_on_barrier(ClientData *data)
{
    int blocked = 0;

    if (!data)
        return 0;
    pthread_mutex_lock(&data->state_mutex);
    blocked = data->blocked_on_barrier;
    pthread_mutex_unlock(&data->state_mutex);
    return blocked;
}

void client_set_blocked_on_barrier(ClientData *data, int blocked)
{
    if (!data)
        return;
    pthread_mutex_lock(&data->state_mutex);
    data->blocked_on_barrier = blocked ? 1 : 0;
    pthread_mutex_unlock(&data->state_mutex);
}

int client_mark_disconnected(ClientData *data, int *fd_read)
{
    if (!data)
        return 0;

    pthread_mutex_lock(&data->state_mutex);
    if (data->client_alive == 0)
    {
        pthread_mutex_unlock(&data->state_mutex);
        return 0;
    }

    data->client_alive = 0;
    data->blocked_on_barrier = 0;
    if (fd_read)
        *fd_read = data->client ? data->client->fd_read : -1;
    pthread_mutex_unlock(&data->state_mutex);
    return 1;
}

Client *client_detach(ClientData *data)
{
    Client *client = NULL;

    if (!data)
        return NULL;
    pthread_mutex_lock(&data->state_mutex);
    client = data->client;
    data->client = NULL;
    pthread_mutex_unlock(&data->state_mutex);
    return client;
}

void *thread_func(void *arg);

void init_thread_pool(int num_threads, CleanTaskArray *clean_tasks)
{
    client_queue = Queue_init();
    if (!client_queue)
        error_exit("[Server] Failed to initialize client queue", clean_tasks);
    CleanTask_add(clean_tasks, client_queue, ClientQueue_free);

    threads = malloc(sizeof(pthread_t) * num_threads);
    if (!threads)
        error_exit("[Server] Failed to allocate memory for threads",
                   clean_tasks);
    CleanTask_add(clean_tasks, threads, (CleanFunc)free_wrapper);

    for (int i = 0; i < num_threads; i++)
        if (pthread_create(&threads[i], NULL, thread_func, NULL) != 0)
            error_exit("[Server] Failed to create thread", clean_tasks);

    ClientResources = Vector_init();
    if (!ClientResources)
        error_exit("[Server] Failed to initialize client resources",
                   clean_tasks);
    Vector_push_back(ClientResources, NULL);
    CleanTask_add(clean_tasks, ClientResources, ClientResources_free);
}

void threads_free()
{
    if (!threads)
        return;
    for (int i = 0; i < num_threads; i++)
        pthread_join(threads[i], NULL);
    free(threads);
}

void release_client_resources(ClientData *data)
{
    int fd_read = -1;

    if (!client_mark_disconnected(data, &fd_read))
        return;
    if (fd_read != -1)
        epoll_ctl(epoll_fd, EPOLL_CTL_DEL, fd_read, NULL);
    rpc_cleanup_client_resources(data);
    release_disconnected_resource_storage(data);
}

int ready_commands_has_disconnect_locked(ClientData *data)
{
    if (!data || !data->ready_commands)
        return 0;

    for (ssize_t i = 0; i < data->ready_commands->size; i++)
    {
        Command *cmd = (Command *)data->ready_commands->data[i];
        if (cmd && cmd->str && strcmp(cmd->str, "Disconnect") == 0)
            return 1;
    }
    return 0;
}

void replace_ready_with_disconnect_locked(ClientData *data)
{
    char *response = NULL;
    Command *cmd = NULL;

    if (!data)
        return;

    Vector_deep_free(data->doing_commands, (CleanFunc)command_free);
    data->doing_commands = NULL;
    Vector_deep_free(data->ready_commands, (CleanFunc)command_free);
    data->ready_commands = Vector_init();

    response = malloc(sizeof(char) * strlen("Disconnect") + 1);
    if (!response || !data->ready_commands)
    {
        free(response);
        return;
    }
    strcpy(response, "Disconnect");
    cmd = Command_init(response, strlen(response));
    Vector_push_back(data->ready_commands, cmd);
}

int server_rpc_handler(ClientData *data, Vector *tokens)
{
    char response[MAX_COMMAND];

    if (!data || !data->client || !tokens || tokens->size == 0)
        return 0;
    response[0] = '\0';
    char *command = (char *)tokens->data[0];
    if (strcmp(command, "Disconnect") == 0)
    {
        release_client_resources(data);
        return 0;
    }
    else if (strcmp(command, "create_canvas") == 0)
        rpc_create_canvas(data, tokens, response);
    else if (strcmp(command, "create_sprite") == 0)
        rpc_create_sprite(data, tokens, response);
    else if (strcmp(command, "create_rectangle") == 0)
        rpc_create_rectangle(data, tokens, response);
    else if (strcmp(command, "create_circle") == 0)
        rpc_create_circle(data, tokens, response);
    else if (strcmp(command, "place_sprite") == 0)
        rpc_place_sprite(data, tokens, response);
    else if (strcmp(command, "placement_up") == 0)
        rpc_placement_up(data, tokens, response);
    else if (strcmp(command, "placement_down") == 0)
        rpc_placement_down(data, tokens, response);
    else if (strcmp(command, "placement_top") == 0)
        rpc_placement_top(data, tokens, response);
    else if (strcmp(command, "placement_bottom") == 0)
        rpc_placement_bottom(data, tokens, response);
    else if (strcmp(command, "set_animation_params") == 0)
        rpc_set_animation_params(data, tokens, response);
    else if (strcmp(command, "destroy_canvas") == 0)
        rpc_destroy_canvas(data, tokens, response);
    else if (strcmp(command, "destroy_sprite") == 0)
        rpc_destroy_sprite(data, tokens, response);
    else if (strcmp(command, "destroy_placement") == 0)
        rpc_destroy_placement(data, tokens, response);
    else if (strcmp(command, "generate") == 0)
        rpc_generate(data, tokens, response);
    else if (strcmp(command, "share_canvas") == 0)
        rpc_share_canvas(data, tokens, response);
    else if (strcmp(command, "barrier") == 0)
    {
        int pending = rpc_barrier(data, tokens, response);
        if (pending)
            return 1;
    }
    else
        snprintf(response, sizeof(response), "-1"); // RPC Failed

    if (response[0] != '\0')
        nonblock_writen_with_terminator(data->client->fd_write, response,
                                        strlen(response));
    return 0;
}

int client_can_handle_rpc(ClientData *data)
{
    int can_handle = 0;

    if (!data)
        return 0;
    pthread_mutex_lock(&data->state_mutex);
    can_handle = data->client_alive && data->client &&
                 (data->client->is_logged_in || data->client->is_rejected);
    pthread_mutex_unlock(&data->state_mutex);
    return can_handle;
}

int server_login_handler(ClientData *data, Vector *tokens)
{
    // if (!client || !tokens) return;
    int fd_write = -1;
    int logged_in = 0;

    if (!data)
        return 0;
    pthread_mutex_lock(&data->state_mutex);
    if (!data->client_alive || !data->client)
    {
        pthread_mutex_unlock(&data->state_mutex);
        return 0;
    }
    fd_write = data->client->fd_write;
    pthread_mutex_unlock(&data->state_mutex);

    if (tokens->size != 2 || strcmp((char *)tokens->data[0], "Login") != 0)
    {
        char *response = (char *)ServerMessage_str[NOT_LOGGED_IN];
        if (fd_write != -1)
            nonblock_writen_with_terminator(fd_write, response,
                                            strlen(response));
        return 1;
    }
    char *username = (char *)tokens->data[1];

    FILE *fp = fopen("users.txt", "r");
    if (!fp)
    {
        perror("[Server] Failed to open users.txt");
        pthread_mutex_lock(&data->state_mutex);
        if (data->client_alive && data->client)
        {
            data->client->is_rejected = 1;
            fd_write = data->client->fd_write;
        }
        pthread_mutex_unlock(&data->state_mutex);
        const char *err_msg = "Reject UNAUTHORISED";
        if (fd_write != -1)
            nonblock_writen_with_terminator(fd_write, err_msg,
                                            strlen(err_msg));
        return 1;
    }

    char file_user[USERNAME_MAX_LEN];
    int file_balance;
    int found = 0;
    int balance = 0;

    while (fscanf(fp, "%32s %d", file_user, &file_balance) == 2)
    {
        if (strcmp(username, file_user) == 0)
        {
            found = 1;
            balance = file_balance;
            break;
        }
    }
    fclose(fp);

    char response[MAX_COMMAND];
    pthread_mutex_lock(&data->state_mutex);
    if (!data->client_alive || !data->client)
    {
        pthread_mutex_unlock(&data->state_mutex);
        return 0;
    }
    if (found)
    {
        if (balance > 0)
        {
            data->client->is_logged_in = 1;
            strncpy(data->client->username, username, USERNAME_MAX_LEN - 1);
            data->client->username[USERNAME_MAX_LEN - 1] = '\0';
            snprintf(response, sizeof(response), "%d", balance);
        }
        else
        {
            data->client->is_rejected = 1;
            snprintf(response, sizeof(response), "Reject BALANCE");
        }
    }
    else
    {
        data->client->is_rejected = 1;
        snprintf(response, sizeof(response), "Reject UNAUTHORISED");
    }
    fd_write = data->client->fd_write;
    logged_in = data->client->is_logged_in;
    pthread_mutex_unlock(&data->state_mutex);

    if (fd_write != -1)
        nonblock_writen_with_terminator(fd_write, response, strlen(response));
    return logged_in;
}

void process_command(ClientData *data)
{
    if (!data || !data->doing_commands)
        return;
    Vector *commands = data->doing_commands;
    if (commands->size == 0 || !client_is_alive(data) ||
        client_is_blocked_on_barrier(data))
        return;

    for (ssize_t i = 0; i < commands->size; i++)
    {
        Command *cmd = (Command *)commands->data[i];
        if (!cmd)
            continue;

        // test
        // printf("Processing command from client %d: %s\n", data->client_id,
        // cmd->str);

        Vector *tokens = Command_tokenization(cmd);
        if (!tokens)
        {
            perror("[Server] Failed to tokenize command");
            continue;
        }
        if (client_can_handle_rpc(data))
        {
            int pending = server_rpc_handler(data, tokens);
            Vector_deep_free(tokens, (CleanFunc)free_wrapper);
            command_free(cmd);
            commands->data[i] = NULL;
            if (pending)
                return;
            if (!client_is_alive(data))
                return;
            continue;
        }
        else if (!server_login_handler(data, tokens))
        {
            add_delay_delete_task(data);
            Vector_deep_free(tokens, (CleanFunc)free_wrapper);
            command_free(cmd);
            commands->data[i] = NULL;
            return;
        }
        Vector_deep_free(tokens, (CleanFunc)free_wrapper);
        command_free(cmd);
        commands->data[i] = NULL;
    }
}

void *thread_func(void *arg)
{
    (void)arg;
    ClientData *data;
    while (1)
    {
        pthread_mutex_lock(&queue_mutex);
        while (client_queue->head == NULL)
            pthread_cond_wait(&queue_cond, &queue_mutex);

        data = Queue_pop(client_queue);
        if (!data || !client_is_alive(data))
        {
            pthread_mutex_unlock(&queue_mutex);
            continue;
        }

        if (pthread_mutex_trylock(&data->Client_process_mutex) == EBUSY)
        {
            pthread_mutex_unlock(&queue_mutex);
            continue;
        }
        pthread_mutex_unlock(&queue_mutex);
        if (client_is_blocked_on_barrier(data))
        {
            int destroy_requested = 0;

            pthread_mutex_lock(&data->ready_command_mutex);
            destroy_requested = ready_commands_has_disconnect_locked(data);
            if (destroy_requested)
                replace_ready_with_disconnect_locked(data);
            pthread_mutex_unlock(&data->ready_command_mutex);

            if (!destroy_requested)
            {
                pthread_mutex_unlock(&data->Client_process_mutex);
                continue;
            }
            client_set_blocked_on_barrier(data, 0);
        }

        // deadlock prevention
        pthread_mutex_lock(&data->ready_command_mutex);
        do
        {
            pthread_mutex_unlock(&data->ready_command_mutex);
            if (data->doing_commands)
                process_command(data);
            if (client_is_blocked_on_barrier(data))
            {
                pthread_mutex_lock(&data->ready_command_mutex);
                break;
            }
            Vector_deep_free(data->doing_commands, (CleanFunc)command_free);
            data->doing_commands = NULL;
            pthread_mutex_lock(&data->ready_command_mutex);
            if (!client_is_alive(data))
                break;
            data->doing_commands = data->ready_commands;
            data->ready_commands = NULL;
        } while (data->doing_commands || data->ready_commands);

        pthread_mutex_unlock(&data->Client_process_mutex);
        pthread_mutex_unlock(&data->ready_command_mutex);

        if (!client_is_alive(data))
        {
            Client_free(client_detach(data));
            Vector_deep_free(data->ready_commands, (CleanFunc)command_free);
            data->ready_commands = NULL;
            Vector_deep_free(data->doing_commands, (CleanFunc)command_free);
            data->doing_commands = NULL;
        }
    }
    return NULL;
}

void push_client_to_queue(ClientData *data)
{
    pthread_mutex_lock(&queue_mutex);
    if (pthread_mutex_trylock(&data->Client_process_mutex) == EBUSY)
    {
        pthread_mutex_unlock(&queue_mutex);
        return; // thread is doing this client
    }
    Queue_push(client_queue, data);
    if (client_queue->status == QUEUE_ERROR)
    {
        perror("[Server] Failed to push client to queue");
        pthread_mutex_unlock(&data->Client_process_mutex);
        pthread_mutex_unlock(&queue_mutex);
        return;
    }

    pthread_mutex_unlock(&data->Client_process_mutex);
    pthread_cond_signal(&queue_cond);
    pthread_mutex_unlock(&queue_mutex);
}
