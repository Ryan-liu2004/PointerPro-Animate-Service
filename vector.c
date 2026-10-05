#include <stdlib.h>

#include "vector.h"

Vector *Vector_init()
{
    Vector *vec = malloc(sizeof(Vector));
    if (!vec)
        return NULL;
    vec->data = malloc(VECTOR_INITIAL_CAPACITY * sizeof(void *));
    vec->size = 0;
    vec->capacity = VECTOR_INITIAL_CAPACITY;
    return vec;
}
Vector *Vector_init_n(ssize_t n)
{
    Vector *vec = malloc(sizeof(Vector));
    if (!vec)
        return NULL;
    vec->data = malloc(n * sizeof(void *));
    vec->size = 0;
    vec->capacity = n;
    return vec;
}

int Vector_push_back(Vector *vec, void *item)
{
    if (!vec)
        return -1;
    if (vec->size == vec->capacity)
    {
        ssize_t new_capacity = vec->capacity * 2;
        void **new_data = realloc(vec->data, new_capacity * sizeof(void *));
        if (!new_data)
            return -1;
        vec->data = new_data;
        vec->capacity = new_capacity;
    }
    vec->data[vec->size++] = item;
    return 0;
}

void Vector_free(Vector *vec)
{
    if (!vec)
        return;
    free(vec->data);
    free(vec);
}

void Vector_deep_free(Vector *vec, void (*free_func)(void *))
{
    if (!vec)
        return;
    if (free_func)
    {
        for (ssize_t i = 0; i < vec->size; i++)
            if (vec->data[i])
                free_func(vec->data[i]);
    }
    free(vec->data);
    free(vec);
}
