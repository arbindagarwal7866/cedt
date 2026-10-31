/* Missing #include <string.h> */
#include <stdio.h>

int main() {
    char name[30];
    strcpy(name, "Compiler Design");
    printf("%s has %d letters\n", name, (int)strlen(name));
    return 0;
}
