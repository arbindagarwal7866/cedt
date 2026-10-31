/* scanf without & (tick "Run" and type 21) */
#include <stdio.h>

int main() {
    int age;
    printf("Enter your age: ");
    scanf("%d", age);
    printf("Next year you will be %d\n", age + 1);
    return 0;
}
