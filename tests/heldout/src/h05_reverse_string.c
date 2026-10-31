#include <stdio.h>

int main() {
    char word[50] = "compiler";
    int len = strlen(word);
    for (int i = len - 1; i >= 0; i--)
        putchar(word[i]);
    putchar('\n');
    return 0;
}
