/* Missing ; after a struct definition */
#include <stdio.h>

struct Student {
    int roll;
    float cgpa;
}

int main() {
    struct Student s = {16, 8.5f};
    printf("Roll %d has CGPA %.1f\n", s.roll, s.cgpa);
    return 0;
}
