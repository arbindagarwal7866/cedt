#include <stdio.h>

int main() {
    char grade[3] = "A";
    switch (grade) {
        case 'A': printf("Excellent\n"); break;
        case 'B': printf("Good\n"); break;
        default:  printf("Keep going\n");
    }
    return 0;
}
