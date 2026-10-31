#include <stdio.h>

int main() {
    double celsius;
    printf("Temperature in C: ");
    scanf("%f", &celsius);
    printf("In F: %.1f\n", celsius * 9 / 5 + 32);
    return 0;
}
