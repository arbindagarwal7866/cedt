/* Global variable that clashes with std::count */
#include <bits/stdc++.h>
using namespace std;

int count = 0;

int main() {
    for (int i = 0; i < 10; i++)
        count++;
    cout << count << endl;
    return 0;
}
