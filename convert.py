import binascii
import json
import zlib
from j1m.xpickle.jsonpickle import record

outp = open('data.json', 'w')
i = 0
for line in open('data.pickles'):
    zoid, p = line.strip().split('\t')
    p = binascii.a2b_hex(p[3:])
    c, j = record(p)
    c = json.loads(c)['name']
    if c == 'karl.content.models.adapters._CachedData':
        state = json.loads(j)
        text = zlib.decompress(state['data']['hex'].decode('hex'))
        try:
            text = text.decode(
                state.get('encoding', 'ascii')).replace('\x00', '')
        except UnicodeDecodeError:
            text = ''
        j = json.dumps(dict(text=text))

    j = j.replace('\\', '\\\\') # postgres issue
    outp.write('\t'.join((zoid, c, j)) + '\n')
    i += 1

outp.close()
