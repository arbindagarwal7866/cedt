#include <stdio.h>
void greet(void) { printf("hi\n"); }
int main() {
    int r = greet();
    printf("%d\n", r);
    return 0;
}
