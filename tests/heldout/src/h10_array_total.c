#include <stdio.h>

int main() {
    int prices[5] = {120, 45, 300, 80, 15};
    int total;
    for (int i = 0; i < 5; i++) {
        total += prices[i];
    }
    printf("Total = %d\n", total);
    return 0;
}
