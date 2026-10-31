#include <iostream>
using namespace std;
class Box {
public:
    int w;
}
int main() {
    Box b;
    b.w = 3;
    cout << b.w;
    return 0;
}
