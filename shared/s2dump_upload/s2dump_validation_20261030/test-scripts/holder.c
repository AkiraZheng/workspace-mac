/* uacce 队列 mmap 持有程序: 打开 /dev/hisi_zip-0 并 mmap 队列区域后长睡 */
#include <fcntl.h>
#include <sys/mman.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <string.h>
#include <errno.h>
int main(int argc, char **argv)
{
    const char *path = argc > 1 ? argv[1] : "/dev/hisi_zip-0";
    int fd = open(path, O_RDWR | O_CLOEXEC);
    if (fd < 0) { perror("open"); return 1; }
    printf("opened %s fd=%d\n", path, fd);
    /* 尝试 mmap 各区域索引 (uacce fops mmap 按 pgoff 区分 qfrt 区域) */
    for (unsigned long idx = 0; idx < 4; idx++) {
        void *p = mmap(NULL, 4096, PROT_READ | PROT_WRITE, MAP_SHARED,
                       fd, idx * 4096);
        if (p == MAP_FAILED) {
            printf("mmap idx=%lu: %s\n", idx, strerror(errno));
        } else {
            printf("mmap idx=%lu: OK %p\n", idx, p);
        }
    }
    /* 持有 */
    printf("holding...\n");
    fflush(stdout);
    sleep(86400);
    return 0;
}
