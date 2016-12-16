from pickle import Unpickler
from pickle import \
     PERSID, NONE, INT, BININT, BININT1, BININT2, LONG, FLOAT, \
     BINFLOAT, STRING, BINSTRING, SHORT_BINSTRING, UNICODE, \
     BINUNICODE, TUPLE, EMPTY_TUPLE, EMPTY_LIST, EMPTY_DICT, LIST, \
     DICT, INST, OBJ, GLOBAL, REDUCE, GET, BINGET, LONG_BINGET, PUT, \
     BINPUT, LONG_BINPUT, STOP, MARK, BUILD, SETITEMS, SETITEM, \
     BINPERSID, APPEND, APPENDS, NEWTRUE, NEWFALSE
from struct import unpack

def load_int(s):
    return unpack("<i", s)[0]

class XUnpickler(Unpickler):

    def __init__(self, *args, **kw):
        self.__put_objects = {}
        Unpickler.__init__(self, *args, **kw)

    def load(self):
        return self._x_load(Unpickler.load(self))

    # Some default noop
    _x_None = lambda self: None
    _x_String = _x_Unicode = _x_Bool = _x_Int = _x_Float = lambda self, v: v
    _x_Dictionary = _x_List = _x_Tuple = _x_Long = _x_String

    dispatch = {}
    dispatch.update(Unpickler.dispatch)

    def persistent_load(self, v):
        return self._x_Persistent(v)

    def load_persid(self):
        pid = self.readline()[:-1]
        self.append(self.persistent_load(String(pid)))
    dispatch[PERSID] = load_persid

    def load_none(self):
        self.append(self._x_None())
    dispatch[NONE] = load_none

    def load_false(self):
        self.append(self._x_Bool(False))
    dispatch[NEWFALSE] = load_false

    def load_true(self):
        self.append(self._x_Bool(True))
    dispatch[NEWTRUE] = load_true

    def load_int(self):
        s = self.readline()[:-1]
        i = int(s)
        self.append(self._x_Int(i))
    dispatch[INT] = load_int

    def load_binint(self):
        self.append(self._x_Int(load_int(self.read(4))))
    dispatch[BININT] = load_binint

    def load_binint1(self):
        self.append(self._x_Int(load_int(self.read(1) + '\000\000\000')))
    dispatch[BININT1] = load_binint1

    def load_binint2(self):
        self.append(self._x_Int(load_int(self.read(2) + '\000\000')))
    dispatch[BININT2] = load_binint2

    def load_long(self):
        self.append(self._x_Long(long(self.readline()[:-1], 0)))
    dispatch[LONG] = load_long

    def load_float(self):
        self.append(self._x_Float(float(self.readline()[:-1])))
    dispatch[FLOAT] = load_float

    def load_binfloat(self):
        self.append(self._x_Float(unpack('>d', self.read(8))[0]))
    dispatch[BINFLOAT] = load_binfloat

    def load_string(self):
        self.append(self._x_String(
            eval(self.readline()[:-1],
                 {'__builtins__': {}}))) # Let's be careful
    dispatch[STRING] = load_string

    def load_binstring(self):
        len = load_int(self.read(4))
        self.append(self._x_String(self.read(len)))
    dispatch[BINSTRING] = load_binstring

    def load_short_binstring(self):
        len = load_int(self.read(1) + '\000\000\000')
        self.append(self._x_String(self.read(len)))
    dispatch[SHORT_BINSTRING] = load_short_binstring

    def load_unicode(self):
        self.append(self._x_Unicode(
            unicode(self.readline()[:-1],'raw-unicode-escape')
            ))
    dispatch[UNICODE] = load_unicode

    def load_binunicode(self):
        len = load_int(self.read(4))
        self.append(self._x_Unicode(unicode(self.read(len),'utf-8')))
    dispatch[BINUNICODE] = load_binunicode

    def load_tuple(self):
        k = self.marker()
        self.stack[k:] = [self._x_Tuple(self.stack[k+1:])]
    dispatch[TUPLE] = load_tuple

    def load_empty_tuple(self):
        self.stack.append(self._x_Tuple(()))
    dispatch[EMPTY_TUPLE] = load_empty_tuple

    def load_empty_list(self):
        self.stack.append(self._x_List([]))
    dispatch[EMPTY_LIST] = load_empty_list

    def load_empty_dictionary(self):
        self.stack.append(self._x_Dictionary({}))
    dispatch[EMPTY_DICT] = load_empty_dictionary

    def load_list(self):
        k = self.marker()
        self.stack[k:] = [self._x_List(self.stack[k+1:])]
    dispatch[LIST] = load_list

    def load_dict(self):
        k = self.marker()
        d = {}
        items = self.stack[k+1:]
        for i in range(0, len(items), 2):
            key = items[i]
            value = items[i+1]
            d[key] = value
        self.stack[k:] = [self._x_Dictionary(d)]
    dispatch[DICT] = load_dict

    def load_inst(self):
        k = self.marker()
        args = tuple(self.stack[k+1:])
        del self.stack[k:]
        module = self.readline()[:-1]
        name = self.readline()[:-1]
        value = self._x_Instance(Global(module, name), args)
        self.append(value)
    dispatch[INST] = load_inst

    def load_obj(self):
        stack = self.stack
        k = self.marker()
        klass = stack[k + 1]
        del stack[k + 1]
        args = tuple(stack[k + 1:])
        del stack[k:]
        value = self._x_Instance(klass,args)
        self.append(value)
    dispatch[OBJ] = load_obj

    def load_global(self):
        module = self.readline()[:-1]
        name = self.readline()[:-1]
        self.append(self._x_Global(module, name))
    dispatch[GLOBAL] = load_global

    def load_reduce(self):
        stack = self.stack

        callable = stack[-2]
        arg_tup  = stack[-1]
        del stack[-2:]

        value = self._x_Instance(callable, arg_tup)
        self.append(value)
    dispatch[REDUCE] = load_reduce

    def __get(self, i):
        self.append(self._x_Get(i, self.__put_objects[i]))

    def __put(self, i):
        ob = self._x_Put(i, self.stack[-1])
        self.stack[-1] = ob
        self.__put_objects[i] = ob

    def load_get(self):
        i = self.readline()[:-1]
        self.__get(i)
    dispatch[GET] = load_get

    def load_binget(self):
        i = load_int(self.read(1) + '\000\000\000')
        self.__get(`i`)
    dispatch[BINGET] = load_binget

    def load_long_binget(self):
        i = load_int(self.read(4))
        self.__get(`i`)
    dispatch[LONG_BINGET] = load_long_binget

    def load_put(self):
        i = self.readline()[:-1]
        self.__put(i)
    dispatch[PUT] = load_put

    def load_binput(self):
        i = load_int(self.read(1) + '\000\000\000')
        self.__put(`i`)
    dispatch[BINPUT] = load_binput

    def load_long_binput(self):
        i = load_int(self.read(4))
        self.__put(`i`)
    dispatch[LONG_BINPUT] = load_long_binput
