#include <stdio.h>
struct Student { int age; char name[20]; };
int main() {
    struct Student s;
    s.agee = 20;
    printf("%d\n", s.age);
    return 0;
}
