#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <sys/mman.h>
#include <unistd.h>

#define PAGE 4096
#define THRESH 256
#define NTAB 1048576

extern void *__libc_malloc(size_t);
extern void *__libc_calloc(size_t, size_t);
extern void *__libc_realloc(void *, size_t);
extern void __libc_free(void *);
extern size_t malloc_usable_size(void *);

static void *(*real_malloc)(size_t) = NULL;
static void *(*real_calloc)(size_t, size_t) = NULL;
static void *(*real_realloc)(void *, size_t) = NULL;
static void (*real_free)(void *) = NULL;
static int guard_above = 0;
static size_t thresh = 256;

struct ent { void *ret; size_t size; void *base; size_t total; };
static struct ent *tab = NULL;
static volatile long ntab = 0;

static void init_syms(void) {
    if (real_malloc) return;
    /* 用 glibc 内部符号，避免 dlsym 递归进入 malloc */
    real_malloc = __libc_malloc;
    real_calloc = __libc_calloc;
    real_realloc = __libc_realloc;
    real_free = __libc_free;
    const char *t = getenv("GUARD_THRESH");
    if (t) thresh = strtoul(t, NULL, 0);
    const char *e = getenv("GUARD_ABOVE");
    guard_above = (e && e[0] == '1') ? 1 : 0;
    if (!tab) tab = __libc_malloc(NTAB * sizeof(struct ent));
}

static void *g_alloc(size_t size) {
    size_t dp = (size + PAGE - 1) / PAGE;
    size_t total = (dp + 2) * PAGE;
    char *base = mmap(NULL, total, PROT_READ | PROT_WRITE,
                      MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (base == MAP_FAILED) return real_malloc(size);
    mprotect(base, PAGE, PROT_NONE);
    mprotect(base + PAGE + dp * PAGE, PAGE, PROT_NONE);
    char *ret;
    if (guard_above) {
        ret = (char *)(((uintptr_t)(base + PAGE) + 0xF) & ~(uintptr_t)0xF);
    } else {
        ret = base + PAGE + (dp * PAGE - size);
        ret = (char *)((uintptr_t)ret & ~(uintptr_t)0xF);  /* 16 字节对齐 */
        if (ret < base + PAGE) ret = base + PAGE;
    }
    long i = __sync_fetch_and_add(&ntab, 1);
    if (tab && i < NTAB) { tab[i].ret = ret; tab[i].size = size; tab[i].base = base; tab[i].total = total; }
    return ret;
}

void *malloc(size_t size) {
    init_syms();
    if (!real_malloc || size < thresh) return real_malloc(size);
    return g_alloc(size);
}

void *calloc(size_t n, size_t sz) {
    init_syms();
    size_t size;
    if (__builtin_mul_overflow(n, sz, &size)) size = (size_t)-1;
    if (!real_calloc || size < thresh) return real_calloc(n, sz);
    void *p = g_alloc(size);
    if (p) memset(p, 0, size);
    return p;
}

void free(void *p) {
    init_syms();
    if (!real_free) return;
    if (p && tab) {
        for (long i = ntab - 1; i >= 0; i--) {
            if (tab[i].ret == p) { munmap(tab[i].base, tab[i].total); tab[i].ret = NULL; return; }
        }
    }
    real_free(p);
}

extern size_t malloc_usable_size(void *);

void *realloc(void *p, size_t size) {
    init_syms();
    if (!p) return malloc(size);
    /* 查找 p 是否是我们 guard 分配的 */
    size_t old = 0;
    int is_guard = 0;
    if (tab) {
        for (long i = ntab - 1; i >= 0; i--) {
            if (tab[i].ret == p) { old = tab[i].size; is_guard = 1; break; }
        }
    }
    if (!is_guard) old = malloc_usable_size(p);
    void *np = (size < thresh) ? real_malloc(size) : g_alloc(size);
    if (np) memcpy(np, p, old < size ? old : size);
    free(p);
    return np;
}
/* ---- aligned 分配钩子：openjpeg 的 t1/tilec/decoded_data 全走这里 ---- */
static void *g_alloc_align(size_t size, size_t align) {
    if (align <= 16) return g_alloc(size);   /* g_alloc 已 16 对齐且尾部贴保护页 */
    /* align > 16：退化为“多分配 + 手动对齐 + 泄漏”，只用于探测 */
    char *raw = (char *) real_malloc(size + align + 16);
    if (!raw) return NULL;
    char *ret = (char *)(((uintptr_t) raw + align - 1) & ~(uintptr_t)(align - 1));
    long i = __sync_fetch_and_add(&ntab, 1);
    if (tab && i < NTAB) { tab[i].ret = ret; tab[i].size = size; tab[i].base = NULL; tab[i].total = 0; }
    return ret;
}

void *memalign(size_t align, size_t size) {
    init_syms();
    if (!real_malloc) return NULL;
    if (size < thresh) {
        char *raw = (char *) real_malloc(size + align + 16);
        if (!raw) return NULL;
        return (char *)(((uintptr_t) raw + align - 1) & ~(uintptr_t)(align - 1));
    }
    return g_alloc_align(size, align);
}

void *aligned_alloc(size_t align, size_t size) { return memalign(align, size); }

int posix_memalign(void **memptr, size_t align, size_t size) {
    void *p = memalign(align, size);
    if (!p) return 12;
    *memptr = p;
    return 0;
}
