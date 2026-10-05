#ifndef TOOL_H
#define TOOL_H

#include <limits.h>
#include <sys/types.h>

#include "vector.h"

#define BUFFER_SIZE (PIPE_BUF > 1024 ? 1024 : PIPE_BUF)
#define MAX_COMMAND (256)
#define MAX_PID_LEN (64)

// Client Tool
#define USERNAME_MAX_LEN (32 + 1)
typedef struct
{
    pid_t client_pid;
    int fd_read;
    int fd_write;
    char *c2s_name;
    char *s2c_name;
    char padding_buffer[MAX_COMMAND];
    char username[USERNAME_MAX_LEN];
    int padding_len;

    // flags
    int is_logged_in;
    int is_rejected;
} Client;
Client *Client_init();
void Client_free(Client *client);

// Memory Clean Tool
typedef void (*CleanFunc)(void *);
typedef Vector CleanTaskArray;
typedef struct CleanTask CleanTask;
CleanTaskArray *CleanTask_init();
int CleanTask_add(CleanTaskArray *array, void *data, CleanFunc clean_func);
void Cleantask_free(CleanTaskArray *array);

void free_wrapper(void *ptr);
void close_wrapper(void *fd_ptr);
// void unlink_wrapper(void *name_ptr);
void commands_vector_clean_wrapper(void *commands);
void tokens_vector_clean_wrapper(void *tokens);

#define READ_SUCCESS (-1)
#define READ_FD_CLOSED (-2)
#define READ_SIGNAL_INTERUPTED (-3)
#define READ_NONBLOCK_NO_DATA (-4)
#define READ_UNKNOWN_ERROR (-5)
extern int READ_STATUS;
ssize_t nonblock_readn(int fd, void *buf, ssize_t n);
#define WRITE_SUCCESS (0)
#define WRITE_NONBLOCK_NO_SPACE (-1)
#define WRITE_UNKNOWN_ERROR (-2)
ssize_t nonblock_writen_with_terminator(int fd, const void *buf, ssize_t n);
ssize_t nonblock_writen_without_terminator(int fd, const void *buf, ssize_t n);

// Epoll Tool
int init_epoll(CleanTaskArray *clean_tasks);
void add_epoll_event(int epoll_fd, void *event_data, int fd,
                     CleanTaskArray *clean_tasks);

// Command Tool
typedef struct
{
    char *str;
    int len;
} Command;
Command *Command_init(char *str, ssize_t len);
// Vector<char*>
Vector *Command_tokenization(Command *cmd);
void command_free(Command *cmd);
// Vector<Command*>
Vector *padding_buffer_tokenization(Client *client, const char *buffer,
                                    ssize_t len);

// message tool
#define ClientMessage_MIN LOGIN
#define ClientMessage_MAX DISCONNECT
typedef enum
{
    LOGIN = 0,
    DISCONNECT = 1
} ClientMessage;
extern const char *ClientMessage_str[];

#define ServerMessage_SHIFT (-3)
typedef enum
{
    INTERNAL_ERROR = 0,
    VALUE_ERROR = 1,
    RPC_FAILED = 2,
    SUCCESS = 3,
    REJECT = 4,
    NOT_LOGGED_IN = 5
} ServerMessage;
extern const char *ServerMessage_str[];

// Utility functions
int my_atoi(const char *str);
void error_exit(const char *message, CleanTaskArray *clean_tasks);
void set_nonblocking(int fd, CleanTaskArray *clean_tasks);
void padding_buffer_append(Client *client, const char *data, ssize_t len);

#endif /* TOOL_H */
