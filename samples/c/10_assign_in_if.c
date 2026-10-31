/* = instead of == in a condition */
#include <stdio.h>

int main() {
    int choice = 2;
    if (choice = 1)
        printf("You chose one\n");
    else
        printf("You chose something else\n");
    return 0;
}
