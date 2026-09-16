# comptash
Helpers for the `odoo-bin shell`

Just run `odoo-bin shell --shell-file=comptash.py`

```
var(*args)
    unpacks globals into variables

clip(text)
    Copy text to clipboard

change_user(domain=None)
    Switch the current shell context user.

cache_diff(env=None, reset=False, indent='    ')
    Tracks both ORM field cache and ormcache entries added during execution.

IrAttachment:
    json_read(self)
        Loads the json content
    json_write(self, dict_data, commit=True)
        Dumps a dictionary inside the content

BaseModel:
    all
        Syntactic sugar for search([])
    describe(self, fields=None)
        Serializes a recordset, showing given fields.
    display(self, fields=None, msg=None)
        Formats a recordset into a list of tuples: [(id, display_name), ...]
    json_search(self, domain_or_fields=None, fields=None, view_type='list', limit=None, offset=0, order=None)
        Returns JSON representation
        envy.ir_config_parameter.json_search("key like mail%")
        envy.ir_config_parameter.all.json_search(["key", "value"])
    search(self, domain=None, *args, **kwargs)
        Modified search, i.e.:
        envy.ir_config_parameter.search('key like mail%').display()
    select(self, msg=None, fields=None)
        Select a record out of a recordset. Returns in the `selected` global variable.
    xmlid
        Syntactic sugar for ``record._get_external_ids()[record.id]`` 
```
