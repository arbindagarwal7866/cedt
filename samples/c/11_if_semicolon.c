/* Semicolon right after if (...) */
#include <stdio.h>

int main() {
    int temperature = 25;
    if (temperature > 30);
    {
        printf("It is hot today\n");
    }
    return 0;
}
