/* Function that does not always return */
#include <stdio.h>

int grade(int marks) {
    if (marks >= 90)
        return 'S';
    else if (marks >= 80)
        return 'A';
    else if (marks >= 50)
        return 'B';
}

int main() {
    printf("Grade: %c\n", grade(42));
    return 0;
}
