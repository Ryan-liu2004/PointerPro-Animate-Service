#ifndef _POSIX_C_SOURCE
#define _POSIX_C_SOURCE 200809L
#endif

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/epoll.h>
#include <sys/stat.h>
#include <unistd.h>

#include "tool.h"

#define MAX_EVENTS (2)

volatile sig_atomic_t sigusr2_flag = 0;
volatile sig_atomic_t timeout_flag = 0;
static CleanTaskArray *clean_tasks;
static int epoll_fd;

void signal_handler(int sig, siginfo_t *info, void *context)
{
    (void)context;
    (void)info;
    if (sig == SIGALRM)
        timeout_flag = 1;
    else if (sig == SIGUSR2)
        sigusr2_flag = 1;
}

void init_signal()
{
    struct sigaction sa = {0};
    sa.sa_sigaction = signal_handler;
    sa.sa_flags = SA_SIGINFO;
    sigemptyset(&sa.sa_mask);

    if (sigaction(SIGUSR2, &sa, NULL) == -1)
        error_exit("[Client] Sigaction failed: SIGUSR2", clean_tasks);
    if (sigaction(SIGALRM, &sa, NULL) == -1)
        error_exit("[Client] Sigaction failed: SIGALRM", clean_tasks);
}

void connect_to_server(Client *client)
{
    pid_t pid = getpid();
    client->client_pid = pid;
    snprintf(client->c2s_name, sizeof(char) * MAX_PID_LEN, "FIFO_C2S_%d", pid);
    snprintf(client->s2c_name, sizeof(char) * MAX_PID_LEN, "FIFO_S2C_%d", pid);

    client->fd_read = open(client->s2c_name, O_RDONLY | O_NONBLOCK);
    client->fd_write = open(client->c2s_name, O_WRONLY);

    if (client->fd_read == -1 || client->fd_write == -1)
        error_exit("[Client] Failed to open FIFOs", clean_tasks);
}

void parse_error(char *message, Vector *tokens, Vector *commands,
                 CleanTaskArray *clean_tasks)
{
    if (tokens)
        Vector_deep_free(tokens, (CleanFunc)free_wrapper);
    if (commands)
        Vector_deep_free(commands, (CleanFunc)command_free);
    error_exit(message, clean_tasks);
}

int stdin_handler(Client *client, Vector *commands)
{
    for (ssize_t j = 0; j < commands->size; j++)
    {
        Command *cmd = (Command *)commands->data[j];
        ssize_t bytes_written = nonblock_writen_with_terminator(
            client->fd_write, cmd->str, cmd->len);
        if (bytes_written == WRITE_NONBLOCK_NO_SPACE)
            perror("[Client] Server is busy, failed to write command");
        else if (bytes_written == WRITE_UNKNOWN_ERROR)
            perror("[Client] Failed to write to server");
        if (strncmp(cmd->str, "Login ", strlen("Login ")) == 0)
        {
            // Extract username
            char *username = cmd->str + strlen("Login ");
            ssize_t username_len = cmd->len - strlen("Login ");
            // exclude "Login " and '\n'
            if (username_len <= 0 || username_len >= USERNAME_MAX_LEN)
                parse_error("[Client] Invalid username length", NULL, commands,
                            clean_tasks);
            memcpy(client->username, username, username_len);
            client->username[username_len] = '\0';
        }
        if (strcmp(cmd->str, ClientMessage_str[DISCONNECT]) == 0)
        {
            Vector_deep_free(commands, (CleanFunc)command_free);
            Cleantask_free(clean_tasks);
            return 0;
        }
    }
    return 1;
}

int login_handler(Client *client, Vector *commands, Vector *tokens,
                  Command *cmd)
{
    if (tokens->size == 1)
    {
        int balance = my_atoi(tokens->data[0]);
        if (balance == INT_MIN)
        {
            parse_error("[Client] Invalid balance received from server", tokens,
                        commands, clean_tasks);
        }
        client->is_logged_in = 1;
        printf("Welcome %s. Your balance is %d\n", client->username, balance);
    }
    else if (tokens->size == 2 &&
             strcmp(tokens->data[0], ServerMessage_str[REJECT]) == 0)
    {
        client->is_rejected = 1;
        printf("%s %s\n", ServerMessage_str[REJECT], (char *)tokens->data[1]);
        Vector_deep_free(tokens, (CleanFunc)free_wrapper);
        Vector_deep_free(commands, (CleanFunc)command_free);
        Cleantask_free(clean_tasks);
        return 0;
    }
    else if (strcmp(cmd->str, ServerMessage_str[NOT_LOGGED_IN]) == 0)
        printf("%s\n", ServerMessage_str[NOT_LOGGED_IN]);
    else
        parse_error("[Client] Unexpected response from server", tokens,
                    commands, clean_tasks);
    return 1;
}

void rpc_handler(Command *cmd, Vector *tokens)
{
    if (cmd->str[0] - '0' == SUCCESS + ServerMessage_SHIFT)
    {
        if (strcmp(cmd->str, "0") == 0)
            printf("Success\n");
        else if (tokens->size == 2)
        {
            if (strcmp(cmd->str, "0 -1") == 0)
                printf("Data write failed\n");
            else
                printf("Success %s\n", (char *)tokens->data[1]);
        }
        else if (strcmp(cmd->str, "0 0 0") == 0)
            printf("Success\n");
        else if (strcmp(cmd->str, "0 0 -1") == 0)
            printf("Movie write failed\n");
        else
        {
            perror("[Client] Unexpected response from server");
        }
    }
    else
    {
        int status = my_atoi(cmd->str);
        if (status >= INTERNAL_ERROR + ServerMessage_SHIFT &&
            status <= RPC_FAILED + ServerMessage_SHIFT)
            printf("%s\n", ServerMessage_str[status - ServerMessage_SHIFT]);
        else
            perror("[Client] Invalid status code received from server");
    }
}

int server_handler(Client *client, Vector *commands)
{
    for (ssize_t j = 0; j < commands->size; j++)
    {
        Command *cmd = (Command *)commands->data[j];
        Vector *tokens = Command_tokenization(cmd);
        if (!tokens)
        {
            perror("[Client] Failed to tokenize server response");
            continue;
        }
        if (client->is_logged_in)
            rpc_handler(cmd, tokens);
        else if (!client->is_rejected)
            if (!login_handler(client, commands, tokens, cmd))
                return 0;
        Vector_deep_free(tokens, (CleanFunc)free_wrapper);
        fflush(stdout);
    }
    return 1;
}

int main(int argc, char **argv, char **envp)
{
    (void)envp;

    /*int pid;
    if(argc != 2)
    {

        FILE *fp = fopen("server_log", "r");
        if(fp == NULL)
        {
            perror("[Client] Failed to open log file");
            exit(1);
        }
        char line[BUFFER_SIZE];
        if(fgets(line, sizeof(line), fp) == NULL)
        {
            perror("[Client] Failed to read from log file");
            fclose(fp);
            exit(1);
        }
        pid = my_atoi(line);
        fclose(fp);
    }
    else {pid = my_atoi(argv[1]);}*/

    if (argc != 2)
    {
        perror("[Client] Incorrect number of arguments");
        return 1;
    }

    int pid = my_atoi(argv[1]);

    if (pid == INT_MIN)
    {
        perror("[Client] Invalid server PID");
        return 1;
    }
    clean_tasks = CleanTask_init();
    if (!clean_tasks)
    {
        perror("[Client] Failed to initialize clean tasks");
        return 1;
    }

    Client *client = Client_init();
    Client *stdin_client = Client_init();
    if (client == NULL || stdin_client == NULL)
        error_exit("[Client] Failed to initialize client", clean_tasks);
    CleanTask_add(clean_tasks, client, (CleanFunc)Client_free);
    CleanTask_add(clean_tasks, stdin_client, (CleanFunc)Client_free);

    pid_t server_pid = (pid_t)pid;
    init_signal();
    if (kill(server_pid, SIGUSR1) == -1)
        error_exit("[Client] Kill failed", clean_tasks);
    alarm(1);
    while (!sigusr2_flag && !timeout_flag)
        pause();
    if (!sigusr2_flag && timeout_flag)
        error_exit("[Client] Connection timeout", clean_tasks);

    connect_to_server(client);

    epoll_fd = init_epoll(clean_tasks);
    add_epoll_event(epoll_fd, client, client->fd_read, clean_tasks);
    stdin_client->fd_read = STDIN_FILENO;
    set_nonblocking(stdin_client->fd_read, clean_tasks);
    add_epoll_event(epoll_fd, stdin_client, stdin_client->fd_read, clean_tasks);

    struct epoll_event events[MAX_EVENTS];
    char buffer[BUFFER_SIZE];
    Client *epoll_client;
    while (1)
    {
        int nfds = epoll_wait(epoll_fd, events, MAX_EVENTS, -1);
        if (nfds == -1)
        {
            if (errno == EINTR)
                continue;
            error_exit("[Client] Epoll wait failed", clean_tasks);
        }
        for (int i = 0; i < nfds; i++)
        {
            epoll_client = (Client *)events[i].data.ptr;
            ssize_t bytes_read =
                nonblock_readn(epoll_client->fd_read, buffer, sizeof(buffer));
            if (bytes_read == -1)
            {
                if (errno == EAGAIN)
                    continue;
                // error_exit("[Client] Failed to read from stdin",
                // clean_tasks);
            }
            if (bytes_read == 0)
                error_exit("[Client] EOF on stdin or FIFO", clean_tasks);

            Vector *commands =
                padding_buffer_tokenization(epoll_client, buffer, bytes_read);
            if (!commands)
            {
                perror("[Client] Failed to tokenize commands");
                continue;
            }
            if (epoll_client == stdin_client)
            {
                // Input from stdin
                if (!stdin_handler(client, commands))
                    return 0;
            }
            else
            {
                // Response from server
                if (!server_handler(client, commands))
                    return 0;
            }
            Vector_deep_free(commands, (CleanFunc)command_free);
        }
    }
    Cleantask_free(clean_tasks);
    return 0;
}
