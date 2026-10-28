// Single-threaded stand-in for the pthread calls of the browser engines, force-included (-include)
// in WASI builds.
// See wasi_pthread_shim.c for how the engine thread runs inline.
#ifndef WASI_PTHREAD_SHIM_H
#define WASI_PTHREAD_SHIM_H

#include <pthread.h>

#ifdef __cplusplus
extern "C" {
#endif
int shim_pthread_create(pthread_t *t, const pthread_attr_t *a, void *(*fn)(void *), void *arg);
int shim_pthread_join(pthread_t t, void **ret);
int shim_pthread_cond_wait(pthread_cond_t *c, pthread_mutex_t *m);
int shim_pthread_cond_signal(pthread_cond_t *c);
int shim_pthread_noop(void *p);
void shim_pthread_exit(void *ret);
#ifdef __cplusplus
}
#endif

#undef pthread_create
#define pthread_create shim_pthread_create
#undef pthread_exit
#define pthread_exit shim_pthread_exit
#undef pthread_detach
#define pthread_detach(t) shim_pthread_noop(0)
#undef pthread_join
#define pthread_join shim_pthread_join
#undef pthread_cond_wait
#define pthread_cond_wait shim_pthread_cond_wait
#undef pthread_cond_signal
#define pthread_cond_signal shim_pthread_cond_signal
#undef pthread_cond_broadcast
#define pthread_cond_broadcast shim_pthread_cond_signal
#undef pthread_mutex_lock
#define pthread_mutex_lock(m) shim_pthread_noop(m)
#undef pthread_mutex_unlock
#define pthread_mutex_unlock(m) shim_pthread_noop(m)
#undef pthread_mutex_init
#define pthread_mutex_init(m, a) shim_pthread_noop(m)
#undef pthread_cond_init
#define pthread_cond_init(c, a) shim_pthread_noop(c)

#endif
