#include <stdio.h>
struct Student {
    int roll;
    float marks;
}
int main() {
    struct Student s;
    s.roll = 1;
    printf("%d\n", s.roll);
    return 0;
}
