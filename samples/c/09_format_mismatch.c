/* Wrong printf / scanf format codes */
#include <stdio.h>

int main() {
    double cgpa;
    int credits = 23;
    printf("Enter CGPA: ");
    scanf("%f", &cgpa);
    printf("CGPA %d with %f credits\n", cgpa, credits);
    return 0;
}
