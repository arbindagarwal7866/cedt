/* Missing semicolon - compiler blames the wrong line */
#include <stdio.h>

int main() {
    int marks[5] = {78, 92, 65, 88, 70};
    int total = 0
    for (int i = 0; i < 5; i++) {
        total += marks[i];
    }
    printf("Total marks: %d\n", total);
    return 0;
}
