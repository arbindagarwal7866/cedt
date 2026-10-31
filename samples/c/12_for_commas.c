/* Commas instead of semicolons in a for loop */
#include <stdio.h>

int main() {
    int i;
    for (i = 0, i < 5, i++) {
        printf("%d\n", i * i);
    }
    return 0;
}
