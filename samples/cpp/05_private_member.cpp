/* Accessing a private member */
#include <iostream>
using namespace std;

class BankAccount {
    double balance = 0;
};

int main() {
    BankAccount acc;
    acc.balance = 5000;
    cout << "Balance set" << endl;
    return 0;
}
