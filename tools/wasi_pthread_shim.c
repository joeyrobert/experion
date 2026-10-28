// Stash and WyldChess run their search on an engine thread that sleeps on a condition variable until the UCI
// thread signals it. Here pthread_create only records that thread function, and signalling the
// condition runs it inline: its first cond_wait returns so it can pick up the pending command, and
// the next one (it is idle again) longjmps back to the signaller. Mutexes are no-ops.
#include "wasi_pthread_shim.h"
#include <setjmp.h>
#include <stddef.h>

static void *(*thread_fn)(void *);
static void *thread_arg;
static int in_thread, waits;
static jmp_buf back;

static void run_thread(void)
{
	if (!thread_fn || in_thread)
		return;
	in_thread = 1;
	waits = 0;
	if (!setjmp(back))
	{
		thread_fn(thread_arg);
		thread_fn = NULL;
	}
	in_thread = 0;
}

int shim_pthread_create(pthread_t *t, const pthread_attr_t *a, void *(*fn)(void *), void *arg)
{
	(void)t; (void)a;
	if (thread_fn)
		return 11; // EAGAIN: only the engine thread is supported (Threads stays at 1)
	thread_fn = fn;
	thread_arg = arg;
	run_thread();
	return 0;
}

int shim_pthread_cond_wait(pthread_cond_t *c, pthread_mutex_t *m)
{
	(void)c; (void)m;
	if (in_thread)
	{
		if (waits++)
			longjmp(back, 1);
		return 0;
	}
	run_thread();
	return 0;
}

int shim_pthread_cond_signal(pthread_cond_t *c) { (void)c; run_thread(); return 0; }
int shim_pthread_join(pthread_t t, void **ret) { (void)t; if (ret) *ret = NULL; return 0; }
int shim_pthread_noop(void *p) { (void)p; return 0; }

void shim_pthread_exit(void *ret)
{
	(void)ret;
	thread_fn = NULL;
	longjmp(back, 1);
}
