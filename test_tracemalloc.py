import os
import sys
import time
import tracemalloc
import unittest

EMPTY_STRING_SIZE = sys.getsizeof(b'')

def get_source(lineno_delta):
    filename = __file__
    frame = sys._getframe(1)
    lineno = frame.f_lineno + lineno_delta
    return filename, lineno

def allocate_bytes(size):
    source = get_source(1)
    data = b'x' * (size - EMPTY_STRING_SIZE)
    return data, source

class TestTracemalloc(unittest.TestCase):
    def setUp(self):
        tracemalloc.enable()

    def tearDown(self):
        tracemalloc.disable()

    def test_get_trace(self):
        size = 12345
        obj, obj_source = allocate_bytes(size)
        trace = tracemalloc._get_object_trace(obj)
        self.assertEqual(trace, (size,) + obj_source)

    def test_get_process_memory(self):
        obj_size = 10 ** 7
        orig = tracemalloc.get_process_memory()
        if orig is None:
            self.skipTest("get_process_memory is not supported")
        obj, obj_source = allocate_bytes(obj_size)
        curr = tracemalloc.get_process_memory()
        self.assertGreaterEqual(curr - orig, obj_size)

    def test_get_stats(self):
        total = 0
        count = 0
        objs = []
        for index in range(5):
            size = 1234
            obj, source = allocate_bytes(size)
            objs.append(obj)
            total += size
            count += 1

            stats = tracemalloc._get_stats()
            filename, lineno = source
            self.assertEqual(stats[filename][lineno], (total, count))

    def test_timer(self):
        calls = []
        def func(*args, **kw):
            calls.append((args, kw))

        # timer enabled
        args = (1, 2, 3)
        kwargs = {'arg': 4}
        tracemalloc.start_timer(1, func, args, kwargs)
        time.sleep(1)
        obj, source = allocate_bytes(123)
        self.assertEqual(len(calls), 1)
        call = calls[0]
        self.assertEqual(call, (args, kwargs))

        # timer disabled
        tracemalloc.stop_timer()
        time.sleep(1)
        obj2, source2 = allocate_bytes(123)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
