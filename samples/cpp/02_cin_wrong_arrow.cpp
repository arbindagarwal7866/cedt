/* cin << instead of cin >> (a 120-line C++ error) */
#include <iostream>
using namespace std;

int main() {
    int age;
    cout << "Enter age: ";
    cin << age;
    cout << "You are " << age << endl;
    return 0;
}
