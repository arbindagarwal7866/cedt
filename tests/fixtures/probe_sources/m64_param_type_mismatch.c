#include <stdio.h>
void show(int *p) { printf("%d\n", *p); }
int main() {
    int x = 5;
    show(x);
    return 0;
}
