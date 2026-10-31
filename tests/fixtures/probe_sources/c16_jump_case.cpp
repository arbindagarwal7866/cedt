#include <iostream>
int main() {
    int x = 1;
    switch (x) {
        case 1:
            int y = 5;
            std::cout << y;
            break;
        case 2:
            std::cout << "two";
            break;
    }
    return 0;
}
