#include <stdio.h>
int main() {
    char a[20];
    strcpy(a, "hi");
    printf("%d\n", (int)strlen(a));
    return 0;
}
