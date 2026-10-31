/* Prototype without a function body (linker error) */
#include <stdio.h>

int factorial(int n);

int main() {
    printf("5! = %d\n", factorial(5));
    return 0;
}
