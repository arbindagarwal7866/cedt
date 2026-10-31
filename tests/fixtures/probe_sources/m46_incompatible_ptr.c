#include <stdio.h>
int main() {
    float f = 2.5f;
    int *p;
    p = &f;
    printf("%d\n", *p);
    return 0;
}
