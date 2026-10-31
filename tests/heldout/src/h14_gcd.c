#include <stdio.h>

int gcd(int a, int b) {
    if (b == 0)
        return a;
    else if (a > 0)
        gcd(b, a % b);
}

int main() {
    printf("gcd = %d\n", gcd(48, 18));
    return 0;
}
