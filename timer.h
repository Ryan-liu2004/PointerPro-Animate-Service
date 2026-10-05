#ifndef TIMER_H
#define TIMER_H

#include "queue.h"
#include "thread_pool.h"
#include <stdint.h>

#define DELAY_MS (1000)

typedef struct
{
    uint64_t expire_time;
    ClientData *data;
} TimerTask;

extern int timer_wake_pipe[2];

int Timer_init(int epoll_fd, CleanTaskArray *clean_tasks);
uint64_t get_current_ms();
int add_delay_delete_task(ClientData *data);
int get_epoll_timeout();
void Timer_drain_wake_pipe();
void process_expired_timers(void (*request_client_destroy)(ClientData *));
void Timer_free(void *arg);

#endif /* TIMER_H */