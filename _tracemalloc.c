#include <Python.h>
#include <glib.h>
#include "frameobject.h"
#include "pythread.h"

#define VERSION "0.8"

#if PY_MAJOR_VERSION >= 3
# define PYTHON3
#endif

#if defined(PYTHON3) || (PY_MAJOR_VERSION >= 2 && PY_MINOR_VERSION >= 7)
#  define PYINT_FROM_SSIZE_T PyLong_FromSize_t
#else
#  define PYINT_FROM_SSIZE_T PyInt_FromSize_t
#endif

#ifndef Py_TYPE
   /* Python 2.5 doesn't have this macro */
#  define Py_TYPE(obj) obj->ob_type
#endif

typedef enum {
    TRACE_MALLOC,
    TRACE_REALLOC_OLD,
    TRACE_REALLOC_NEW,
    TRACE_FREE
} trace_func_t;

typedef void* (*trace_malloc_t) (size_t);
typedef void* (*trace_realloc_t) (void*, size_t);
typedef void (*trace_free_t) (void*);

static struct {
    int enabled;
    int delay;
    time_t next_trigger;
    PyObject *callback;
    PyObject *args;
    PyObject *kwargs;
} trace_timer;

static struct {
    int enabled;
    int debug;

    trace_malloc_t mem_malloc;
    trace_realloc_t mem_realloc;
    trace_free_t mem_free;

    trace_malloc_t object_malloc;
    trace_realloc_t object_realloc;
    trace_free_t object_free;
} trace_config;

typedef struct {
    size_t size;
    const char *filename;
    int lineno;
} trace_alloc_t;

typedef struct {
    size_t size;
    size_t count;
} trace_file_stats_t;

/* filename (char*) => GHashTable,
 * the sub-hash table: lineno (int) => stats (trace_file_stats_t) */
static GHashTable *trace_files = NULL;

/* pointer (void*) => trace (trace_alloc_t*) */
static GHashTable *trace_allocs = NULL;

/* Forward declaration */
static char* trace_get_filename(int *lineno_p);

static void
trace_error(const char *format, ...)
{
    va_list ap;
    fprintf(stderr, "tracemalloc: ");
    va_start(ap, format);
    vfprintf(stderr, format, ap);
    va_end(ap);
    fprintf(stderr, "\n");
    fflush(stderr);
}

static trace_alloc_t*
trace_alloc_trace(void)
{
    return g_slice_alloc(sizeof(trace_alloc_t));
}

static void
trace_free_trace(trace_alloc_t* trace)
{
    g_slice_free1(sizeof(trace_alloc_t), trace);
}

static int
trace_timer_call(void *user_data)
{
    PyObject *result;

    result = PyEval_CallObjectWithKeywords(trace_timer.callback,
                                           trace_timer.args,
                                           trace_timer.kwargs);
    if (!result)
        return -1;
    Py_DECREF(result);
    return 0;
}

static void
trace_update_stats(int is_alloc, trace_alloc_t *trace)
{
    trace_file_stats_t *stats;
    int is_new_trace;
    GHashTable *line_hash;
    gpointer key;

    assert(trace->filename != NULL);

    line_hash = g_hash_table_lookup(trace_files, trace->filename);
    if (line_hash == NULL) {
        line_hash = g_hash_table_new_full(g_direct_hash,
                                          g_direct_equal,
                                          NULL,
                                          g_free);
        if (line_hash == NULL) {
            trace_error("failed to allocate a hash table for lines for a new filename");
            return;
        }
        g_hash_table_insert(trace_files, (gpointer)trace->filename, line_hash);
    }

    key = GINT_TO_POINTER(trace->lineno);
    stats = g_hash_table_lookup(line_hash, key);
    is_new_trace = (stats == NULL);
    if (is_new_trace) {
        stats = g_new0(trace_file_stats_t, 1);
        if (stats == NULL) {
            trace_error("failed to allocate a stats");
            return;
        }
    }

    if (is_alloc) {
        stats->size += trace->size;
        stats->count++;
    }
    else {
        stats->size -= trace->size;
        stats->count--;
    }

    if (is_new_trace) {
        g_hash_table_insert(line_hash, key, stats);
    }
    else if (stats->size == 0) {
        g_hash_table_remove(line_hash, key);
        if (g_hash_table_size(line_hash) == 0)
            g_hash_table_remove(trace_files, trace->filename);
    }
}

static void
trace_timer_check(void)
{
    if (!trace_timer.enabled)
        return;
    if (time(NULL) < trace_timer.next_trigger)
        return;

    Py_AddPendingCall(trace_timer_call, NULL);
    trace_timer.next_trigger = time(NULL) + trace_timer.delay;
}

static void
trace_log_alloc(void *ptr, trace_alloc_t *trace)
{
    trace_config.enabled = 0;
    trace->filename = trace_get_filename(&trace->lineno);
    trace_config.enabled = 1;

    if (trace->filename != NULL) {
        trace->filename = g_intern_string(trace->filename);
        if (trace->filename == NULL) {
            trace_error("failed to intern the filename");
            trace->filename = "???";
        }
    }
    else {
        trace->filename = "???";
    }

    g_hash_table_insert(trace_allocs, ptr, trace);

    trace_update_stats(1, trace);

    trace_timer_check();
}

static void
trace_log_dealloc(void *ptr, trace_alloc_t *trace)
{
    trace_update_stats(0, trace);

    g_hash_table_remove(trace_allocs, ptr);
    trace_free_trace(trace);

    trace_timer_check();
}

static void *
trace_malloc(trace_malloc_t func, size_t size)
{
    void *ptr;
    trace_alloc_t *trace;

    if (!trace_config.enabled)
        return func(size);

    ptr = func(size);
    if (ptr == NULL)
        return NULL;

    trace = trace_alloc_trace();
    if (trace != NULL) {
        trace->size = size;
        trace_log_alloc(ptr, trace);
    }
    return ptr;
}

static void *
trace_realloc(trace_realloc_t func, void *ptr1, size_t size)
{
    trace_alloc_t *trace1, *trace2;
    void *ptr2;

    if (!trace_config.enabled)
        return func(ptr1, size);

    if (ptr1 != NULL) {
        trace1 = g_hash_table_lookup(trace_allocs, ptr1);
        if (trace1 == NULL) {
            /* the pointer is not tracked */
            return func(ptr1, size);
        }
    }
    else
        trace1 = NULL;

    ptr2 = func(ptr1, size);
    if (ptr2 == NULL)
        return NULL;

    if (trace1 != NULL)
        trace_log_dealloc(ptr1, trace1);

    trace2 = trace_alloc_trace();
    if (trace2 != NULL) {
        trace2->size = size;
        trace_log_alloc(ptr2, trace2);
    }
    return ptr2;
}

static void
trace_free(trace_free_t func, void *ptr)
{
    trace_alloc_t *trace;

    if (!trace_config.enabled) {
        func(ptr);
        return;
    }

    if (ptr == NULL)
        return;

    func(ptr);

    trace = g_hash_table_lookup(trace_allocs, ptr);
    if (trace != NULL)
        trace_log_dealloc(ptr, trace);
}

#ifdef WITH_FREE_LIST
static void
trace_free_list_alloc(PyObject *op)
{
    void *ptr;
    PyTypeObject *type;
    size_t size;
    trace_alloc_t *trace;

    if (!trace_config.enabled)
        return;

    trace = trace_alloc_trace();
    if (trace == NULL)
        return;

    type = Py_TYPE(op);
    if (PyType_IS_GC(type))
        ptr = (void *)((char *)op - sizeof(PyGC_Head));
    else
        ptr = (void *)op;
    size = type->tp_basicsize;

    trace->size = size;
    trace_log_alloc(ptr, trace);
}

static void
trace_free_list_free(PyObject *op)
{
    trace_alloc_t *trace;
    void *ptr;

    if (!trace_config.enabled)
        return;

    ptr = (void *)op;
    trace = g_hash_table_lookup(trace_allocs, ptr);
    if (trace != NULL)
        trace_log_dealloc(ptr, trace);
}
#endif

static void *
trace_mem_malloc(size_t size)
{
    return trace_malloc(trace_config.mem_malloc, size);
}

static void *
trace_mem_realloc(void *ptr, size_t size)
{
    return trace_realloc(trace_config.mem_realloc, ptr, size);
}

static void
trace_mem_free(void *ptr)
{
    trace_free(trace_config.mem_free, ptr);
}

static void *
trace_object_malloc(size_t size)
{
    return trace_malloc(trace_config.object_malloc, size);
}

static void *
trace_object_realloc(void *ptr, size_t size)
{
    return trace_realloc(trace_config.object_realloc, ptr, size);
}

static void
trace_object_free(void *ptr)
{
    trace_free(trace_config.object_free, ptr);
}

static int
trace_init(void)
{
    memset(&trace_config, 0, sizeof(trace_config));

    memset(&trace_timer, 0, sizeof(trace_timer));

    trace_files = g_hash_table_new_full(g_str_hash,
                                        g_str_equal,
                                        NULL,
                                        (GDestroyNotify)g_hash_table_destroy);
    if (trace_files == NULL) {
        PyErr_NoMemory();
        return -1;
    }

    trace_allocs = g_hash_table_new(g_direct_hash, g_direct_equal);
    if (trace_allocs == NULL) {
        PyErr_NoMemory();
        return -1;
    }

    return 0;
}

static PyObject*
trace_get_filename_obj(int *lineno_p)
{
    PyThreadState *tstate;
    PyFrameObject *frame;
    PyCodeObject *code;

    *lineno_p = -1;

    tstate = PyGILState_GetThisThreadState();
    if (tstate == NULL) {
        if (trace_config.debug) {
            trace_error(
                "failed to get the current thread state (thread %li)\n",
                PyThread_get_thread_ident());
        }
        return NULL;
    }

    frame = tstate->frame;
    if (frame == NULL) {
        if (trace_config.debug) {
            trace_error(
                "failed to get the last frame of "
                "the thread state (thread %li)\n",
                PyThread_get_thread_ident());
        }
        return NULL;
    }

    code = frame->f_code;
    if (code == NULL) {
        if (trace_config.debug) {
            trace_error(
                "failed to get the code object of "
                "the last frame (thread %li)\n",
                PyThread_get_thread_ident());
        }
        return NULL;
    }

    if (code->co_filename == NULL) {
        if (trace_config.debug) {
            trace_error(
                "failed to get the filename of the code object "
                "(thread %li)\n",
                PyThread_get_thread_ident());
        }
        return NULL;
    }

#if PY_MAJOR_VERSION >= 2 && PY_MINOR_VERSION >= 7
    *lineno_p = PyFrame_GetLineNumber(frame);
#else
    *lineno_p = PyCode_Addr2Line(frame->f_code, frame->f_lasti);
#endif
    return code->co_filename;
}

static char*
trace_get_filename(int *lineno_p)
{
    char *filename;
    PyObject *filename_obj;

    filename_obj = trace_get_filename_obj(lineno_p);
    if (!filename_obj)
        return NULL;

#ifdef PYTHON3
    filename = _PyUnicode_AsString(filename_obj);
    if (filename == NULL) {
        PyErr_Clear();
        return NULL;
    }
#else
    filename = PyString_AS_STRING(filename_obj);
#endif
    return filename;
}


static int
trace_register_allocators(void)
{
    g_hash_table_remove_all(trace_files);
    g_hash_table_remove_all(trace_allocs);

    if (Py_GetAllocators(PY_ALLOC_MEM_API,
                         &trace_config.mem_malloc,
                         &trace_config.mem_realloc,
                         &trace_config.mem_free) < 0)
        return -1;

    if (Py_GetAllocators(PY_ALLOC_OBJECT_API,
                         &trace_config.object_malloc,
                         &trace_config.object_realloc,
                         &trace_config.object_free) < 0)
        return -1;

    if (Py_SetAllocators(PY_ALLOC_MEM_API,
                         trace_mem_malloc,
                         trace_mem_realloc,
                         trace_mem_free) < 0)
        return -1;

    if (Py_SetAllocators(PY_ALLOC_OBJECT_API,
                         trace_object_malloc,
                         trace_object_realloc,
                         trace_object_free) < 0)
        return -1;

#ifdef WITH_FREE_LIST
    if (_PyFreeList_SetAllocators(trace_free_list_alloc,
                                  trace_free_list_free) < 0)
        return -1;
#endif

    return 0;
}

static int
trace_unregister_allocators(void)
{
    int res = 0;

    if (Py_SetAllocators(PY_ALLOC_MEM_API,
                         trace_config.mem_malloc,
                         trace_config.mem_realloc,
                         trace_config.mem_free) < 0)
        res = -1;

    if (Py_SetAllocators(PY_ALLOC_OBJECT_API,
                         trace_config.object_malloc,
                         trace_config.object_realloc,
                         trace_config.object_free) < 0)
        res = -1;

    return res;
}

PyDoc_STRVAR(trace_enable_doc,
    "enable()\n"
    "\n"
    "Start tracing Python memory allocations.");

static PyObject*
py_trace_enable(PyObject *self)
{
    if (!trace_config.enabled) {
        if (trace_register_allocators() < 0) {
            PyErr_SetString(PyExc_RuntimeError,
                            "Failed to register memory allocators");
            return NULL;
        }
    }

    trace_config.enabled = 1;
    Py_INCREF(Py_None);
    return Py_None;
}

static void
trace_timer_stop(void)
{
    trace_timer.enabled = 0;
    Py_CLEAR(trace_timer.callback);
    Py_CLEAR(trace_timer.args);
    Py_CLEAR(trace_timer.kwargs);
}

PyDoc_STRVAR(trace_disable_doc,
    "disable()\n"
    "\n"
    "Stop tracing Python memory allocations\n"
    "and stop the timer started by start_timer().");

static PyObject*
py_trace_disable(PyObject *self)
{
    trace_timer_stop();

    if (trace_config.enabled) {
        trace_config.enabled = 0;

        g_hash_table_remove_all(trace_allocs);
        g_hash_table_remove_all(trace_files);

        if (trace_unregister_allocators() < 0) {
            PyErr_SetString(PyExc_RuntimeError,
                            "Failed to unregister memory allocators");
            return NULL;
        }
    }

    Py_INCREF(Py_None);
    return Py_None;
}

PyDoc_STRVAR(trace_start_timer_doc,
    "start_timer(delay: int, callback: callable, args: tuple=None, kwargs: dict=None)\n"
    "\n"
    "Start a timer: call the 'callback' every 'delay' seconds\n"
    "when the memory allocator is used.");

static PyObject*
py_trace_start_timer(PyObject *self, PyObject *args)
{
    int delay;
    PyObject *callback;
    PyObject *cb_args = NULL;
    PyObject *kwargs = NULL;

    if (!PyArg_ParseTuple(args, "iO|OO:start_timer",
                          &delay, &callback, &cb_args, &kwargs))
        return NULL;

    if (delay < 1) {
        PyErr_SetString(PyExc_ValueError, "delay must be greater than 0");
        return NULL;
    }

    if (!PyCallable_Check(callback)) {
        PyErr_Format(PyExc_TypeError,
                     "callback must be a callable object, not %s",
                     Py_TYPE(callback)->tp_name);
        return NULL;
    }

    if (cb_args != NULL && !PyTuple_Check(cb_args)) {
        PyErr_SetString(PyExc_TypeError,
                        "argument list must be a tuple");
        return NULL;
    }

    if (kwargs != NULL && !PyDict_Check(kwargs)) {
        PyErr_SetString(PyExc_TypeError,
                        "keyword list must be a dictionary");
        return NULL;
    }

    /* Disable temporary the timer because Py_CLEAR may call it */
    trace_timer_stop();

    Py_INCREF(callback);
    trace_timer.callback = callback;
    Py_XINCREF(cb_args);
    trace_timer.args = cb_args;
    Py_XINCREF(kwargs);
    trace_timer.kwargs = kwargs;

    trace_timer.delay = delay;
    trace_timer.next_trigger = time(NULL) + delay;
    trace_timer.enabled = 1;

    Py_INCREF(Py_None);
    return Py_None;
}

PyDoc_STRVAR(trace_stop_timer_doc,
    "stop_timer()\n"
    "\n"
    "Stop the timer started by start_timer().");

PyObject*
py_trace_stop_timer(PyObject *self)
{
    trace_timer_stop();

    Py_INCREF(Py_None);
    return Py_None;
}

typedef struct {
    PyObject *file_dict;
    PyObject *line_dict;
    int err;
    char *current_filename;
} trace_get_stats_t;

static PyObject*
trace_decode_filename(const char *filename)
{
#ifdef PYTHON3
    return PyUnicode_FromString(filename);
#else
    return PyString_FromString(filename);
#endif
}

static PyObject*
trace_lineno_as_obj(int lineno)
{
    if (lineno != -1) {
#ifdef PYTHON3
        return PyLong_FromLong(lineno);
#else
        return PyInt_FromLong(lineno);
#endif
    }
    else {
        Py_INCREF(Py_None);
        return Py_None;
    }
}

PyDoc_STRVAR(trace_get_stats_doc,
    "_get_stats() -> dict\n"
    "\n"
    "Get allocation statistics per Python file as a dict:\n"
    "{filename (str): {lineno (int) -> (size (int), count (int))}}");

static void
trace_get_stats_fill_line(gpointer key, gpointer value, gpointer user_data)
{
    int lineno = GPOINTER_TO_INT(key);
    trace_file_stats_t *stats = value;
    trace_get_stats_t *get_stats = user_data;
    PyObject *line_obj = NULL, *size = NULL, *count = NULL, *tuple = NULL;
    int res;

    if (get_stats->err)
        return;

    line_obj = trace_lineno_as_obj(lineno);
    if (line_obj == NULL) {
        get_stats->err = 1;
        goto done;
    }

    size = PYINT_FROM_SSIZE_T(stats->size);
    if (size == NULL) {
        get_stats->err = 1;
        goto done;
    }

    count = PYINT_FROM_SSIZE_T(stats->count);
    if (count == NULL) {
        get_stats->err = 1;
        goto done;
    }

    tuple = Py_BuildValue("(NN)", size, count);
    size = NULL;
    count = NULL;
    if (tuple == NULL) {
        get_stats->err = 1;
        goto done;
    }

    res = PyDict_SetItem(get_stats->line_dict, line_obj, tuple);
    if (res < 0) {
        get_stats->err = 1;
        goto done;
    }

done:
    Py_XDECREF(line_obj);
    Py_XDECREF(size);
    Py_XDECREF(count);
    Py_XDECREF(tuple);
}

static void
trace_get_stats_fill_file(gpointer key, gpointer value, gpointer user_data)
{
    char *filename = key;
    GHashTable *line_hash = value;
    trace_get_stats_t *get_stats = user_data;
    PyObject *file_obj = NULL;
    int res;

    if (get_stats->err)
        return;

    get_stats->current_filename = filename;
    get_stats->line_dict = NULL;

    file_obj = trace_decode_filename(filename);
    if (file_obj == NULL) {
        get_stats->err = 1;
        goto done;
    }

    get_stats->line_dict = PyDict_New();
    if (get_stats->line_dict == NULL) {
        get_stats->err = 1;
        goto done;
    }

    g_hash_table_foreach(line_hash, trace_get_stats_fill_line, user_data);
    if (get_stats->err)
        goto done;

    res = PyDict_SetItem(get_stats->file_dict, file_obj, get_stats->line_dict);
    Py_CLEAR(file_obj);
    Py_CLEAR(get_stats->line_dict);
    if (res < 0) {
        get_stats->err = 1;
        goto done;
    }

done:
    Py_XDECREF(file_obj);
    Py_XDECREF(get_stats->line_dict);
}

static PyObject*
py_trace_get_stats(PyObject *self)
{
    int was_enabled;

    /* don't track memory allocations done by trace_get_stats_fill_file()
     * to not modify hash tables */
    was_enabled = trace_config.enabled;
    trace_config.enabled = 0;

    trace_get_stats_t get_stats;
    get_stats.file_dict = PyDict_New();
    if (get_stats.file_dict == NULL)
        goto done;
    get_stats.err = 0;

    g_hash_table_foreach(trace_files, trace_get_stats_fill_file, &get_stats);
    if (get_stats.err) {
        Py_CLEAR(get_stats.file_dict);
        goto done;
    }

done:
    trace_config.enabled = was_enabled;
    return get_stats.file_dict;
}

PyDoc_STRVAR(trace_get_object_trace_doc,
    "_get_object_trace(obj) -> (size: int, filename: str, lineno: int)\n"
    "\n"
    "Get the memory allocation trace of an object.\n"
    "Return (size, filename, lineno) if the source is known,\n"
    "None otherwise.");

static PyObject*
py_trace_get_object_trace(PyObject *self, PyObject *obj)
{
    PyTypeObject *type;
    void *ptr;
    trace_alloc_t *trace;
    PyObject *size = NULL, *filename = NULL, *lineno = NULL;

    type = Py_TYPE(obj);
    if (PyType_IS_GC(type))
        ptr = (void *)((char *)obj - sizeof(PyGC_Head));
    else
        ptr = (void *)obj;
    trace = g_hash_table_lookup(trace_allocs, ptr);
    if (trace == NULL) {
        Py_INCREF(Py_None);
        return Py_None;
    }

    size = PYINT_FROM_SSIZE_T(trace->size);
    if (size == NULL)
        goto error;

    filename = trace_decode_filename(trace->filename);
    if (filename == NULL)
        goto error;

    lineno = trace_lineno_as_obj(trace->lineno);
    if (lineno == NULL)
        goto error;

    return Py_BuildValue("(NNN)", size, filename, lineno);

error:
    Py_XDECREF(size);
    Py_XDECREF(filename);
    Py_XDECREF(lineno);
    return NULL;
}

static int
trace_atexit_register(PyObject *module)
{
    PyObject *disable = NULL, *atexit = NULL, *func = NULL;
    PyObject *result;
    int ret = -1;

    disable = PyObject_GetAttrString(module, "disable");
    if (disable == NULL)
        goto done;

    atexit = PyImport_ImportModule("atexit");
    if (atexit == NULL) {
        if (!PyErr_Warn(PyExc_ImportWarning,
                       "atexit module is missing: "
                       "cannot automatically disable tracemalloc at exit"))
        {
            PyErr_Clear();
            return 0;
        }
        goto done;
    }

    func = PyObject_GetAttrString(atexit, "register");
    if (func == NULL)
        goto done;

    result = PyObject_CallFunction(func, "O", disable);
    if (result == NULL)
        goto done;
    Py_DECREF(result);

    ret = 0;

done:
    Py_XDECREF(disable);
    Py_XDECREF(func);
    Py_XDECREF(atexit);
    return ret;
}



static PyMethodDef trace_methods[] = {
    {"enable", (PyCFunction)py_trace_enable, METH_NOARGS, trace_enable_doc},
    {"disable", (PyCFunction)py_trace_disable, METH_NOARGS, trace_disable_doc},
    {"_get_object_trace", (PyCFunction)py_trace_get_object_trace, METH_O, trace_get_object_trace_doc},
    {"_get_stats", (PyCFunction)py_trace_get_stats, METH_NOARGS, trace_get_stats_doc},
    {"start_timer", py_trace_start_timer, METH_VARARGS, trace_start_timer_doc},
    {"stop_timer", (PyCFunction)py_trace_stop_timer, METH_NOARGS, trace_stop_timer_doc},
    {NULL,              NULL}           /* sentinel */
};

PyDoc_STRVAR(trace_doc,
"Track memory allocations per Python file.");

#ifdef PYTHON3
static struct PyModuleDef sandbox_module = {
    PyModuleDef_HEAD_INIT,
    "_tracemalloc",
    trace_doc,
    -1,
    trace_methods,
    NULL,
    NULL,
    NULL,
    NULL
};
#endif

PyMODINIT_FUNC
#ifdef PYTHON3
PyInit__tracemalloc(void)
#else
init_tracemalloc(void)
#endif
{
    PyObject *m, *version;

    if (trace_init() < 0)
        goto error;

#ifdef PYTHON3
    m = PyModule_Create(&sandbox_module);
#else
    m = Py_InitModule3("_tracemalloc", trace_methods, trace_doc);
#endif
    if (m == NULL)
        goto error;

#ifdef PYTHON3
    version = PyUnicode_FromString(VERSION);
#else
    version = PyString_FromString(VERSION);
#endif
    if (version == NULL)
        goto error;
    PyModule_AddObject(m, "__version__", version);

    if (trace_atexit_register(m) < 0)
        goto error;

#ifdef PYTHON3
    return m;
#endif

error:
#ifdef PYTHON3
    return NULL;
#else
    return;
#endif
}

