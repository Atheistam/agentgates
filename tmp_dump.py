import json

ds = json.load(open('data/distribution_surfaces.json'))
s = ds['summary']
t1 = json.load(open('data/robotspolicy_t1.json'))
t2 = json.load(open('data/robotspolicy_t2.json'))
print("asked t1/t2:", t1['summary']['asked'], t2['summary']['asked'])
print("domains_file t1:", t1['domains_file'])
print("domains_file t2:", t2['domains_file'])
print()
print("%-22s %-12s %-30s %-6s %s" % ("name", "verdict", "phrasing", "http", "gate"))
for v in ds['venues']:
    print("%-22s %-12s %-30s %-6s %s" % (
        v['name'][:22], v['verdict'], v['refusal_phrased_as'], v['http_status'], v['gate']))
print()
print("accepted:", [(v['name'], v['gate'], v['artifact_url']) for v in ds['venues']
                    if v['verdict'] == 'published'])
print()
for k in ('gated', 'unavailable', 'published', 'published_with_bare_reach',
          'published_only_because_a_key_was_held', 'inconclusive'):
    print(k, "=", s[k])
