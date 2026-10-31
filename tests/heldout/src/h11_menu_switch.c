#include <stdio.h>

int main() {
    int choice = 2;
    switch (choice) {
        case 1:
            printf("Add\n");
            break;
        case 2:
            printf("Delete\n");
        case 3:
            printf("Exit\n");
            break;
    }
    return 0;
}
