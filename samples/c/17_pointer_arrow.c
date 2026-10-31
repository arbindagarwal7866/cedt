/* Using . instead of -> with a pointer */
#include <stdio.h>

struct Point {
    int x, y;
};

int main() {
    struct Point p = {3, 4};
    struct Point *ptr = &p;
    printf("x = %d, y = %d\n", ptr.x, ptr.y);
    return 0;
}
