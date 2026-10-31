#include <iostream>
using namespace std;

class Account {
    double balance;
public:
    Account() { balance = 0; }
    void show() { cout << balance << endl; }
};

int main() {
    Account a;
    a.balance = 500;
    a.show();
    return 0;
}
