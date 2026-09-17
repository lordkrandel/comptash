# ruff: file-ignore [print,import-outside-top-level]

import copy
import inspect
import json
import re
import readline
import shlex
import shutil
import subprocess
import sys
from ast import literal_eval
from contextlib import contextmanager
from pathlib import Path
from IPython.core import ultratb
from IPython.terminal.prompts import Prompts
from pygments.token import Token

import odoo
from odoo.addons.base.models.ir_attachment import IrAttachment
from odoo.release import version_info

self = locals().get('self')
JSON_INDENT = 4


class ShellObject:
    env = self.env


class Envy(ShellObject):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.commit = self.env.cr.commit
        self.rollback = self.env.cr.rollback
        self.major = int(str(version_info[0]).replace("saas~", ""))
        self.minor = int(str(version_info[1]))

    def __dir__(self):
        return [
            k.replace('.', '_')
            for k in self.env.registry
        ]

    def __getattr__(self, name):
        """ If the attribute is not in the class, search the registry """
        pattern = re.sub(r"(\\?[\._])", r"[._]", re.escape(name))
        pattern = re.compile(f"^{pattern}$")
        for item in self.env.registry:
            if re.match(pattern, item):
                return self.env.__getitem__(item)
        raise KeyError(name)


def get_class(name):
    if envy.major <= 18:
        from odoo.fields import Field
        from odoo.models import BaseModel
    else:
        from odoo.orm.fields import Field
        from odoo.orm.models import BaseModel
    return {
        'Field': Field,
        'BaseModel': BaseModel,
    }.get(name)


def _monkeypatch_get():
    """ ``__get__`` becomes ``mapped`` on multiple-records recordsets. """
    Field = get_class('Field')
    __old___get__ = Field.__get__

    def _monkey___get__(self, record, *args, **kwargs):
        try:
            return __old___get__(self, record, *args, **kwargs)
        except ValueError:
            field_name = self.name.split('.')[-1]
            return record.mapped(field_name)
    Field.__get__ = _monkey___get__


def _monkeypatch_spec(fields=None, view_type='list'):
    def get_spec(self, fields, view_type):
        if not envy.ir_module_module._get('web').state == 'installed':
            raise NotImplementedError("Web module has to be installed to jsearch")
        view = self.get_view(None, view_type)
        spec = self._get_fields_spec(view)
        if fields:
            spec = {
                k: copy.deepcopy(v)
                for k, v in spec.items()
                if k in fields
            }
        return spec

    BaseModel = get_class('BaseModel')
    BaseModel.spec = get_spec


def _monkeypatch_display():
    def display(self, fields=None, msg=None):
        """Formats a recordset into a list of tuples: [(id, display_name), ...]"""
        print(msg or '')
        choices = self.describe(fields)
        for idx, (k, *v) in enumerate(choices, 1):
            print(f"    #{idx:<5} [{k:>6}] {', '.join(v)}")

    def describe(self, fields=None):
        """Serializes a recordset, showing given fields. """
        def describe_record(record):
            nonlocal fields
            fields = fields or []
            return [record.id] + ([record.display_name] if not fields else [record[field] for field in fields])
        return sorted(self.mapped(describe_record))

    def select(self, msg=None, fields=None):
        """Select a record out of a recordset. Returns in the `selected` global variable."""
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

    BaseModel = get_class('BaseModel')
    BaseModel.describe = describe
    BaseModel.display = display
    BaseModel.select = select


def _monkeypatch_search():
    """ use strings """
    BaseModel = get_class('BaseModel')
    old_search = BaseModel.search

    def _monkey_search(self, domain=None, *args, **kwargs):
        """ Modified search, i.e.:
            envy.ir_config_parameter.search('key like mail%').display() """
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

    def _monkey_json_search(self, domain_or_fields=None, fields=None, view_type='list', limit=None, offset=0, order=None):
        """ Returns JSON representation
            envy.ir_config_parameter.json_search("key like mail%")
            envy.ir_config_parameter.all.json_search(["key", "value"])
        """
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

    BaseModel.search = _monkey_search
    BaseModel.json_search = _monkey_json_search

    def _all(self):
        """ Syntactic sugar for search([])"""
        return self.search()

    BaseModel.all = property(_all)


def _monkeypatch_IPython():
    ultratb.VerboseTB._tb_highlight = "bg:#700000"


class Filestore(ShellObject):
    @classmethod
    @property
    def path(self):
        return Path(odoo.tools.config.filestore(self.env.cr.dbname))

    @classmethod
    def orphans(cls, domain=None, include_folders=False):
        attachments = cls.env['ir.attachment'].search(domain or [])
        ir_attachment_files = {path for path in attachments.mapped("store_fname") if path}
        filestore_files = {
            str(path.relative_to(cls.path))
            for path in Path(cls.path).glob('./**/*')
            if path and (include_folders or not Path(path).is_dir())
        }
        return sorted(filestore_files - ir_attachment_files)

    @classmethod
    def content(cls, filenames, summary=2000, start=0, count=10):
        if isinstance(filenames, str):
            filenames = [filenames]
        results = {}
        for filename in filenames[start:start + count + 1]:
            with open(cls.path / filename, "rb") as f:
                content = repr(f.read())
            if summary:
                results[filename] = content[:summary]
            else:
                results[filename] = content
        return results


# ----------------------------------------------
# TOOLS
# ----------------------------------------------

def var(*args):
    """ unpacks globals into variables """
    return unpack(globals(), *args)


def unpack(obj, *args):
    def get(arg):
        return getattr(obj, args[0], None) or obj[arg]
    if len(args) > 1:
        return [get(arg) for arg in args]
    return get(args[0])


def clip(text):
    """ Copy text to clipboard """
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


def _monkeypatch_cache(env=None):
    env = env or self.env
    if envy.major <= 18:
        type(env.cache).invalidate_all = env.invalidate_all


def input_ignore_history(msg):
    result = input(msg)
    last_idx = readline.get_current_history_length() - 1
    readline.remove_history_item(last_idx)
    return result


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
    env = self.env
    if env and hasattr(env, "user"):
        if ip := var('get_ipython')():
            class OdooPrompt(Prompts):
                def in_prompt_tokens(self, cli=None):
                    return [
                        (Token.Prompt, '['),
                        (Token.PromptNum, f"{env.user.name}"),
                        (Token.Prompt, ' | '),
                        (Token.Keyword, f"{', '.join(env.user.company_ids.mapped('name'))}"),
                        (Token.Prompt, '] In ['),
                        (Token.PromptNum, str(self.shell.execution_count)),
                        (Token.Prompt, ']: '),
                    ]
            ip.prompts = OdooPrompt(ip)
        else:
            user = self.env.user.describe()[0]
            companies = self.env.companies.describe()
            sys.ps1 = f"\nuser={user}\ncompanies={companies}\n>>> "
    else:
        sys.ps1 = ">>> "


def _monkeypatch_xmlid():
    BaseModel = get_class('BaseModel')

    def xmlid(self):
        """ Syntactic sugar for ``record._get_external_ids()[record.id]`` """
        return next(iter(self._get_external_ids()[self.id]), None)

    BaseModel.xmlid = property(xmlid)


def _monkeypatch_attachment_json():
    def json_read(self):
        """ Loads the json content """
        return json.loads(self.raw)

    def json_write(self, dict_data, commit=True):
        """ Dumps a dictionary inside the content """
        self.write({
            'raw': json.dumps(dict_data, indent=JSON_INDENT),
            'mimetype': 'application/json',
        })

    IrAttachment.json_read = json_read
    IrAttachment.json_write = json_write


def setup_helpers(show=False):
    def printout(x, level=1):
        for k, v in x.items():
            func_indent = f"{' ' * 4 * (level - 1)}"
            indent = f"{' ' * 4 * level}"
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

    BaseModel = get_class('BaseModel')
    HELPERS = {
        'var': var,
        'clip': clip,
        'change_user': change_user,
        'cache_diff': cache_diff,
        'IrAttachment': {
            'json_read': IrAttachment.json_read,
            'json_write': IrAttachment.json_write,
        },
        'BaseModel': {
            'all': BaseModel.all,
            'describe': BaseModel.describe,
            'display': BaseModel.display,
            'json_search': BaseModel.json_search,
            'search': BaseModel.search,
            'select': BaseModel.select,
            'xmlid': BaseModel.xmlid,
        }
    }
    for name, helper in HELPERS.items():
        if callable(helper):
            globals()[name] = helper
    if show:
        printout(HELPERS)


def main(envy):

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
    envy = Envy()
    main(envy)
