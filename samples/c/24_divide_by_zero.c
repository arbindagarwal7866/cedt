/* Division by zero at run time (Run with input: 10 0) */
#include <stdio.h>

int main() {
    int total, people;
    printf("Total amount and number of people: ");
    scanf("%d %d", &total, &people);
    printf("Each pays %d\n", total / people);
    return 0;
}
