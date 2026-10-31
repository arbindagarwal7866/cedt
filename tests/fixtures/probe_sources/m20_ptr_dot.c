#include <stdio.h>
struct Point { int x, y; };
int main() {
    struct Point pt = {1, 2};
    struct Point *p = &pt;
    printf("%d\n", p.x);
    return 0;
}
