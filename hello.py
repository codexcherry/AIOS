def add_numbers(a, b):
    return a + b

result = add_numbers(5, 7)
print(result)

with open('hello.txt', 'w') as f:
    f.write("The sum of 5 and 7 is " + str(result))