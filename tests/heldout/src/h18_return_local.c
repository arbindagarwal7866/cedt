#include <stdio.h>

char *make_greeting(void) {
    char text[32] = "Good morning";
    return text;
}

int main() {
    printf("%s\n", make_greeting());
    return 0;
}
