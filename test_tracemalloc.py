import gc
import os
import sys
import time
import tracemalloc
import unittest
try:
    # Python 2
    try:
        from cStringIO import StringIO
    except ImportError:
        from StringIO import StringIO
except ImportError:
    # Python 3
    from io import StringIO

# Need a special patch to track Python free lists (ex: PyDict free list)
TRACK_FREE_LIST = False

EMPTY_STRING_SIZE = sys.getsizeof(b'')
THIS_FILE = os.path.basename(__file__)

class UncollectableObject:
    def __init__(self):
        self.ref = self

    def __del__(self):
        pass

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
        gc.set_debug(0)

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

    def _test_get_uncollectable(self, saveall):
        getter = tracemalloc._GetUncollectable()

        leak_source = get_source(1)
        leak = UncollectableObject()
        leak_id = id(leak)
        leak_dict_id = id(leak.__dict__)
        leak = None

        objects = getter.get_new_objects()
        if saveall:
            self.assertEqual(len(objects), 2)
        else:
            self.assertEqual(len(objects), 1)

        obj, obj_source = objects[0]
        self.assertEqual(id(obj), leak_id)
        self.assertGreater(obj_source[0], 1)
        self.assertEqual(obj_source[1:], leak_source)

        if saveall:
            obj, obj_source = objects[1]
            self.assertEqual(id(obj), leak_dict_id)

    def test_get_uncollectable(self):
        self._test_get_uncollectable(False)

    def test_get_uncollectable_saveall(self):
        gc.set_debug(gc.DEBUG_SAVEALL)
        self._test_get_uncollectable(True)

    def _test_display_uncollectable(self, saveall):
        stream = StringIO()
        display = tracemalloc.DisplayGarbage(file=stream)
        stream.truncate()

        leak_source = get_source(1)
        leak = UncollectableObject()
        leak_id = id(leak)
        leak_dict_id = id(leak.__dict__)
        leak = None

        display.display()
        output = stream.getvalue().splitlines()
        self.assertIn('UncollectableObject', output[0])
        self.assertIn(THIS_FILE, output[0])
        if saveall:
            self.assertEqual(len(output), 2)
            self.assertIn('{', output[1])
        else:
            self.assertEqual(len(output), 1)

    def test_display_uncollectable(self):
        self._test_display_uncollectable(False)

    def test_display_uncollectable_saveall(self):
        gc.set_debug(gc.DEBUG_SAVEALL)
        self._test_display_uncollectable(True)

    def _test_display_uncollectable_cumulative(self, saveall):
        gc.set_debug(gc.DEBUG_SAVEALL)
        stream = StringIO()
        display = tracemalloc.DisplayGarbage(file=stream)
        display.cumulative = True

        # Leak 1
        UncollectableObject()

        display.display()
        output = stream.getvalue().splitlines()
        self.assertIn('UncollectableObject', output[0])
        self.assertIn(THIS_FILE, output[0])
        if saveall:
            self.assertEqual(len(output), 2)
            self.assertIn('{', output[1])
        else:
            self.assertEqual(len(output), 1)

        # Leak 2
        UncollectableObject()

        stream.seek(0)
        stream.truncate()
        display.display()
        output = stream.getvalue().splitlines()
        self.assertIn('UncollectableObject', output[0])
        self.assertIn(THIS_FILE, output[0])
        if saveall:
            self.assertEqual(len(output), 4)
            self.assertIn('{', output[1])
            self.assertIn('UncollectableObject', output[2])
            self.assertIn(THIS_FILE, output[2])
            self.assertIn('{', output[3])
        else:
            self.assertEqual(len(output), 2)
            self.assertIn('UncollectableObject', output[1])
            self.assertIn(THIS_FILE, output[1])

    def test_display_uncollectable_cumulative(self):
        self._test_display_uncollectable_cumulative(False)

    def test_display_uncollectable_cumulative(self):
        gc.set_debug(gc.DEBUG_SAVEALL)
        self._test_display_uncollectable_cumulative(True)


if __name__ == "__main__":
    unittest.main()

