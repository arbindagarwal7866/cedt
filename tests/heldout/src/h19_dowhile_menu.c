#include <stdio.h>

int main() {
    int choice;
    do {
        printf("1. Play  2. Quit\n");
        scanf("%d", &choice);
    } while (choice != 2)
    printf("Bye\n");
    return 0;
}
