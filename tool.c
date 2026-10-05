#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/epoll.h>
#include <sys/stat.h>
#include <unistd.h>

#include "tool.h"

Client *Client_init()
{
    Client *client = malloc(sizeof(Client));
    if (!client)
        return NULL;
    client->client_pid = 0;
    client->fd_read = -1;
    client->fd_write = -1;
    client->c2s_name = malloc(sizeof(char) * MAX_PID_LEN);
    client->s2c_name = malloc(sizeof(char) * MAX_PID_LEN);
    if (client->c2s_name)
        client->c2s_name[0] = '\0';
    if (client->s2c_name)
        client->s2c_name[0] = '\0';
    if (!client->c2s_name || !client->s2c_name)
    {
        Client_free(client);
        return NULL;
    }
    // memset(client->padding_buffer, 0, sizeof(char) * MAX_COMMAND);
    client->padding_len = 0;
    memset(client->username, 0, sizeof(char) * USERNAME_MAX_LEN);

    client->is_logged_in = 0;
    client->is_rejected = 0;
    return client;
}

void Client_free(Client *client)
{
    if (!client)
        return;

    if (client->c2s_name && client->c2s_name[0] != '\0')
        unlink(client->c2s_name);
    if (client->s2c_name && client->s2c_name[0] != '\0')
        unlink(client->s2c_name);
    if (client->fd_read != -1)
        close(client->fd_read);
    if (client->fd_write != -1)
        close(client->fd_write);
    free(client->c2s_name);
    free(client->s2c_name);
    free(client);
}

struct CleanTask
{
    void *data;
    CleanFunc clean_func;
};
CleanTaskArray *CleanTask_init()
{
    CleanTaskArray *task = Vector_init();
    if (!task)
        return NULL;
    return task;
}
int CleanTask_add(CleanTaskArray *array, void *data, CleanFunc clean_func)
{
    if (!array)
        return -1;
    CleanTask *task = malloc(sizeof(CleanTask));
    if (!task)
        return -1;
    task->data = data;
    task->clean_func = clean_func;
    return Vector_push_back(array, task);
}
void Cleantask_free(CleanTaskArray *array)
{
    if (!array)
        return;
    for (ssize_t i = 0; i < array->size; i++)
    {
        CleanTask *task = (CleanTask *)array->data[i];
        if (task)
        {
            if (task->clean_func)
                task->clean_func(task->data);
            free(task);
        }
    }
    Vector_free(array);
}

void free_wrapper(void *ptr) { free(ptr); }
void close_wrapper(void *fd_ptr)
{
    if (fd_ptr)
        close((int)(intptr_t)fd_ptr);
}
/*
void unlink_wrapper(void *name_ptr)
{
    if(name_ptr) unlink((char*)name_ptr);
}*/
void commands_vector_clean_wrapper(void *commands)
{
    if (commands)
        Vector_deep_free((Vector *)commands, (CleanFunc)command_free);
}
void tokens_vector_clean_wrapper(void *tokens)
{
    if (tokens)
        Vector_deep_free((Vector *)tokens, (CleanFunc)free_wrapper);
}

int READ_STATUS;
ssize_t nonblock_readn(int fd, void *buf, ssize_t n)
{
    ssize_t tot_n = 0, nread;
    READ_STATUS = READ_SUCCESS;
    while (tot_n < n)
    {
        nread = read(fd, (char *)buf + tot_n, n - tot_n);
        if (nread == -1)
        {
            if (errno == EINTR)
                READ_STATUS = READ_SIGNAL_INTERUPTED;
            else if (errno == EAGAIN)
                READ_STATUS = READ_NONBLOCK_NO_DATA;
            else
                READ_STATUS = READ_UNKNOWN_ERROR;
            break;
        }
        if (nread == 0)
        {
            READ_STATUS = READ_FD_CLOSED;
            break;
        }
        tot_n += nread;
    }
    return tot_n;
}

const char terminator = '\n';
ssize_t nonblock_writen_with_terminator(int fd, const void *buf, ssize_t n)
{
    ssize_t tot_n = 0, nwritten;
    while (tot_n < n)
    {
        nwritten = write(fd, (const char *)buf + tot_n, n - tot_n);
        if (nwritten == -1)
        {
            if (errno == EINTR)
                continue;
            if (errno == EAGAIN)
                return WRITE_NONBLOCK_NO_SPACE;
            return WRITE_UNKNOWN_ERROR;
        }
        tot_n += nwritten;
    }
    if (n > 0 && ((const char *)buf)[n - 1] != terminator)
    {
        tot_n = 0;
        while (tot_n < 1)
        {
            nwritten = write(fd, &terminator + tot_n, 1 - tot_n);
            if (nwritten == -1)
            {
                if (errno == EINTR)
                    continue;
                if (errno == EAGAIN)
                    return WRITE_NONBLOCK_NO_SPACE;
                return WRITE_UNKNOWN_ERROR;
            }
            tot_n += nwritten;
        }
    }
    return WRITE_SUCCESS;
}

ssize_t nonblock_writen_without_terminator(int fd, const void *buf, ssize_t n)
{
    ssize_t tot_n = 0, nwritten;
    while (tot_n < n)
    {
        nwritten = write(fd, (const char *)buf + tot_n, n - tot_n);
        if (nwritten == -1)
        {
            if (errno == EINTR)
                continue;
            if (errno == EAGAIN)
                return WRITE_NONBLOCK_NO_SPACE;
            return WRITE_UNKNOWN_ERROR;
        }
        tot_n += nwritten;
    }
    return WRITE_SUCCESS;
}

// epoll tools
void add_epoll_event(int epoll_fd, void *event_data, int fd,
                     CleanTaskArray *clean_tasks)
{
    struct epoll_event ev;
    ev.events = EPOLLIN;
    ev.data.ptr = event_data;
    if (epoll_ctl(epoll_fd, EPOLL_CTL_ADD, fd, &ev) == -1)
        error_exit("[Epoll] Failed to add event to epoll", clean_tasks);
}

int init_epoll(CleanTaskArray *clean_tasks)
{
    int epoll_fd = epoll_create1(0);
    CleanTask_add(clean_tasks, (void *)(intptr_t)epoll_fd,
                  (CleanFunc)close_wrapper);
    if (epoll_fd == -1)
        error_exit("[Epoll] Failed to create epoll instance", clean_tasks);
    return epoll_fd;
}

// Utility functions
int my_atoi(const char *str)
{
    if (!str)
        return INT_MIN;
    int res = 0, sign = 1, i = 0;
    while (str[i] == ' ' || str[i] == '\t' || str[i] == '\n' || str[i] == '\r')
        i++;
    if (str[i] == '\0')
        return INT_MIN;

    if (str[i] == '-')
    {
        sign = -1;
        i++;
    }
    else if (str[i] == '+')
    {
        sign = 1;
        i++;
    }

    while (str[i] >= '0' && str[i] <= '9')
    {
        if (res > INT_MAX / 10)
            return INT_MIN;
        res = res * 10 + (str[i++] - '0');
    }
    if (str[i] != '\0')
        return INT_MIN;
    return res * sign;
}

// Command Tool
Command *Command_init(char *str, ssize_t len)
{
    Command *cmd = malloc(sizeof(Command));
    if (!cmd)
        return NULL;
    cmd->str = str;
    cmd->len = len;
    return cmd;
}

int iswhitespace(char c)
{
    return c == ' ' || c == '\t' || c == '\n' || c == '\r';
}
Vector *Command_tokenization(Command *cmd)
{
    if (!cmd || !cmd->str || cmd->len <= 0)
        return NULL;

    Vector *tokens = Vector_init();
    if (!tokens)
        return NULL;

    char *p = cmd->str;
    char *end = cmd->str + cmd->len;

    while (p < end)
    {
        while (p < end && iswhitespace(*p))
            p++;
        if (p >= end)
            break;
        char *token_start = p;

        while (p < end && !iswhitespace(*p))
            p++;
        ssize_t token_len = p - token_start;
        Vector_push_back(tokens, strndup(token_start, token_len));
    }
    return tokens;
}

void command_free(Command *cmd)
{
    if (!cmd)
        return;
    free(cmd->str);
    free(cmd);
}

Vector *padding_buffer_tokenization(Client *client, const char *buffer,
                                    ssize_t len)
{
    Vector *commands = Vector_init();
    if (!commands)
        return NULL;

    char command[MAX_COMMAND + 10];
    ssize_t command_len = 0;
    if (client->padding_len > MAX_COMMAND)
    {
        Vector_free(commands);
        return NULL;
    }
    memcpy(command, client->padding_buffer, client->padding_len);
    command_len = client->padding_len;

    char *p = (char *)buffer;
    while (p < buffer + len)
    {
        char *newline_ptr = (char *)memchr(p, '\n', buffer + len - p);
        if (newline_ptr)
        {
            ssize_t chunk_len = newline_ptr - p;
            if (command_len + chunk_len > MAX_COMMAND)
            {
                Vector_deep_free(commands, (CleanFunc)command_free);
                return NULL;
            }
            if (command_len + chunk_len == 0)
            {
                p = newline_ptr + 1;
                continue;
            }
            memcpy(command + command_len, p, chunk_len);
            command_len += chunk_len;
            Vector_push_back(
                commands,
                Command_init(strndup(command, command_len), command_len));
            command_len = 0;
            p = newline_ptr + 1;
        }
        else
        {
            ssize_t chunk_len = buffer + len - p;
            if (command_len + chunk_len > MAX_COMMAND)
            {
                Vector_deep_free(commands, (CleanFunc)command_free);
                return NULL;
            }
            memcpy(command + command_len, p, chunk_len);
            command_len += chunk_len;
            break;
        }
    }
    client->padding_len = command_len;
    memcpy(client->padding_buffer, command, command_len);
    return commands;
}

// Message Tool
const char *ClientMessage_str[] = {"Login", "Disconnect"};
const char *ServerMessage_str[] = {"Internal error", "Value error",
                                   "RPC Failed",     "Success",
                                   "Reject",         "Not logged in"};

void error_exit(const char *message, CleanTaskArray *clean_tasks)
{
    perror(message);
    Cleantask_free(clean_tasks);
    exit(1);
}

void set_nonblocking(int fd, CleanTaskArray *clean_tasks)
{
    int flags = fcntl(fd, F_GETFL, 0);
    if (flags == -1)
        error_exit("[Fcntl] Failed to get file status flags", clean_tasks);
    if (fcntl(fd, F_SETFL, flags | O_NONBLOCK) == -1)
        error_exit("[Fcntl] Failed to set file status flags", clean_tasks);
}
