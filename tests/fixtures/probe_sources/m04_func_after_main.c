#include <stdio.h>
int main() {
    float r = area(2.0);
    printf("%f\n", r);
    return 0;
}
float area(float r) {
    return 3.14f * r * r;
}
