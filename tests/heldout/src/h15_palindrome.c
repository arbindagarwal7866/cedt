#include <stdio.h>
#include <string.h>

int main() {
    char word[20] = "level", rev[20];
    int n = strlen(word);
    for (int i = 0; i < n; i++)
        rev[i] = word[n - 1 - i];
    rev[n] = '\0';
    if (word == rev)
        printf("Palindrome\n");
    else
        printf("Not a palindrome\n");
    return 0;
}
