#ifndef QUEUE_H
#define QUEUE_H

#define QUEUE_SUCCESS (0)
#define QUEUE_EMPTY (-1)
#define QUEUE_NOT_FOUND (-2)
#define QUEUE_ERROR (-3)

typedef struct queue_node_s
{
    void *data;
    struct queue_node_s *next;
} queue_node;

typedef struct
{
    int status;
    queue_node *head;
    queue_node *tail;
} Queue;

Queue *Queue_init();
void Queue_push(Queue *q, void *data);
void *Queue_pop(Queue *q);
void *Queue_delete(Queue *q, void *data);
void Queue_free(Queue *q);

#endif /* QUEUE_H */