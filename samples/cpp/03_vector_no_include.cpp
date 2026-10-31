/* vector without #include <vector> */
#include <iostream>
using namespace std;

int main() {
    vector<int> marks = {80, 75, 90};
    int sum = 0;
    for (int m : marks) sum += m;
    cout << "Sum: " << sum << endl;
    return 0;
}
