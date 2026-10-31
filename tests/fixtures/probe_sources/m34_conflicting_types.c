#include <stdio.h>
int square(int x);
float square(float x) {
    return x * x;
}
int main() {
    printf("%f\n", square(2.0f));
    return 0;
}
