def fibonacci(n):
    if n <= 0:
        return 0
    elif n == 1:
        return 1
    else:
        return fibonacci(n-1) + fibonacci(n-2)

with open('test.py', 'w') as f:
    f.write("def fibonacci(n):\n")
    f.write("    if n <= 0:\n")
    f.write("        return 0\n")
    f.write("    elif n == 1:\n")
    f.write("        return 1\n")
    f.write("    else:\n")
    f.write("        return fibonacci(n-1) + fibonacci(n-2)\n")