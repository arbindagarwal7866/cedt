#include <stdio.h>

int main() {
    int n;
    printf("Enter n: ");
    scanf("%d", &n);
    printf("%d! = %ld\n", n, fact(n));
    return 0;
}

long fact(int n) {
    if (n <= 1)
        return 1;
    return n * fact(n - 1);
}
