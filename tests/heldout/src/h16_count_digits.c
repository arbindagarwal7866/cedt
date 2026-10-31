#include <stdio.h>

int main() {
    int n = 90210, digits = 0;
    while (n > 0);
    {
        n = n / 10;
        digits++;
    }
    printf("Digits: %d\n", digits);
    return 0;
}
