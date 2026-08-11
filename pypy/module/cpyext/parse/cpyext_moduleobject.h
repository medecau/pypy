typedef struct PyModuleDef_Base {
  PyObject_HEAD
  PyObject* (*m_init)(void);
  Py_ssize_t m_index;
  PyObject* m_copy;
} PyModuleDef_Base;

#define PyModuleDef_HEAD_INIT { \
    PyObject_HEAD_INIT(NULL)    \
    NULL, /* m_init */          \
    0,    /* m_index */         \
    NULL, /* m_copy */          \
  }

struct PyModuleDef_Slot;
/* New in 3.5 */
typedef struct PyModuleDef_Slot{
    int slot;
    void *value;
} PyModuleDef_Slot;

#define Py_mod_create 1
#define Py_mod_exec 2
/* New in 3.12.  PyPy has no subinterpreters, so the value a module supplies
   is only validated, never acted on. */
#define Py_mod_multiple_interpreters 3

#define _Py_mod_LAST_SLOT 3

/* for Py_mod_multiple_interpreters: */
#define Py_MOD_MULTIPLE_INTERPRETERS_NOT_SUPPORTED ((void *)0)
#define Py_MOD_MULTIPLE_INTERPRETERS_SUPPORTED ((void *)1)
#define Py_MOD_PER_INTERPRETER_GIL_SUPPORTED ((void *)2)


typedef struct PyModuleDef{
  PyModuleDef_Base m_base;
  const char* m_name;
  const char* m_doc;
  Py_ssize_t m_size;
  PyMethodDef *m_methods;
  struct PyModuleDef_Slot* m_slots;
  traverseproc m_traverse;
  inquiry m_clear;
  freefunc m_free;
} PyModuleDef;

typedef struct {
    PyObject_HEAD
    struct PyModuleDef *md_def;
    void *md_state;
} PyModuleObject;
