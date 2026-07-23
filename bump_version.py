import re
p = r'C:\Users\1\Desktop\crop-doctor-backend-deploy\app.py'
with open(p, encoding='utf-8') as f:
    c = f.read()
# 只精确替换 "version": "2.2.0" 的字符串,避免误伤其他 2.2.0
c2 = c.replace('"version": "2.2.0"', '"version": "2.2.1"')
# 兼容写
n = c.count('"version": "2.2.0"')
n2 = c2.count('"version": "2.2.1"')
print(f'replaced {n} -> {n2}')
with open(p, 'w', encoding='utf-8') as f:
    f.write(c2)
print('done')
