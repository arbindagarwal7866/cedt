#include <stdio.h>

int main() {
    int marks[4] = {78, 85, 91, 66};
    int sum = 0;
    for (int i = 0; i < 4; i++)
        sum += marks[i];
    float avg = sum / 4;
    printf("Average = %.2f\n", avg);
    return 0;
}
