#include <stdlib.h>

#include "queue.h"

Queue *Queue_init()
{
    Queue *q = (Queue *)malloc(sizeof(Queue));
    if (!q)
        return NULL;
    q->head = NULL;
    q->tail = NULL;
    q->status = QUEUE_SUCCESS;
    return q;
}

void Queue_push(Queue *q, void *data)
{
    if (!q)
        return;
    if (!data)
    {
        q->status = QUEUE_ERROR;
        return;
    }
    queue_node *new_node = (queue_node *)malloc(sizeof(queue_node));
    if (!new_node)
    {
        q->status = QUEUE_ERROR;
        return;
    }
    new_node->data = data;
    new_node->next = NULL;
    if (q->tail)
        q->tail->next = new_node;
    q->tail = new_node;
    if (!q->head)
        q->head = new_node;
    q->status = QUEUE_SUCCESS;
}

void *Queue_pop(Queue *q)
{
    if (!q)
        return NULL;
    if (!q->head)
    {
        q->status = QUEUE_EMPTY;
        return NULL;
    }
    queue_node *temp = q->head;
    void *data = temp->data;
    q->head = q->head->next;
    if (!q->head)
        q->tail = NULL;
    free(temp);
    q->status = QUEUE_SUCCESS;
    return data;
}

void *Queue_delete(Queue *q, void *data)
{
    if (!q)
        return NULL;
    if (!q->head || !data)
    {
        q->status = QUEUE_NOT_FOUND;
        return NULL;
    }
    queue_node *current = q->head;
    queue_node *prev = NULL;
    while (current)
    {
        if (current->data == data)
        {
            if (prev)
                prev->next = current->next;
            else
                q->head = current->next;
            if (current == q->tail)
                q->tail = prev;
            void *deleted_data = current->data;
            free(current);
            q->status = QUEUE_SUCCESS;
            return deleted_data;
        }
        prev = current;
        current = current->next;
    }
    q->status = QUEUE_NOT_FOUND;
    return NULL;
}

void Queue_free(Queue *q)
{
    if (!q)
        return;
    queue_node *current = q->head;
    while (current)
    {
        queue_node *temp = current;
        current = current->next;
        free(temp->data);
        free(temp);
    }
    q->head = NULL;
    q->tail = NULL;
    q->status = QUEUE_SUCCESS;
    free(q);
}