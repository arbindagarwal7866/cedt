/* Bugs the compiler does not report */
#include <stdio.h>

int main() {
    int marks[5] = {80, 75, 90, 60, 85};
    int sum = 0, n = 5;
    for (int i = 0; i <= 5; i++)
        sum += marks[i];
    float average = sum / n;
    int square = n^2;
    printf("Average %.2f, n squared %d\n", average, square);
    return 0;
}
