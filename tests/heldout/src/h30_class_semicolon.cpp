#include <iostream>
using namespace std;

class Point {
public:
    int x, y;
}

int main() {
    Point p;
    p.x = 1; p.y = 2;
    cout << p.x + p.y << endl;
    return 0;
}
