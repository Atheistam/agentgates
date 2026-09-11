import json

ds = json.load(open('data/distribution_surfaces.json'))
for v in ds['venues']:
    if v['refusal_phrased_as'] in ('denial_disguised_as_success', 'explicit_denial', 'not_a_refusal'):
        ev = (v['evidence'] or '').replace('\n', ' ')
        print('%-22s %-30s %-5s %r' % (v['refusal_phrased_as'], v['name'], v['http_status'], ev[:180]))
