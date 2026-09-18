# ruff: file-ignore [print,import-outside-top-level]

import inspect
import json
import re
import readline
import shlex
import shutil
import subprocess
import sys
from ast import literal_eval
from datetime import datetime, date
from contextlib import contextmanager
from pathlib import Path  # ruff: ignore [unused-import]

from IPython.core import ultratb
from IPython.terminal.prompts import Prompts
from pygments.token import Token

import odoo  # ruff: ignore [unused-import]
from odoo.addons.base.models.ir_attachment import IrAttachment
from odoo.release import version_info


envy = None
ipy = None
BaseModel = None
Field = None

JSON_INDENT = 4
HELPERS = {}


def _helper(target=None):
    """Decorator supporting @_helper and @_helper(Class).
       Registers tools into HELPERS and automatically monkeypatches target classes. """
    def decorator(func):
        # Unwrap property descriptors to access the underlying getter function name
        if isinstance(func, property):
            func_name = func.fget.__name__
        else:
            func_name = func.__name__

        if target is None:
            # Standalone functions (e.g. clip, j, var)
            HELPERS[func_name] = func
        else:
            # Class-bound methods (e.g. BaseModel, IrAttachment)
            class_name = target.__name__ if hasattr(target, '__name__') else str(target)
            if class_name not in HELPERS:
                HELPERS[class_name] = {}
            HELPERS[class_name][func_name] = func

            # Auto-monkeypatch onto the class if target is a model/type
            if isinstance(target, type):
                setattr(target, func_name, func)

        return func

    if callable(target) and not isinstance(target, type):
        # Called as plain @_helper without arguments
        func = target
        target = None
        return decorator(func)

    return decorator


class Envy:
    def __init__(self, env, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.env = env
        self.commit = self.env.cr.commit
        self.rollback = self.env.cr.rollback
        self.major = int(str(version_info[0]).replace("saas~", ""))
        self.minor = int(str(version_info[1]))

    def __dir__(self):
        attrs = set(super().__dir__())
        attrs.update(model.replace('.', '_') for model in self.env.registry)
        return list(attrs)

    def __getattr__(self, name):
        """ If the attribute is not in the class, search the registry """
        pattern = re.sub(r"(\\?[\._])", r"[._]", re.escape(name))
        pattern = re.compile(f"^{pattern}$")
        for item in self.env.registry:
            if re.match(pattern, item):
                return self.env[item]
        raise AttributeError(f"'Envy' object has no attribute '{name}'")


def _monkeypatch_cache(env=None):
    env = env or envy.env
    if envy.major <= 18:
        type(env.cache).invalidate_all = env.invalidate_all


def _monkeypatch_xmlid():
    @_helper
    @property
    def xmlid(self):
        """ Syntactic sugar for ``record._get_external_ids()[record.id]`` """
        return next(iter(self._get_external_ids()[self.id]), None)


def _monkeypatch_attachment_json():
    @_helper(IrAttachment)
    def json_read(self):
        """Loads and parses the attachment's raw JSON content into a dictionary."""
        return json.loads(self.raw)

    @_helper(IrAttachment)
    def json_write(self, dict_data, commit=True):
        """Dumps a dictionary as formatted JSON into the attachment's raw content."""
        self.write({
            'raw': json.dumps(dict_data, indent=JSON_INDENT),
            'mimetype': 'application/json',
        })


def _monkeypatch_get():
    """ ``__get__`` becomes ``mapped`` on multiple-records recordsets. """
    __old___get__ = Field.__get__

    def _monkey___get__(self, record, *args, **kwargs):
        try:
            return __old___get__(self, record, *args, **kwargs)
        except ValueError:
            field_name = self.name.split('.')[-1]
            return record.mapped(field_name)

    Field.__get__ = _monkey___get__


def _monkeypatch_spec():
    @_helper(BaseModel)
    def spec(self, fields=None, view_type='list'):
        """Generates a web view specification dictionary for the model's fields."""
        if envy.ir_module_module._get('web').state != 'installed':
            raise NotImplementedError("Web module has to be installed to use spec/jsearch")

        view = self.get_view(None, view_type)
        spec_dict = self._get_fields_spec(view)

        if fields:
            return {
                field: spec_dict.get(field, {})
                for field in fields
                if field in self._fields
            }

        return spec_dict


def _monkeypatch_display():
    @_helper(BaseModel)
    def display(self, fields=None, msg=None):
        """Formats a recordset into a list of tuples: [(id, display_name), ...]"""
        print(msg or '')
        choices = self.describe(fields)
        for idx, (k, *v) in enumerate(choices, 1):
            print(f"    #{idx:<5} [{k:>6}] {', '.join(v)}")

    @_helper(BaseModel)
    def describe(self, fields=None):
        """Serializes a recordset, showing given fields. """
        def describe_record(record):
            nonlocal fields
            fields = fields or []
            return [record.id] + ([record.display_name] if not fields else [record[field] for field in fields])
        return sorted(self.mapped(describe_record))

    @_helper(BaseModel)
    def select(self, msg=None, fields=None):
        """Interactively selects a record from the recordset and updates the `selected` global variable."""
        def input_ignore_history(msg):
            result = input(msg)
            last_idx = readline.get_current_history_length() - 1
            readline.remove_history_item(last_idx)
            return result

        global selected  # ruff: ignore [global-statement]
        self.display(fields=fields)
        while True:
            try:
                ans = int(input_ignore_history(f"\n {f'{msg} ' if msg else ''}# "))
                if 1 <= ans <= len(self):
                    selected = self.sorted(lambda x: x.id)[ans - 1]
                    print(f"selected = {selected}")
                    print()
                    return selected
            except (ValueError, KeyboardInterrupt, EOFError):
                return None


def _monkeypatch_search():
    old_search = BaseModel.search

    @_helper(BaseModel)
    def search(self, domain=None, *args, **kwargs):
        """Searches records with support for string domain queries (e.g. 'key like mail%')."""
        match domain:
            case None:
                domain = []
            case str():
                left, operator, *right = shlex.split(domain, posix=False)
                right = ' '.join(right)
                if operator.lower() == 'in':
                    right = literal_eval(right)
                domain = [(left, operator, right)]
            case tuple() | list():
                pass
        return old_search(self, domain, *args, **kwargs)

    @_helper(BaseModel)
    def json_search(self, domain_or_fields=None, fields=None, view_type='list', limit=None, offset=0, order=None):
        """Executes search_read and returns a JSON-serializable list of dictionary records."""
        def is_seq(x):
            return isinstance(x, tuple | list)
        domain = []
        if fields:
            domain = domain_or_fields
        elif not domain_or_fields and is_seq(domain_or_fields):
            domain = []
        elif domain_or_fields and is_seq(domain_or_fields):
            if is_seq(domain_or_fields[0]) and len(domain_or_fields[0]) == 3:
                domain = domain_or_fields
            else:
                fields = domain_or_fields
        spec = self.spec(fields=fields, view_type=view_type)
        domain = domain or ([('id', 'in', self.ids)] if self else [])
        return self.web_search_read(domain, spec, limit=limit, offset=offset, order=order)['records']

    @_helper(BaseModel)
    @property
    def all(self):
        """Syntactic sugar for search([])."""
        return self.search()


def _monkeypatch_IPython():
    ultratb.VerboseTB._tb_highlight = "bg:#700000"


# ----------------------------------------------
# TOOLS
# ----------------------------------------------

@_helper
def j(x, indent=JSON_INDENT):
    """ Pretty-prints a json_dumps of an object """
    def default_serializer(obj):
        """ Fallback for types json.dumps doesn't handle natively. """
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if isinstance(obj, (set, tuple)):
            return list(obj)
        if hasattr(obj, "__dict__"):
            return obj.__dict__
        return str(obj)

    print(json.dumps(x, indent=indent, default=default_serializer, ensure_ascii=False))


@_helper
def var(*args, value=None):
    """Retrieves variables from ```globals```, or assigns a variable into globals and IPython ```user_ns```."""
    if value:
        globals()[args[0]] = value
        if ipy:
            ipy.user_ns[args[0]] = value
        return
    return unpack(globals(), *args)


@_helper
def unpack(obj, *args):
    """Unpacks specific attributes or keys from an object or dictionary by name."""
    def get(arg):
        return getattr(obj, args[0], None) or obj[arg]
    if len(args) > 1:
        return [get(arg) for arg in args]
    return get(args[0])


@_helper
def clip(text):
    """ Copy text to clipboard. Requires clip tools in the PATH (i.e. ```xclip```) """
    if not isinstance(text, str):
        raise TypeError("You're trying to copy something which is not a string")
    match sys.platform:
        case 'darwin':
            subprocess.run('pbcopy', text=True, input=text, check=True)
        case 'win32':
            subprocess.run('clip', text=True, input=text, check=True)
        case 'linux':
            if shutil.which('wl-copy'):
                subprocess.run(['wl-copy'], text=True, input=text, check=True)
            elif shutil.which('xclip'):
                subprocess.run(['xclip', '-selection', 'clipboard'], text=True, input=text, check=True)
            elif shutil.which('xsel'):
                subprocess.run(['xsel', '--clipboard', '--input'], text=True, input=text, check=True)
            else:
                raise Exception("No clipboard tool found (wl-copy, xclip, xsel)")
        case _:
            raise Exception("Unrecognized system platform")


@contextmanager
@_helper
def cache_diff(env=None, reset=False, indent="    "):
    """ Tracks both ORM field cache and ormcache entries added during execution. """
    env = env or self.env

    is_modern = (envy.major > 19) or (envy.major == 19 and envy.minor > 3)

    if reset:
        env.invalidate_all()
        if is_modern and hasattr(env.transaction, 'ormcaches__'):
            for cache_layer in env.transaction.ormcaches__.values():
                if hasattr(cache_layer, 'clear'):
                    cache_layer.clear()

    def _snapshot():
        snapshot = {}

        if is_modern:
            fields_obj = getattr(env.transaction, 'fields', getattr(env, '_fields_cache', None))
            field_dict = getattr(fields_obj, '_cache', getattr(fields_obj, '_field_cache', {})) if fields_obj else {}

            for key, val in field_dict.items():
                if isinstance(key, tuple) and len(key) == 2:
                    field, record_id = key
                    snapshot["ORM", field.model_name, record_id, field.name] = val
        else:
            old_cache = getattr(env, '_cache', getattr(env, 'cache', None))
            for field, field_cache in getattr(old_cache, '_data', {}).items():
                for record_id, val in field_cache.items():
                    snapshot["ORM", field.model_name, record_id, field.name] = val

        # 2. Method LRU Caches (@ormcache)
        if is_modern and hasattr(env.transaction, 'ormcaches__'):
            for cache_name, cache_layer in env.transaction.ormcaches__.items():
                cache_items = getattr(cache_layer, 'snapshot', cache_layer)
                if hasattr(cache_items, 'items'):
                    for key, val in cache_items.items():
                        snapshot["METHOD", cache_name, key] = val

        return snapshot

    def _format_value(val):
        if isinstance(val, set):
            sorted_items = sorted(repr(x) for x in val)
            return "{" + ", ".join(sorted_items) + "}"
        return repr(val)

    def _format_key(entry):
        entry_type = entry[0]
        if entry_type == "ORM":
            _, model, rid, field_name = entry
            return f"[ORM] {model}({rid}).{field_name}"
        else:
            _, cache_name, key = entry
            formatted_items = []
            for item in key:
                if callable(item):
                    formatted_items.append(f"<func {item.__module__}.{item.__qualname__}>")
                else:
                    formatted_items.append(repr(item))
            key_str = f"({', '.join(formatted_items)})"
            return f"[METHOD:{cache_name}] {key_str}"

    before_snapshot = _snapshot()
    try:
        yield
    finally:
        after_snapshot = _snapshot()
        new_keys = set(after_snapshot.keys()) - set(before_snapshot.keys())

        sub_indent = indent * 2
        print(f"\n--- [CACHE DIFF: {len(new_keys)} new entries cached] ---")
        if not new_keys:
            print(f"{indent}(No new cache entries)")
        else:
            for k in sorted(new_keys, key=lambda x: (x[0], str(x[1]))):
                header = _format_key(k)
                value_str = _format_value(after_snapshot[k])
                print(f"{indent}{header}")
                print(f"{sub_indent}= {value_str}\n")


@_helper
def change_user(domain=None):
    """Switch the current shell context user."""
    global self  # ruff: ignore [global-statement]
    users = envy.res_users.with_context(active_test=False).sudo().search(domain or [])
    usr = users.select("Change environment user:")
    if not usr:
        return

    env = self.env(user=usr, context=dict(self.env.context, allowed_company_ids=usr.company_ids.ids))
    self = usr.with_env(env)
    set_prompt()
    print(f"User changed to: [{self.id:>6}] {self.name}")


def set_prompt():
    class OdooPrompt(Prompts):
        def in_prompt_tokens(self, cli=None):
            return [
                (Token.Prompt, '['),
                (Token.PromptNum, f"{envy.env.user.name}"),
                (Token.Prompt, ' | '),
                (Token.Keyword, f"{', '.join(envy.env.user.company_ids.mapped('name'))}"),
                (Token.Prompt, '] In ['),
                (Token.PromptNum, str(self.shell.execution_count)),
                (Token.Prompt, ']: '),
            ]

    if envy and envy.env:
        if ipy:
            ipy.prompts = OdooPrompt(ipy)
        else:
            user = envy.env.user.describe()[0]
            companies = envy.env.companies.describe()
            sys.ps1 = f"\nuser={user}\ncompanies={companies}\n>>> "
    else:
        sys.ps1 = ">>> "


def _indent(level):
    return ' ' * JSON_INDENT * level


def setup_helpers(show=False):
    def printout(x, level=1):
        for k, v in x.items():
            func_indent = f"{_indent(level - 1)}"
            indent = f"{_indent(level)}"
            if callable(v):
                sig = inspect.signature(v)
                print(f"{func_indent}{k.strip()}{sig}")
                if doc := inspect.getdoc(v):
                    for line in doc.split('\n'):
                        print(indent + line.strip())
            elif isinstance(v, property):
                print(f"{func_indent}{k.strip()}")
                if doc := inspect.getdoc(v):
                    print(indent + re.sub(r"\n", " ", doc))
            else:
                print(f"{func_indent}{k.strip()}:")
                printout(v, level + 1)

    for name, helper in HELPERS.items():
        if callable(helper):
            var(name, value=helper)
    if show:
        printout(HELPERS)


def _setup_globals():
    if (get_ipy := var('get_ipython')) and (ip := get_ipy()):
        var('ipy', value=ip)
    if env := var('env'):
        var('envy', value=Envy(env))

    # We need to know the version from the `env` before we can import these """
    def get_base_model():
        if envy.major <= 18:
            from odoo.models import BaseModel
        else:
            from odoo.orm.models import BaseModel
        return BaseModel

    def get_field_model():
        if envy.major <= 18:
            from odoo.fields import Field
        else:
            from odoo.orm.fields import Field
        return Field

    var('BaseModel', value=get_base_model())
    var('Field', value=get_field_model())


def main():
    _setup_globals()
    _monkeypatch_get()
    _monkeypatch_search()
    _monkeypatch_spec()
    _monkeypatch_display()
    _monkeypatch_IPython()
    _monkeypatch_cache()
    _monkeypatch_xmlid()
    _monkeypatch_attachment_json()
    setup_helpers(show=True)

    set_prompt()


if __name__ == '__main__':
    main()
