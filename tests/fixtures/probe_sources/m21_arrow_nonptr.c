#include <stdio.h>
struct Point { int x, y; };
int main() {
    struct Point pt = {1, 2};
    printf("%d\n", pt->x);
    return 0;
}
