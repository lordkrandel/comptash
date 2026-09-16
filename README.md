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

        In [2]: envy.res_users.all
            res.users(2, 5)

    describe(self, fields=None)
        Serializes a recordset, showing given fields.

        In [3]: envy.res_users.all.describe()
            [[2, 'Administrator'], [5, 'Rhodio Francesco user']]

    display(self, fields=None, msg=None)
        Formats a recordset into a list of tuples: [(id, display_name), ...]

        In [1]: envy.res_users.all.display()
            #1     [     2] Administrator
            #2     [     5] Rhodio Francesco user

    json_search(self, domain_or_fields=None, fields=None, view_type='list', limit=None, offset=0, order=None)
        Returns JSON representation

        In [12]: envy.ir_config_parameter.json_search([("key", "=like", "digest%")])
        Out[12]: 
            [{'id': 16, 'key': 'digest.default_digest_emails', 'value': 'True'},
             {'id': 17, 'key': 'digest.default_digest_id', 'value': '1'}]

    search(self, domain=None, *args, **kwargs)
        Modified search

            In [13]: envy.ir_config_parameter.search('key like digest%')
            Out[18]: ir.config_parameter(16, 17)

    select(self, msg=None, fields=None)
        Select a record out of a recordset. Returns in the `selected` global variable.

            In [15]: envy.ir_config_parameter.search('key like digest%').select()

                #1     [    16] digest.default_digest_emails
                #2     [    17] digest.default_digest_id

             # 1
            selected = ir.config_parameter(16,)
            Out[15]: ir.config_parameter(16,)

    xmlid
        Syntactic sugar for ``record._get_external_ids()[record.id]`` 
```
