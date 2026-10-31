#include <stdio.h>
int *make(void) {
    int x = 5;
    return &x;
}
int main() {
    printf("%d\n", *make());
    return 0;
}
