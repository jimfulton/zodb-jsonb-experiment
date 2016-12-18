import binascii
import json
import re
import sys
import time
import zlib
from j1m.xpickle.jsonpickle import record

unicode_surrogates = re.compile(r'\\ud[89a-f][0-9a-f]{2,2}', flags=re.I)

def main():
    inp, outp = sys.argv[1:]
    with open(inp) as inf:
        with open(outp, 'w') as outf:
            write = outf.write
            i = 0
            start = time.time()
            for line in inf:
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

                # Remove unicode surrogate strings, as postgres utf-8
                # will reject them.
                j = unicode_surrogates.sub(' ', j)

                # double \s because we're going to feed the data to psql stdin:
                j = j.replace('\\', '\\\\')

                write('\t'.join((zoid, c, j)) + '\n')
                i += 1

            print((time.time()-start)/i)

if __name__ == '__main__':
    main()
