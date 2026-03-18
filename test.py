import csv


import csv


time1 = []
time2 = []
p1 = []
p2 = []
c_len = []
with open(f"cycle.txt", "r") as f:
    for line in f.readlines():
        c_len.append(float(line))
c_len = c_len[::-1]


time1 = []
with open(f"timeline.txt", "r") as f:
    for line in f.readlines():
        time1.append(float(line))


t0 = time1[0]
for i in range(len(time1)):
    time1[i] -= t0

current_c = 0
t_start = 0
res1 = []
for i in range(len(time1)):
    if (time1[i] - t_start) < c_len[current_c]:
        res1.append(current_c+(time1[i] - t_start)/c_len[current_c])
    elif current_c < len(c_len)-1:
        t_start = time1[i]
        current_c += 1
        res1.append(current_c+(time1[i] - t_start)/c_len[current_c])



with open('циклограмма.csv', "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f, delimiter=" ")
    for i in range(len(res1)):
        row = []
        if i < len(res1):
            row.append(f"{time1[i]+t0}")# .replace('.', ','))
            row.append(f"{res1[i]}" )#.replace('.', ','))
        writer.writerow(row)