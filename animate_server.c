#ifndef _POSIX_C_SOURCE
#define _POSIX_C_SOURCE 200809L
#endif

#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/epoll.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#include "thread_pool.h"
#include "timer.h"
#include "tool.h"

#define MAX_EVENTS (256)

static int self_pipe[2];
static CleanTaskArray *clean_tasks;

static void signal_handler_SIGUSR1(int sig, siginfo_t *info, void *context)
{
    (void)sig;
    (void)context;
    int saved_errno = errno;

    if (info != NULL)
        write(self_pipe[1], &info->si_pid, sizeof(pid_t));

    errno = saved_errno;
}

static void init_signal()
{
    struct sigaction sa = {0};
    sa.sa_sigaction = signal_handler_SIGUSR1;
    sa.sa_flags = SA_SIGINFO;
    sigemptyset(&sa.sa_mask);

    if (sigaction(SIGUSR1, &sa, NULL) == -1)
        error_exit("[Server] Sigaction failed: SIGUSR1", clean_tasks);
}

Client *connect_client()
{
    pid_t client_pid;
    int bytes_read = nonblock_readn(self_pipe[0], &client_pid, sizeof(pid_t));
    if (READ_STATUS == READ_UNKNOWN_ERROR)
    {
        perror("[Server] Failed to read from self-pipe");
        return NULL;
    }

    if (bytes_read == 0)
        return NULL;

    Client *client = Client_init();
    // CleanTask_add(clean_tasks, client, (CleanFunc) Client_free);
    if (client == NULL)
    {
        perror("[Server] Failed to initialize client");
        return NULL;
    }

    client->client_pid = client_pid;
    snprintf(client->c2s_name, sizeof(char) * MAX_PID_LEN, "FIFO_C2S_%d",
             client_pid);
    snprintf(client->s2c_name, sizeof(char) * MAX_PID_LEN, "FIFO_S2C_%d",
             client_pid);

    unlink(client->c2s_name);
    unlink(client->s2c_name);

    if (mkfifo(client->c2s_name, 0666) == -1 ||
        mkfifo(client->s2c_name, 0666) == -1)
    {
        perror("[Server] Create FIFO failed");
        Client_free(client);
        return NULL;
    }

    if (kill(client_pid, SIGUSR2) == -1)
    {
        perror("[Server] Failed to send SIGUSR2");
        Client_free(client);
        return NULL;
    }

    client->fd_read = open(client->c2s_name, O_RDONLY | O_NONBLOCK);
    client->fd_write = open(client->s2c_name, O_RDWR | O_NONBLOCK);
    if (client->fd_read == -1 || client->fd_write == -1)
    {
        perror("[Server] Failed to open FIFOs");
        Client_free(client);
        return NULL;
    }

    return client;
}

void request_client_destroy(ClientData *data)
{
    if (!data)
        return;
    if (!client_is_alive(data))
        return;

    pthread_mutex_lock(&data->ready_command_mutex);
    Vector_deep_free(data->ready_commands, (CleanFunc)command_free);
    data->ready_commands = Vector_init();

    char *response = malloc(sizeof(char) * strlen("Disconnect") + 1);
    strcpy(response, "Disconnect");
    Command *cmd = Command_init(response, strlen(response));
    Vector_push_back(data->ready_commands, cmd);
    pthread_mutex_unlock(&data->ready_command_mutex);

    push_client_to_queue(data);
}

void rpc_handle_client_request(ClientData *data)
{
    Client *client = NULL;
    Vector *commands = NULL;
    char buffer[BUFFER_SIZE];
    ssize_t bytes_read = 0;

    if (!data)
        return;

    pthread_mutex_lock(&data->state_mutex);
    if (!data->client_alive || !data->client)
    {
        pthread_mutex_unlock(&data->state_mutex);
        return;
    }
    client = data->client;
    bytes_read = nonblock_readn(client->fd_read, buffer, sizeof(buffer));
    if (READ_STATUS == READ_UNKNOWN_ERROR)
    {
        pthread_mutex_unlock(&data->state_mutex);
        error_exit("[Server] Failed to read from client FIFO", clean_tasks);
    }
    if (READ_STATUS == READ_FD_CLOSED)
    {
        pthread_mutex_unlock(&data->state_mutex);
        request_client_destroy(data);
        return;
    }

    commands = padding_buffer_tokenization(client, buffer, bytes_read);
    pthread_mutex_unlock(&data->state_mutex);
    if (!commands)
    {
        perror("[Server] Failed to parse client command");
        return;
    }
    pthread_mutex_lock(&data->ready_command_mutex);
    if (!data->ready_commands)
        data->ready_commands = commands;
    else
    {
        for (ssize_t i = 0; i < commands->size; i++)
        {
            Command *cmd = (Command *)commands->data[i];
            Vector_push_back(data->ready_commands, cmd);
        }
        Vector_free(commands);
    }
    pthread_mutex_unlock(&data->ready_command_mutex);
    // CleanTask_add(clean_tasks, commands, (CleanFunc)
    // commands_vector_clean_wrapper);
    push_client_to_queue(data);
}

int main(int argc, char **argv, char **envp)
{
    (void)envp;

    clean_tasks = CleanTask_init();
    if (!clean_tasks)
    {
        perror("[Server] Failed to initialize clean tasks");
        exit(1);
    }

    if (argc != 2)
        error_exit("[Server] Usage: ./animate_server <num_threads>",
                   clean_tasks);

    if (pipe(self_pipe) == -1)
        error_exit("[Server] Failed to create self-pipe", clean_tasks);
    set_nonblocking(self_pipe[0], clean_tasks);
    set_nonblocking(self_pipe[1], clean_tasks);
    CleanTask_add(clean_tasks, (void *)(intptr_t)self_pipe[0],
                  (CleanFunc)close_wrapper);
    CleanTask_add(clean_tasks, (void *)(intptr_t)self_pipe[1],
                  (CleanFunc)close_wrapper);

    /*FILE *fp = fopen("server_log", "w");
    if(fp == NULL)
        error_exit("[Server] Failed to open log file", clean_tasks);

    fprintf(fp, "%d", getpid());
    fclose(fp);*/

    init_signal();

    // Initialize epoll
    epoll_fd = init_epoll(clean_tasks);
    add_epoll_event(epoll_fd, NULL, self_pipe[0], clean_tasks);

    // Initialize thread pool
    num_threads = my_atoi(argv[1]);
    if (num_threads <= 0)
        error_exit("[Server] Invalid number of threads", clean_tasks);

    init_thread_pool(num_threads, clean_tasks);

    if (Timer_init(epoll_fd, clean_tasks) == -1)
        error_exit("[Server] Failed to initialize timer", clean_tasks);
    CleanTask_add(clean_tasks, NULL, (CleanFunc)Timer_free);

    // Start the server
    printf("Server PID: %d.\n", getpid());
    fflush(stdout);

    // Start epoll loop
    struct epoll_event events[MAX_EVENTS];
    ClientData *data;
    Client *client;
    while (1)
    {
        int timeout = get_epoll_timeout();
        // printf("Epoll wait timeout: %d ms\n", timeout);
        int nfds = epoll_wait(epoll_fd, events, MAX_EVENTS, timeout);
        if (nfds == -1)
        {
            if (errno == EINTR)
                continue;
            error_exit("[Server] Epoll wait failed", clean_tasks);
        }
        for (int i = 0; i < nfds; i++)
        {
            if (events[i].data.ptr == &timer_wake_pipe[0])
            {
                Timer_drain_wake_pipe();
                continue;
            }
            data = (ClientData *)events[i].data.ptr;
            // New client connection
            if (data == NULL)
            {
                while ((client = connect_client()) != NULL)
                {
                    ClientData *data = ClientData_init(client);
                    if (!data)
                    {
                        perror(
                            "[Server] Failed to initialize client extra data");
                        Client_free(client);
                        continue;
                    }
                    pthread_mutex_lock(&ClientResources_mutex);
                    data->client_id = ClientResources->size;
                    Vector_push_back(ClientResources, data);
                    pthread_mutex_unlock(&ClientResources_mutex);

                    add_epoll_event(epoll_fd, data, client->fd_read,
                                    clean_tasks);
                }
            }
            else
            {
                rpc_handle_client_request(data);
            }
        }
        process_expired_timers(request_client_destroy);
    }

    Cleantask_free(clean_tasks);
    return 0;
}
