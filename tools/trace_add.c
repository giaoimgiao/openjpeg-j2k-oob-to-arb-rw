#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>

typedef void (*opj_procedure)(void);
static int (*real_add)(void *, opj_procedure, void *);

int opj_procedure_list_add_procedure(void *list, opj_procedure proc, void *mgr)
{
    if (!real_add) {
        real_add = (int (*)(void *, opj_procedure, void *))
                   dlsym(RTLD_NEXT, "opj_procedure_list_add_procedure");
    }
    Dl_info di;
    if (proc && dladdr((void *)proc, &di) && di.dli_fbase) {
        unsigned long off = (unsigned long)proc - (unsigned long)di.dli_fbase;
        printf("[PROC] +0x%lx\n", off);
    } else if (proc) {
        printf("[PROC] ?\n");
    }
    fflush(stdout);
    if (!real_add) {
        return 1;
    }
    return real_add(list, proc, mgr);
}