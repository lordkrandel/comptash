# comptash
Helpers for the `odoo-bin shell`

Just run `odoo-bin shell --shell-file=comptash.py`

<img width="904" height="835" alt="immagine" src="https://github.com/user-attachments/assets/c146b52b-c0df-40ca-a434-1db078954f58" />

```
    j(x, indent=4)
        Pretty-prints a json_dumps of an object

    var(*args, value=None)
        Retrieves variables from ```globals```, or assigns a variable into globals and IPython ```user_ns```.

    unpack(obj, *args)
        Unpacks specific attributes or keys from an object or dictionary by name.

    clip(text)
        Copy text to clipboard. Requires clip tools in the PATH (i.e. ```xclip```)

    cache_diff(env=None, reset=False, indent='    ')
        Tracks both ORM field cache and ormcache entries added during execution.

    change_user(domain=None)
        Switch the current shell context user.

    BaseModel:
        search(self, domain=None, *args, **kwargs)
            Searches records with support for string domain queries (e.g. 'key like mail%').
        json_search(self, domain_or_fields=None, fields=None, view_type='list', limit=None, offset=0, order=None)
            Executes search_read and returns a JSON-serializable list of dictionary records.
        all
            Syntactic sugar for search([]).
        spec(self, fields=None, view_type='list')
            Generates a web view specification dictionary for the model's fields.
        display(self, fields=None, msg=None)
            Formats a recordset into a list of tuples: [(id, display_name), ...]
        describe(self, fields=None)
            Serializes a recordset, showing given fields.
        select(self, msg=None, fields=None)
            Interactively selects a record from the recordset and updates the `selected` global variable.

    IrAttachment:
        json_read(self)
            Loads and parses the attachment's raw JSON content into a dictionary.
        json_write(self, dict_data, commit=True)
            Dumps a dictionary as formatted JSON into the attachment's raw content.
```
