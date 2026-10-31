#include <iostream>
using namespace std;

class Shape {
public:
    display() {
        cout << "Shape" << endl;
    }
};

int main() {
    Shape s;
    s.display();
    return 0;
}
