/* Variable used outside its for loop (scope) */
#include <stdio.h>

int main() {
    int sum = 0;
    for (int i = 1; i <= 5; i++) {
        sum += i;
    }
    printf("Loop ended at i = %d, sum = %d\n", i, sum);
    return 0;
}
