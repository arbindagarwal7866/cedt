#include <stdio.h>
struct P { int x; };
int main() {
    struct P a = {1}, b = {1};
    if (a == b) printf("same\n");
    return 0;
}
