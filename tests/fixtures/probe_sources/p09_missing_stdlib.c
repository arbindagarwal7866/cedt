#include <stdio.h>
int main() {
    int *p = malloc(10 * sizeof(int));
    p[0] = 1;
    free(p);
    exit(0);
}
