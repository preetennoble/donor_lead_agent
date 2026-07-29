def calculator(data: int, data2: int, operator):
    # substraction = "-"
    # addition = "+"
    # multiplication = "*"
    # division = "/"

    if operator == "+":
        print(data + data2) 
    elif operator == "-":
        print(data - data2)
    elif operator == "*":
        print(data * data2)
    elif operator == "/":
        print (data/ data2)

    else: 
        return "invalid operator"


print(calculator(1,2, "+"))