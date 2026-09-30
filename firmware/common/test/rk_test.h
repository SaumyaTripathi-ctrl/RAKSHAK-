/* Minimal test harness for the host tests. */
#ifndef RK_TEST_H
#define RK_TEST_H

#include <math.h>
#include <stdio.h>
#include <string.h>

static int rk_failures = 0;
static int rk_checks = 0;

#define CHECK(cond)                                                                     \
    do {                                                                                \
        rk_checks++;                                                                    \
        if (!(cond)) {                                                                  \
            rk_failures++;                                                              \
            printf("  FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);                    \
        }                                                                               \
    } while (0)

#define CHECK_EQ(a, b) CHECK((long long)(a) == (long long)(b))
#define CHECK_NEAR(a, b, eps) CHECK(fabs((double)(a) - (double)(b)) <= (eps))
#define RUN(fn)                     \
    do {                            \
        printf("- %s\n", #fn);      \
        fn();                       \
    } while (0)

#define RK_TEST_MAIN_END(name)                                                      \
    do {                                                                            \
        if (rk_failures) {                                                          \
            printf("%s FAILED: %d of %d checks\n", name, rk_failures, rk_checks);   \
            return 1;                                                               \
        }                                                                           \
        printf("%s OK (%d checks)\n", name, rk_checks);                             \
        return 0;                                                                   \
    } while (0)

#endif
