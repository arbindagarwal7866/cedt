/* Comparing strings with == */
#include <stdio.h>

int main() {
    char password[20];
    printf("Password: ");
    scanf("%19s", password);
    if (password == "vit2026")
        printf("Welcome!\n");
    else
        printf("Wrong password\n");
    return 0;
}
