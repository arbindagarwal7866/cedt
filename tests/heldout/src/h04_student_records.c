#include <stdio.h>

struct Student {
    char name[30];
    int marks;
};

void print_student(struct Student *s) {
    printf("%s scored %d\n", s.name, s->marks);
}

int main() {
    struct Student st = {"Riya", 91};
    print_student(&st);
    return 0;
}
