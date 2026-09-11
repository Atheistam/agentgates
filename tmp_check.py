import re

h = open('web/findings/index.html').read()
print('unsubstituted placeholders:', re.findall(r'%\([a-z0-9_]+\)', h))
text = re.sub(r'<[^>]+>', ' ', h)
text = re.sub(r'&mdash;', '--', text)
text = re.sub(r'&[a-z]+;', ' ', text)
text = re.sub(r'\s+', ' ', text)

for probe in ('did not accept', 'said so', 'The honest no', '202', 'no account'):
    i = text.find(probe)
    print('---', probe, '->', text[max(0, i - 260):i + 420] if i >= 0 else 'NOT FOUND')
    print()
