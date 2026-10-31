#include <stdio.h>

int main() {
    int n = 29, i, is_prime = 1;
    for (i = 2; i * i <= n; i++) {
        if (n % i = 0) {
            is_prime = 0;
            break;
        }
    }
    printf("%d is %s\n", n, is_prime ? "prime" : "not prime");
    return 0;
}
