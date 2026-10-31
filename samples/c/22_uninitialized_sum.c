/* Sum without a starting value */
#include <stdio.h>

int main() {
    int sum;
    for (int i = 1; i <= 100; i++)
        sum += i;
    printf("1 + 2 + ... + 100 = %d\n", sum);
    return 0;
}
