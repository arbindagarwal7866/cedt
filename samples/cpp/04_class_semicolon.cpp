/* Missing ; after a class */
#include <iostream>
using namespace std;

class Rectangle {
public:
    int w, h;
    int area() { return w * h; }
}

int main() {
    Rectangle r;
    r.w = 3; r.h = 4;
    cout << r.area() << endl;
    return 0;
}
