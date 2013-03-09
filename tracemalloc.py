from __future__ import with_statement
import datetime
import os
import sys
pickle = None

from _tracemalloc import *
from _tracemalloc import __version__

if sys.version_info >= (3,):
    def _iteritems(obj):
        return obj.items()
else:
    def _iteritems(obj):
        return obj.iteritems()

def _sort_by_size(item):
    trace = item[2]
    return (trace.size, trace.count)

def _sort_by_size_diff(item):
    trace = item[2]
    return (trace.size_diff, trace.size, trace.count_diff, trace.count)

def _get_timestamp():
    return str(datetime.datetime.now()).split(".")[0]

def __format_size(size, sign=False):
    kb = size // 1024
    if kb:
        if sign:
            return "%+i KiB" % kb
        else:
            return "%i KiB" % kb
    else:
        if sign:
            return "%+i B" % size
        else:
            return "%i B" % size

_FORMAT_YELLOW = '\x1b[1;33m%s\x1b[0m'
_FORMAT_BOLD = '\x1b[1m%s\x1b[0m'
_FORMAT_CYAN = '\x1b[36m%s\x1b[0m'

def _format_size(size, color):
    text = __format_size(size)
    if color:
        text = _FORMAT_YELLOW % text
    return text

def _format_size_diff(size, diff, color):
    text = __format_size(size)
    if diff is not None:
        if color:
            text = _FORMAT_BOLD % text
        textdiff = __format_size(diff, sign=True)
        if color:
            textdiff = _FORMAT_YELLOW % textdiff
        text += " (%s)" % textdiff
    else:
        if color:
            text = _FORMAT_YELLOW % text
    return text

def get_process_memory():
    if get_process_memory.psutil_process is None:
        try:
            import psutil
        except ImportError:
            get_process_memory.psutil_process = False
        else:
            pid = os.getpid()
            get_process_memory.psutil_process = psutil.Process(pid)

    if get_process_memory.psutil_process != False:
        meminfo = get_process_memory.psutil_process.get_memory_info()
        return meminfo.rss

    if get_process_memory.support_proc == False:
        return

    try:
        fp = open("/proc/self/status")
    except IOError:
        get_process_memory.support_proc = False
        return None

    get_process_memory.support_proc = True
    with fp:
        for line in fp:
            if not(line.startswith("VmRSS:") and line.endswith(" kB\n")):
                continue
            value = line[6:-4].strip()
            value = int(value) * 1024
            return value

    # VmRss not found in /proc/self/status
    get_process_memory.support_proc = False
    return None
get_process_memory.support_proc = None
get_process_memory.psutil_process = None

class _TopTrace:
    __slots__ = ('size', 'size_diff', 'count', 'count_diff')

    def __init__(self, size=0, size_diff=0, count=0, count_diff=0):
        self.size = size
        self.size_diff = size_diff
        self.count = count
        self.count_diff = count_diff

    def add(self, trace):
        self.size += trace.size
        self.size_diff += trace.size_diff
        self.count += trace.count
        self.count_diff += trace.count_diff

    def use_snapshot(self, previous):
        if previous is not None:
            self.size_diff = self.size - previous.size
            self.count_diff = self.count - previous.count
        else:
            self.size_diff = self.size
            self.count_diff = self.count

    def format(self, display_top, show_diff):
        if not display_top.show_count and not display_top.show_average:
            if show_diff:
                return _format_size_diff(self.size, self.size_diff, display_top.color)
            else:
                return _format_size(self.size, display_top.color)

        parts = []
        if (display_top.show_size
        and (self.size or self.size_diff or not display_top.show_count)):
            if show_diff:
                text = _format_size_diff(self.size, self.size_diff, display_top.color)
            else:
                text = _format_size(self.size, display_top.color)
            parts.append("size=%s" % text)
        if display_top.show_count and (self.count or self.count_diff):
            text = "count=%s" % self.count
            if self.count_diff is not None:
                text += " (%+i)" % self.count_diff
            parts.append(text)
        if (display_top.show_average
        and self.count > 1):
            parts.append('average=%s' % _format_size(self.size // self.count, False))
        return ', '.join(parts)


class _TopSnapshot:
    def __init__(self, top):
        self.name = top.name
        self.stats = top.snapshot_stats
        self.process_memory = top.process_memory


class _Top:
    __slots__ = (
        'name', 'raw_stats', 'real_process_memory',
        'top_stats', 'snapshot_stats', 'tracemalloc_size', 'process_memory')

    def __init__(self, name, raw_stats, real_process_memory):
        self.name = name
        self.raw_stats = raw_stats
        self.real_process_memory = real_process_memory

        self.top_stats = None
        self.snapshot_stats = None
        self.tracemalloc_size = None
        self.process_memory = None

    def compute(self, display_top, want_snapshot):
        if display_top._snapshot is not None:
            snapshot = display_top._snapshot.stats.copy()
        else:
            snapshot = None

        stats = []
        if want_snapshot:
            new_snapshot = {}
        else:
            new_snapshot = None
        tracemalloc_size = 0
        for filename, line_dict in _iteritems(self.raw_stats):
            if os.path.basename(filename) == "tracemalloc.py":
                tracemalloc_size += sum(
                    item[0]
                    for lineno, item in _iteritems(line_dict))
                # ignore allocations in this file
                continue
            if display_top.show_lineno:
                for lineno, item in _iteritems(line_dict):
                    key = (filename, lineno)

                    trace = _TopTrace(size=item[0], count=item[1])
                    if snapshot is not None:
                        previous = snapshot.pop(key, None)
                        trace.use_snapshot(previous)
                    if lineno is None:
                        lineno = "?"
                    stats.append((filename, lineno, trace))
                    if want_snapshot:
                        new_snapshot[key] = trace
            else:
                key = (filename, None)
                trace = _TopTrace()
                for lineno, item in _iteritems(line_dict):
                    trace.size += item[0]
                    trace.count += item[1]
                if snapshot is not None:
                    previous = snapshot.pop(key, None)
                    trace.use_snapshot(previous)
                stats.append((filename, None, trace))
                if want_snapshot:
                    new_snapshot[key] = trace

        if snapshot is not None:
            for key, trace in _iteritems(snapshot):
                if display_top.show_lineno:
                    filename, lineno = key
                else:
                    filename, lineno = key
                trace = _TopTrace(size_diff=-trace.size, count_diff=-trace.count)
                stats.append((filename, lineno, trace))

        self.top_stats = stats
        self.snapshot_stats = new_snapshot
        self.tracemalloc_size = tracemalloc_size
        if self.real_process_memory:
            size = self.real_process_memory - self.tracemalloc_size
            self.process_memory = _TopTrace(size)


class DisplayTop:
    def __init__(self, top_count, file=None):
        self.top_count = top_count
        self._snapshot = None
        self.show_lineno = False
        self.show_size = True
        self.show_count = True
        self.show_average = True
        self.filename_parts = 3
        if file is not None:
            self.stream = file
        else:
            self.stream = sys.stdout
        self.compare_with_previous = True
        self.color = self.stream.isatty()

    def cleanup_filename(self, filename):
        parts = filename.split(os.path.sep)
        if self.filename_parts < len(parts):
            parts = ['...'] + parts[-self.filename_parts:]
        return os.path.sep.join(parts)


    def _display(self, top):
        log = self.stream.write
        snapshot = self._snapshot
        has_snapshot = (snapshot is not None)

        stats = top.top_stats
        if has_snapshot:
            stats.sort(key=_sort_by_size_diff, reverse=True)
        else:
            stats.sort(key=_sort_by_size, reverse=True)

        count = min(self.top_count, len(stats))
        if self.show_lineno:
            text = "file and line"
        else:
            text = "file"
        text = "Top %s allocations per %s" % (count, text)
        if self.color:
            text = _FORMAT_CYAN % text
        if has_snapshot:
            text += ' (compared to %s)' % snapshot.name
        name = top.name
        if self.color:
            name = _FORMAT_BOLD % name
        log("%s: %s\n" % (name, text))

        other = _TopTrace()
        total = _TopTrace()
        for index, item in enumerate(stats):
            filename, lineno, trace = item
            if index < self.top_count:
                filename = self.cleanup_filename(filename)
                if lineno is not None:
                    filename = "%s:%s" % (filename, lineno)
                text = trace.format(self, has_snapshot)
                if self.color:
                    path, basename = os.path.split(filename)
                    if path:
                        path += os.path.sep
                    filename = _FORMAT_CYAN % path + basename
                log("#%s: %s: %s\n" % (1 + index, filename, text))
            else:
                other.add(trace)
            total.add(trace)

        nother = len(stats) - self.top_count
        if nother > 0:
            text = other.format(self, has_snapshot)
            log("%s more: %s\n" % (nother, text))

        text = total.format(self, has_snapshot)
        log("Total Python memory: %s\n" % text)

        if top.process_memory:
            if has_snapshot:
                top.process_memory.use_snapshot(snapshot.process_memory)
            text = top.process_memory.format(self, has_snapshot)
            ignore = (" (ignore tracemalloc: %s)"
                          % _format_size(top.tracemalloc_size, False))
            if self.color:
                ignore = _FORMAT_CYAN % ignore
            text += ignore
            log("Total process memory: %s\n" % text)
        else:
            text = ("Ignore tracemalloc: %s"
                    % _format_size(top.tracemalloc_size, False))
            if self.color:
                text = _FORMAT_CYAN % text
            log(text + "\n")

        log("\n")
        self.stream.flush()

    def _run(self, top):
        save_snapshot = self.compare_with_previous
        if self._snapshot is None:
            save_snapshot = True

        top.compute(self, save_snapshot)
        self._display(top)
        if save_snapshot:
            self._snapshot = _TopSnapshot(top)

    def display(self):
        name = _get_timestamp()
        raw_stats = get_stats()
        process_memory = get_process_memory()
        top = _Top(name, raw_stats, process_memory)
        self._run(top)

    def start(self, delay):
        start_timer(int(delay), self.display)

    def stop(self):
        stop_timer()


def _lazy_import_pickle():
    # lazy loader for the pickle module
    global pickle
    if pickle is None:
        try:
            import cPickle as pickle
        except ImportError:
            import pickle
    return pickle


class Snapshot:
    FORMAT_VERSION = 1

    def __init__(self, stats, timestamp, pid, process_memory):
        self.stats = stats
        self.timestamp = timestamp
        self.pid = pid
        self.process_memory = process_memory

    @classmethod
    def create(cls):
        timestamp = _get_timestamp()
        stats = get_stats()
        pid = os.getpid()
        process_memory = get_process_memory()
        return cls(stats, timestamp, pid, process_memory)

    @classmethod
    def load(cls, filename):
        pickle = _lazy_import_pickle()
        try:
            with open(filename, "rb") as fp:
                data = pickle.load(fp)
        except Exception:
            err = sys.exc_info()[1]
            print("ERROR: Failed to load %s: [%s] %s" % (filename, type(err).__name__, err))
            sys.exit(1)

        try:
            if data['format_version'] != cls.FORMAT_VERSION:
                raise TypeError("unknown format version")

            stats = data['stats']
            timestamp = data['timestamp']
            pid = data['pid']
            process_memory = data.get('process_memory')
        except KeyError:
            raise TypeError("invalid file format")

        return cls(stats, timestamp, pid, process_memory)

    def write(self, filename):
        pickle = _lazy_import_pickle()
        data = {
            'format_version': self.FORMAT_VERSION,
            'timestamp': self.timestamp,
            'stats': self.stats,
            'pid': self.pid,
            'process_memory': self.process_memory,
        }

        with open(filename, "wb") as fp:
            pickle.dump(data, fp, pickle.HIGHEST_PROTOCOL)

    def filter_filenames(self, patterns, include):
        import fnmatch
        new_stats = {}
        for filename, file_stats in _iteritems(self.stats):
            if include:
                ignore = all(
                    not fnmatch.fnmatch(filename, pattern)
                    for pattern in patterns)
            else:
                ignore = any(
                    fnmatch.fnmatch(filename, pattern)
                    for pattern in patterns)
            if ignore:
                continue
            new_stats[filename] = file_stats
        self.stats = new_stats

    def display(self, display_top, show_pid=False):
        name = self.timestamp
        if show_pid:
            name += ' [pid %s]' % self.pid
        top = _Top(name, self.stats, self.process_memory)
        display_top._run(top)


class TakeSnapshot:
    def __init__(self):
        self.filename_template = "tracemalloc-$counter.pickle"
        self.counter = 1

    def take_snapshot(self):
        snapshot = Snapshot.create()

        filename = self.filename_template
        filename = filename.replace("$pid", str(snapshot.pid))
        timestamp = snapshot.timestamp.replace(" ", "-")
        filename = filename.replace("$timestamp", timestamp)
        filename = filename.replace("$counter", "%04i" % self.counter)

        snapshot.write(filename)
        self.counter += 1
        return snapshot, filename

    def _task(self):
        snapshot, filename = self.take_snapshot()
        sys.stderr.write("%s: Write a snapshot of memory allocations into %s\n"
                         % (snapshot.timestamp, filename))

    def start(self, delay):
        start_timer(int(delay), self._task)

    def stop(self):
        stop_timer()


def main():
    from optparse import OptionParser

    print("tracemalloc %s" % __version__)
    print("")

    parser = OptionParser(usage="%prog trace1.pickle [trace2.pickle  trace3.pickle ...]")
    parser.add_option("-l", "--line-number",
        help="Display line number",
        action="store_true", default=False)
    parser.add_option("-n", "--number",
        help="Number of traces displayed per top (default: 10)",
        type="int", action="store", default=10)
    parser.add_option("--first",
        help="Compare with the first trace, instead of with the previous trace",
        action="store_true", default=False)
    parser.add_option("--include", metavar="MATCH",
        help="Only include filenames matching pattern MATCH, "
             "the option can be specified multiple times",
        action="append", type=str)
    parser.add_option("--exclude", metavar="MATCH",
        help="Exclude filenames matching pattern MATCH, "
             "the option can be specified multiple times",
        action="append", type=str)
    parser.add_option("-S", "--hide-size",
        help="Hide the size of allocations",
        action="store_true", default=False)
    parser.add_option("-C", "--hide-count",
        help="Hide the number of allocations",
        action="store_true", default=False)
    parser.add_option("-A", "--hide-average",
        help="Hide the average size of allocations",
        action="store_true", default=False)
    parser.add_option("-P", "--filename-parts",
        help="Number of displayed filename parts (default: 3)",
        type="int", action="store", default=3)
    parser.add_option("--color",
        help="Enable colors even if stdout is not a TTY",
        action="store_true", default=False)
    parser.add_option("--no-color",
        help="Disable colors",
        action="store_true", default=False)

    options, filenames = parser.parse_args()
    if not filenames:
        parser.print_usage()
        sys.exit(1)
    # remove duplicates
    filenames = list(set(filenames))

    snapshots = []
    for filename in filenames:
        snapshot = Snapshot.load(filename)
        if options.include:
            snapshot.filter_filenames(options.include, True)
        if options.exclude:
            snapshot.filter_filenames(options.exclude, False)
        snapshots.append(snapshot)
    snapshots.sort(key=lambda snapshot: snapshot.timestamp)

    pids = set(snapshot.pid for snapshot in snapshots)
    show_pid = (len(pids) > 1)
    if show_pid:
        pids = ', '.join(map(str, sorted(pids)))
        print("WARNING: Traces generated by different processes: %s" % pids)
        print("")

    top = DisplayTop(options.number)
    top.filename_parts = options.filename_parts
    top.show_average = not options.hide_average
    top.show_count = not options.hide_count
    top.show_lineno = options.line_number
    top.show_size = not options.hide_size
    top.compare_with_previous = not options.first
    if options.color:
        top.color = True
    elif options.no_color:
        top.color = False

    for snapshot in snapshots:
        snapshot.display(top, show_pid=show_pid)

    print("%s snapshots" % len(snapshots))


if __name__ == "__main__":
    if 0:
        import cProfile
        cProfile.run('main()', sort='tottime')
    else:
        main()

