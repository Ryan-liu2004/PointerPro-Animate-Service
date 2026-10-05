#ifndef _POSIX_C_SOURCE
#define _POSIX_C_SOURCE 200809L
#endif
#include <stdio.h>
#include <stdlib.h>
#include <sys/epoll.h>
#include <time.h>

#include "timer.h"

static Queue *timer_queue = NULL;
int timer_wake_pipe[2];

int Timer_init(int epoll_fd, CleanTaskArray *clean_tasks)
{
    timer_queue = Queue_init();
    if (!timer_queue)
    {
        perror("[Timer] Failed to initialize timer queue");
        return -1;
    }

    if (pipe(timer_wake_pipe) == -1)
    {
        perror("[Timer] Failed to create wake pipe");
        return -1;
    }

    set_nonblocking(timer_wake_pipe[0], clean_tasks);
    set_nonblocking(timer_wake_pipe[1], clean_tasks);

    CleanTask_add(clean_tasks, (void *)(intptr_t)timer_wake_pipe[0],
                  (CleanFunc)close_wrapper);
    CleanTask_add(clean_tasks, (void *)(intptr_t)timer_wake_pipe[1],
                  (CleanFunc)close_wrapper);

    add_epoll_event(epoll_fd, &timer_wake_pipe[0], timer_wake_pipe[0],
                    clean_tasks);
    return 0;
}

uint64_t get_current_ms()
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000 + (uint64_t)ts.tv_nsec / 1000000;
}

int add_delay_delete_task(ClientData *data)
{
    if (!data || !timer_queue)
        return 0;

    TimerTask *task = (TimerTask *)malloc(sizeof(TimerTask));
    if (!task)
    {
        perror("[Timer] malloc failed");
        return -1;
    }
    task->expire_time = get_current_ms() + DELAY_MS;
    task->data = data;

    pthread_mutex_lock(&timer_mutex);
    Queue_push(timer_queue, task);
    pthread_mutex_unlock(&timer_mutex);

    char dummy = 1;
    write(timer_wake_pipe[1], &dummy, 1);
    return 1;
}

int get_epoll_timeout()
{
    pthread_mutex_lock(&timer_mutex);
    if (!timer_queue || !timer_queue->head)
    {
        pthread_mutex_unlock(&timer_mutex);
        return -1;
    }

    uint64_t now = get_current_ms();
    TimerTask *first = (TimerTask *)timer_queue->head->data;
    int timeout;
    if (now >= first->expire_time)
        timeout = 0;
    else
        timeout = (int)(first->expire_time - now);
    pthread_mutex_unlock(&timer_mutex);
    return timeout;
}

void Timer_drain_wake_pipe()
{
    char dummy;
    while (read(timer_wake_pipe[0], &dummy, 1) > 0)
        ;
}

void process_expired_timers(void (*request_client_destroy)(ClientData *))
{
    if (!timer_queue)
        return;
    uint64_t now = get_current_ms();
    while (1)
    {
        pthread_mutex_lock(&timer_mutex);
        if (!timer_queue->head)
        {
            pthread_mutex_unlock(&timer_mutex);
            break;
        }

        TimerTask *first = (TimerTask *)timer_queue->head->data;
        if (now >= first->expire_time)
        {
            TimerTask *expired_task = (TimerTask *)Queue_pop(timer_queue);
            pthread_mutex_unlock(&timer_mutex);
            ClientData *data = expired_task->data;

            if (client_is_alive(data))
                request_client_destroy(data);
            free(expired_task);
        }
        else
        {
            pthread_mutex_unlock(&timer_mutex);
            break;
        }
    }
}

void Timer_free(void *arg)
{
    (void)arg;
    if (!timer_queue)
        return;
    Queue_free(timer_queue);
    timer_queue = NULL;
}
