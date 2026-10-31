/* Extra } closes main too early */
#include <stdio.h>

int main() {
    int a = 10, b = 20;
    if (a > b) {
        printf("a is bigger\n");
    }
    }
    printf("done\n");
    return 0;
}
