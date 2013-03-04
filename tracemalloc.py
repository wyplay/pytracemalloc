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

def _format_size(size, diff=None):
    text = __format_size(size)
    if diff is not None:
        text += " (%s)" % __format_size(diff, sign=True)
    return text

class _TopTrace:
    __slots__ = ('size', 'size_diff', 'count', 'count_diff')

    def __init__(self, size=0, size_diff=None, count=0, count_diff=None):
        self.size = size
        self.size_diff = size_diff
        self.count = count
        self.count_diff = count_diff

    def add(self, trace):
        self.size += trace.size
        if trace.size_diff is not None:
            if self.size_diff is not None:
                self.size_diff += trace.size_diff
            else:
                self.size_diff = trace.size_diff

        self.count += trace.count
        if trace.count_diff is not None:
            if self.count_diff is not None:
                self.count_diff += trace.count_diff
            else:
                self.count_diff = trace.count_diff

    def use_snapshot(self, previous):
        if previous is not None:
            self.size_diff = self.size - previous.size
            self.count_diff = self.count - previous.count
        else:
            self.size_diff = self.size
            self.count_diff = self.count

    def format(self, top):
        if not top.show_count and not top.show_average:
            return _format_size(self.size, self.size_diff)

        parts = []
        if top.show_size and (self.size or self.size_diff or not top.show_count):
            parts.append("size=%s" % _format_size(self.size, self.size_diff))
        if top.show_count:
            text = "count=%s" % self.count
            if self.count_diff is not None:
                text += " (%+i)" % self.count_diff
            parts.append(text)
        if top.show_average and self.count > 1:
            parts.append('average=%s' % _format_size(self.size // self.count))
        return ', '.join(parts)


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

    def cleanup_filename(self, filename):
        parts = filename.split(os.path.sep)
        if self.filename_parts < len(parts):
            parts = ['...'] + parts[-self.filename_parts:]
        return os.path.sep.join(parts)

    def _compute_stats(self, raw_stats, want_snapshot=False):
        if self._snapshot is not None:
            snapshot = self._snapshot.copy()
        else:
            snapshot = None

        stats = []
        if want_snapshot:
            new_snapshot = {}
        else:
            new_snapshot = None
        for filename, line_dict in _iteritems(raw_stats):
            if os.path.basename(filename) == "tracemalloc.py":
                # ignore allocations in this file
                continue
            if self.show_lineno:
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
                if self.show_lineno:
                    filename, lineno = key
                else:
                    filename, lineno = key
                trace = _TopTrace(size_diff=-trace.size, count_diff=-trace.count)
                stats.append((filename, lineno, trace))

        return stats, new_snapshot

    def _display_stats(self, stats, name):
        log = self.stream.write

        if self._snapshot is not None:
            stats.sort(key=_sort_by_size_diff, reverse=True)
        else:
            stats.sort(key=_sort_by_size, reverse=True)

        if name is None:
            name = _get_timestamp()
        count = min(self.top_count, len(stats))
        if self.show_lineno:
            text = "file and line"
        else:
            text = "file"
        log("%s: Top %s allocations per %s\n" % (name, count, text))

        other = _TopTrace()
        total = _TopTrace()
        for index, item in enumerate(stats):
            filename, lineno, trace = item
            if index < self.top_count:
                filename = self.cleanup_filename(filename)
                if lineno is not None:
                    filename = "%s:%s" % (filename, lineno)
                text = trace.format(self)
                log("#%s: %s: %s\n" % (1 + index, filename, text))
            else:
                other.add(trace)
            total.add(trace)

        nother = len(stats) - self.top_count
        if nother > 0:
            text = other.format(self)
            log("%s more: %s\n" % (nother, text))

        text = total.format(self)
        log("Total: %s\n" % text)

        log("\n")
        self.stream.flush()

    def _run(self, raw_stats=None, name=None):
        save_snapshot = self.compare_with_previous
        if self._snapshot is None:
            save_snapshot = True

        if raw_stats is None:
            raw_stats = get_stats()
        stats, snapshot = self._compute_stats(raw_stats, save_snapshot)
        self._display_stats(stats, name)
        if save_snapshot:
            self._snapshot = snapshot

    def display(self):
        self._run()

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

    def __init__(self, stats, timestamp, pid):
        self.stats = stats
        self.timestamp = timestamp
        self.pid = pid

    @classmethod
    def create(cls):
        timestamp = _get_timestamp()
        stats = get_stats()
        pid = os.getpid()
        return cls(stats, timestamp, pid)

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
        except KeyError:
            raise TypeError("invalid file format")

        return cls(stats, timestamp, pid)

    def write(self, filename):
        pickle = _lazy_import_pickle()
        data = {
            'format_version': self.FORMAT_VERSION,
            'timestamp': self.timestamp,
            'stats': self.stats,
            'pid': self.pid,
        }

        with open(filename, "wb") as fp:
            pickle.dump(data, fp, pickle.HIGHEST_PROTOCOL)

    def filter_filenames(self, pattern, include):
        import fnmatch
        new_stats = {}
        for filename, file_stats in _iteritems(self.stats):
            match = fnmatch.fnmatch(filename, pattern)
            if include:
                if not match:
                    continue
            else:
                if match:
                    continue
            new_stats[filename] = file_stats
        self.stats = new_stats

    def display(self, top, show_pid=False):
        name = self.timestamp
        if show_pid:
            name += ' [pid %s]' % self.pid
        top._run(self.stats, name)


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
        help="Only include filenames matching pattern MATCH",
        action="store", type=str)
    parser.add_option("--exclude", metavar="MATCH",
        help="Exclude filenames matching pattern MATCH",
        action="store", type=str)
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
    for snapshot in snapshots:
        snapshot.display(top, show_pid=show_pid)

    print("%s snapshots" % len(snapshots))


if __name__ == "__main__":
    main()

