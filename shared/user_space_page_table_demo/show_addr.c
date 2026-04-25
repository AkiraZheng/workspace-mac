/*
 * show_addr.c - 简单的用户态地址演示程序
 *
 * 该程序创建一个全局变量和一个堆分配，输出它们的地址
 * 用于演示如何获取用户态页表属性
 */

#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

int global_var = 42;  /* 全局变量 - 在数据段 */

int main(void)
{
    int local_var = 99;           /* 局部变量 - 在栈上 */
    int *heap_ptr;                /* 堆指针 */

    /* 分配堆内存 */
    heap_ptr = malloc(sizeof(int) * 16);
    if (heap_ptr == NULL) {
        fprintf(stderr, "malloc failed\n");
        return 1;
    }

    /* 初始化堆内存 */
    for (int i = 0; i < 16; i++) {
        heap_ptr[i] = i;
    }

    /* 输出地址信息 */
    printf("PID: %d\n", getpid());
    printf("\n=== 地址信息 ===\n");
    printf("全局变量:     addr = %p, value = %d\n", (void *)&global_var, global_var);
    printf("局部变量:     addr = %p, value = %d\n", (void *)&local_var, local_var);
    printf("堆内存:       addr = %p, first value = %d\n", (void *)heap_ptr, heap_ptr[0]);

    printf("\n=== 进程信息 ===\n");
    printf("Press Ctrl+C to exit.\n");
    printf("在另一个终端运行: sh demo.sh <pid>\n");

    /* 循环保持进程运行 */
    while (1) {
        sleep(1);
        global_var++;  /* 触发页面访问 */
    }

    free(heap_ptr);
    return 0;
}
