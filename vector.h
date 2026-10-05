#ifndef VECTOR_H
#define VECTOR_H

#include <stdlib.h>
#include <unistd.h>

#define VECTOR_INITIAL_CAPACITY (2)
typedef struct
{
    void **data;
    ssize_t size;
    ssize_t capacity;
} Vector;
Vector *Vector_init();
Vector *Vector_init_n(ssize_t n);
int Vector_push_back(Vector *vec, void *item);
void Vector_free(Vector *vec);
void Vector_deep_free(Vector *vec, void (*free_func)(void *));

#endif /* VECTOR_H */