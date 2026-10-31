/* Function used before it is declared */
#include <stdio.h>

int main() {
    float r = 2.5;
    printf("Area = %.2f\n", area(r));
    return 0;
}

float area(float radius) {
    return 3.14159f * radius * radius;
}
